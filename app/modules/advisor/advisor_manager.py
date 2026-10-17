"""PRD AdvisorService: query → route → context snapshot → LLM → persisted, grounded answer (§3.1)."""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.config import settings
from app.enums.context_category import Category
from app.modules.advisor.prompts import SYSTEM_PROMPT
from app.modules.advisor.proposal_manager import proposal_manager
from app.modules.context.context_builder_manager import ContextBuilderManager, context_builder_manager
from app.modules.context.context_routing_manager import ContextRoutingManager, context_routing_manager
from app.modules.context.privacy_manager import privacy_manager
from app.modules.crud.advisor_handler import context_snapshot_handler, conversation_handler, message_handler
from app.modules.crud.audit_log_handler import audit_log_handler
from app.modules.database.model import AdvisorConversation
from app.modules.documents.retrieval import visible_documents
from app.modules.llm.errors import AdvisorError
from app.modules.llm.llm_gateway_manager import LLMGatewayManager, llm_gateway_manager
from app.schema.advisor_schema import AskOptions
from app.schema.context_schema import RouteDecision
from app.schema.llm_schema import LLMRequest


class AdvisorManager:
    def __init__(self, gateway: LLMGatewayManager, router: ContextRoutingManager, builder: ContextBuilderManager,
                 history_limit: int):
        self.gateway = gateway
        self.router = router
        self.builder = builder
        self.history_limit = history_limit

    # --- routing / context ---------------------------------------------------------------

    def route(self, session: Session, query: str, conversation: AdvisorConversation | None,
              options: AskOptions) -> RouteDecision:
        previous = None
        if conversation is not None:
            last = context_snapshot_handler.get_latest_for_conversation(session, conversation.id)
            if last is not None:
                previous = frozenset(Category(c) for c in last.context_categories)
        return self.router.route(
            query,
            excluded=privacy_manager.get_excluded(session) | options.exclude,
            override=options.categories,
            previous=previous,
            domain=conversation.domain if conversation else None,
        )

    def document_options(self, session: Session, conversation: AdvisorConversation | None,
                         options: AskOptions) -> AskOptions:
        if options.document_ids is not None:
            return options
        last = context_snapshot_handler.get_latest_for_conversation(session, conversation.id) if conversation else None
        ids = last.payload.get("document_scope", {}).get("document_ids", []) if last else []
        return replace(options, document_ids=tuple(ids))

    def build_context(self, session, query, conversation, options, conversation_id=None):
        options = self.document_options(session, conversation, options)
        route = self.route(session, query, conversation, options)
        excluded = privacy_manager.get_excluded(session) | options.exclude
        if options.document_search and options.document_ids:
            # Explicit documents supply their topics, but cannot bypass a sharing exclusion.
            docs = visible_documents(session, document_ids=options.document_ids, excluded_categories=excluded)
            topics = frozenset(Category(c) for d in docs for c in d.categories)
            route = replace(route, requested=route.requested | topics,
                            selected=(route.selected | topics) - excluded)
        inherited_citations, dependencies = {}, {}
        if conversation is not None:
            for message in self.safe_history(session, conversation.id, 2**63 - 1, route, options):
                snapshot = context_snapshot_handler.get(session, message.context_snapshot_id)
                for citation in snapshot.payload.get("data", {}).get("search_documents", {}).get("citations", []):
                    inherited_citations[citation["ref"]] = citation
                for dependency in snapshot.payload.get("document_dependencies", []):
                    dependencies[(dependency["document_id"], dependency["version_id"])] = dependency
        package = self.builder.build(session, route, conversation_id=conversation_id, query=query,
                                     document_search=options.document_search,
                                     document_ids=options.document_ids or (), excluded=excluded,
                                     inherited_citations=list(inherited_citations.values()),
                                     inherited_dependencies=list(dependencies.values()))
        return route, package, options

    def safe_history(self, session, conversation_id, before_id, route, options):
        history = message_handler.get_history(session, conversation_id, before_id, self.history_limit)
        allowed = {str(c) for c in route.selected}
        visible = {d.id: d for d in visible_documents(session, categories=route.selected,
                   excluded_categories=privacy_manager.get_excluded(session) | options.exclude)}
        safe = []
        for message in history:
            snapshot = context_snapshot_handler.get(session, message.context_snapshot_id) if message.context_snapshot_id else None
            # Missing provenance (including purged evidence) must not re-enter model context.
            if snapshot is None or not set(snapshot.context_categories).issubset(allowed):
                continue
            citations = snapshot.payload.get("data", {}).get("search_documents", {}).get("citations", [])
            dependencies = snapshot.payload.get("document_dependencies", [])
            evidence = citations + dependencies
            if evidence and not options.document_search:
                continue
            if any(c["document_id"] not in visible or
                   visible[c["document_id"]].active_version_id != c["version_id"] or
                   (options.document_ids and c["document_id"] not in options.document_ids)
                   for c in evidence):
                continue
            safe.append(message)
        return safe

    def preview(self, session: Session, query: str, conversation: AdvisorConversation | None,
                options: AskOptions) -> dict:
        """What would be shared for this question — nothing is persisted or sent."""
        route, package, _ = self.build_context(session, query, conversation, options)
        session.rollback()
        inspector = package.inspector()
        inspector["context_snapshot_id"] = None
        return {"route": route.as_dict(), **inspector}

    # --- conversations -------------------------------------------------------------------

    @staticmethod
    def create_conversation(session: Session, title: str, domain: str | None = None) -> AdvisorConversation:
        conv = conversation_handler.create(session, {"title": title[:200] or "새 상담", "domain": domain})
        session.commit()
        return conv

    @staticmethod
    def get_conversation(session: Session, conversation_id: int) -> AdvisorConversation:
        conv = conversation_handler.get(session, conversation_id)
        if conv is None:
            raise LookupError("conversation not found")
        return conv

    @staticmethod
    def delete_conversation(session: Session, conversation_id: int) -> None:
        """Deletes messages and the context snapshots taken for this conversation (PRD §7.5)."""
        conv = AdvisorManager.get_conversation(session, conversation_id)
        context_snapshot_handler.delete_for_conversation(session, conversation_id)
        conversation_handler.delete(session, conv)
        audit_log_handler.record(session, "user", "conversation.delete", f"advisor_conversations:{conversation_id}")
        session.commit()

    # --- ask -----------------------------------------------------------------------------

    async def ask(self, session: Session, conversation: AdvisorConversation, query: str,
                  options: AskOptions | None = None) -> AsyncIterator[dict]:
        options = options or AskOptions()
        route, package, options = await asyncio.to_thread(
            self.build_context, session, query, conversation, options, conversation.id)
        user_msg = message_handler.create(session, {
            "conversation_id": conversation.id, "role": "user", "content": query,
            "context_snapshot_id": package.snapshot_id,
        })
        conversation_handler.update(session, conversation, {"updated_at": datetime.now(UTC)})
        session.commit()
        yield {"type": "context", "route": route.as_dict(), **package.inspector()}

        model = None
        parts: list[str] = []
        settled = False
        try:
            model = await self.gateway.resolve_model(session)
            history = self.safe_history(session, conversation.id, user_msg.id, route, options)
            available_refs = {c["ref"] for c in package.payload.get("data", {}).get("search_documents", {}).get("citations", [])}
            # Replay only turns whose entire document evidence fits this request's budget.
            # Otherwise old source refs could be repeated without a resolvable citation.
            history = [m for m in history if all(c["ref"] in available_refs for c in
                       context_snapshot_handler.get(session, m.context_snapshot_id).payload.get("data", {})
                       .get("search_documents", {}).get("citations", []))]
            request = LLMRequest(
                model=model,
                instructions=SYSTEM_PROMPT,
                input=[
                    *({"role": m.role, "content": m.content} for m in history),
                    {"role": "developer",
                     "content": "Context Package (JSON, 사용자 데이터의 유일한 출처):\n" + package.text},
                    {"role": "user", "content": query},
                ],
            )
            async for event in self.gateway.stream(session, request, conversation_id=conversation.id):
                if event.type == "delta" and event.text:
                    parts.append(event.text)
                    yield {"type": "delta", "text": event.text}
            settled = True
        except AdvisorError as exc:
            self._settle_unanswered(session, conversation.id, user_msg, parts, package.snapshot_id, model)
            settled = True
            yield {"type": "error", **exc.as_dict()}
            return
        finally:
            if not settled:  # client went away mid-stream (generator closed)
                self._settle_unanswered(session, conversation.id, user_msg, parts, package.snapshot_id, model)

        display, proposals, memories = proposal_manager.extract_blocks("".join(parts))
        reply = message_handler.create(session, {
            "conversation_id": conversation.id, "role": "assistant", "content": display,
            "context_snapshot_id": package.snapshot_id, "model": model,
        })
        actions, mems = proposal_manager.record(session, conversation.id, reply.id, proposals, memories)
        session.commit()
        yield {
            "type": "done",
            "message_id": reply.id,
            "context_snapshot_id": package.snapshot_id,
            "proposals": [{"id": a.id, "action": a.action, "payload": a.payload, "rationale": a.rationale}
                          for a in actions],
            "memory_proposals": [{"id": m.id, "kind": m.kind, "content": m.content} for m in mems],
        }


    @staticmethod
    def _settle_unanswered(session: Session, conversation_id: int, user_msg, parts: list[str],
                           snapshot_id: str, model: str | None) -> None:
        """Keep partial output as `incomplete`; unanswered turns stay visible but are not replayed."""
        if parts:
            message_handler.create(session, {
                "conversation_id": conversation_id, "role": "assistant", "content": "".join(parts),
                "status": "incomplete", "context_snapshot_id": snapshot_id, "model": model,
            })
        message_handler.update(session, user_msg, {"status": "failed"})
        session.commit()


advisor_manager = AdvisorManager(
    gateway=llm_gateway_manager,
    router=context_routing_manager,
    builder=context_builder_manager,
    history_limit=settings.history_message_limit,
)
