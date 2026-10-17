"""PRD AdvisorService: query → route → context snapshot → LLM → persisted, grounded answer (§3.1)."""

from collections.abc import AsyncIterator
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

    def preview(self, session: Session, query: str, conversation: AdvisorConversation | None,
                options: AskOptions) -> dict:
        """What would be shared for this question — nothing is persisted or sent."""
        route = self.route(session, query, conversation, options)
        package = self.builder.build(session, route, conversation_id=None)
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
        route = self.route(session, query, conversation, options)
        package = self.builder.build(session, route, conversation_id=conversation.id)
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
            history = message_handler.get_history(session, conversation.id, user_msg.id, self.history_limit)
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
