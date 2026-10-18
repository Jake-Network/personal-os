"""PRD AdvisorService: query → route → context snapshot → LLM → persisted, grounded answer (§3.1)."""

import asyncio
import logging
import re
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.enums.context_category import ALL_CATEGORIES, Category
from app.modules.advisor.prompts import SYSTEM_PROMPT
from app.modules.advisor.proposal_manager import proposal_manager
from app.modules.advisor.types import AskOptions, PreparedHistory
from app.modules.context.context_builder_manager import ContextBuilderManager, context_builder_manager
from app.modules.context.routing import ContextRouter, context_router
from app.modules.context.history_privacy_manager import history_privacy_manager
from app.modules.context.privacy_manager import privacy_manager
from app.modules.context.types import ContextPackage, HistoryDecision, RouteDecision, payload_citations, payload_evidence
from app.modules.context.entity_routing import matched_investment_terms
from app.modules.crud import audit_log_handler, context_snapshot_handler, conversation_handler, message_handler
from app.modules.database.model import AdvisorConversation, ContextSnapshot, DocumentVersion
from app.modules.documents.retrieval import visible_documents
from app.modules.llm.errors import AdvisorError
from app.modules.llm.llm_gateway_manager import LLMGatewayManager, llm_gateway_manager
from app.modules.llm.types import LLMRequest

logger = logging.getLogger(__name__)

DOCUMENT_REFERENCE_PATTERN = re.compile(r"\[(document_chunks:\d+)\]")
HISTORICAL_EVIDENCE_RULES = (
    "\n- historical=true 문서 발췌와 과거 대화는 당시 맥락입니다. 현재 사실이나 숫자로 재사용하지 말고, "
    "최신 구조화 데이터와 현재 검색 결과를 우선하며 과거 근거임을 밝히세요. 과거 대화의 [과거 문서 근거 생략]은 "
    "예산 때문에 원문 근거를 생략했다는 뜻입니다. 현재 제공된 ref만 인용하고 생략된 근거로 현재 사실을 단정하지 마세요."
)


class AdvisorManager:
    def __init__(self, gateway: LLMGatewayManager, router: ContextRouter, builder: ContextBuilderManager,
                 history_limit: int):
        self.gateway = gateway
        self.router = router
        self.builder = builder
        self.history_limit = history_limit

    # --- routing / context ---------------------------------------------------------------

    @staticmethod
    def excluded(session: Session, options: AskOptions) -> frozenset[Category]:
        """Saved privacy settings plus this request's exclusions."""
        return privacy_manager.get_excluded(session) | options.exclude

    def route(self, session: Session, query: str, conversation: AdvisorConversation | None,
              options: AskOptions) -> RouteDecision:
        previous = None
        if conversation is not None:
            last = context_snapshot_handler.get_latest_for_conversation(session, conversation.id)
            if last is not None:
                previous = frozenset(Category(c) for c in [*last.context_categories, *last.excluded_categories])
        excluded = self.excluded(session, options)
        route = self.router.route(
            query,
            excluded=excluded,
            override=options.categories,
            previous=previous,
            domain=conversation.domain if conversation else None,
        )
        # Generic investment questions already select the correct tools. Read only
        # names/tickers for otherwise unrecognized registered-position mentions.
        explicit_other_domains = route.requested & {Category.CAREER, Category.CALENDAR, Category.HEALTH}
        if options.categories is None and Category.INVESTMENT not in route.requested and not explicit_other_domains:
            terms = matched_investment_terms(session, query, excluded=excluded)
            if terms:
                route = self.router.route(query, excluded=excluded, previous=previous,
                                          domain=conversation.domain if conversation else None, entity_terms=terms)
        return route

    def document_options(self, session: Session, conversation: AdvisorConversation | None,
                         options: AskOptions) -> AskOptions:
        if options.document_ids is not None:
            return options
        last = context_snapshot_handler.get_latest_for_conversation(session, conversation.id) if conversation else None
        ids = last.payload.get("document_scope", {}).get("document_ids", []) if last else []
        return replace(options, document_ids=tuple(ids))

    def sharing_exclusions(self, session, options):
        """The policy for the whole outbound request: an explicit category override also restricts sharing."""
        excluded = self.excluded(session, options)
        if options.categories is not None:
            excluded |= frozenset(ALL_CATEGORIES) - (options.categories | {Category.PROFILE})
        return excluded

    def prepare_context(self, session, query, conversation, options, conversation_id=None):
        options = self.document_options(session, conversation, options)
        route = self.route(session, query, conversation, options)
        excluded = self.sharing_exclusions(session, options)
        if options.document_search and options.document_ids:
            docs = visible_documents(session, document_ids=options.document_ids, excluded_categories=excluded)
            topics = frozenset(Category(c) for d in docs for c in d.categories)
            route = replace(route, requested=route.requested | topics,
                            selected=(route.selected | topics) - excluded)
        prepared = self.prepare_history(session, conversation.id, None, options, excluded) if conversation else PreparedHistory([], {})
        inherited_citations, dependencies, history_categories = {}, {}, set()
        inherited_unknown = False
        for message in prepared.messages:
            snapshot = prepared.snapshots.get(message.context_snapshot_id)
            inherited_unknown |= snapshot is None or bool(snapshot.payload.get("history_provenance_unknown"))
            for citation in prepared.citations(message):
                # Old excerpts explain past turns; they never become freshly retrieved facts.
                inherited_citations[citation["ref"]] = {**citation, "historical": True}
            if snapshot:
                history_categories.update(snapshot.context_categories)
                history_categories.update(snapshot.payload.get("history_categories", []))
                for dependency in snapshot.payload.get("document_dependencies", []):
                    dependencies[(dependency["document_id"], dependency["version_id"])] = dependency
        package = self.builder.build(session, route, conversation_id=conversation_id, query=query,
                                     document_search=options.document_search,
                                     document_ids=options.document_ids or (), excluded=excluded,
                                     inherited_citations=list(inherited_citations.values()),
                                     inherited_dependencies=list(dependencies.values()),
                                     inherited_categories=sorted(history_categories),
                                     inherited_unknown=inherited_unknown,
                                     history_document_refs={ref for message in prepared.messages
                                                            for ref in DOCUMENT_REFERENCE_PATTERN.findall(message.content)})
        return route, package, options, prepared

    def prepare_history(self, session, conversation_id, before_id, options, excluded=None):
        """Replayable messages minus category-tainted turns (cumulative), then per-turn document checks."""
        excluded = self.sharing_exclusions(session, options) if excluded is None else excluded
        replayable = message_handler.get_replayable_before(session, conversation_id, before_id)
        decision = history_privacy_manager.filter(session, replayable, excluded)
        history = decision.kept[-self.history_limit:] if self.history_limit else []
        snapshot_ids = {m.context_snapshot_id for m in history if m.context_snapshot_id}
        snapshots = {s.id: s for s in session.scalars(select(ContextSnapshot).where(
            ContextSnapshot.id.in_(snapshot_ids)))} if snapshot_ids else {}
        evidence_rows = [c for snapshot in snapshots.values() for c in payload_evidence(snapshot.payload)]
        document_ids = {c["document_id"] for c in evidence_rows}
        visible = {d.id: d for d in visible_documents(session, document_ids=document_ids,
                   excluded_categories=excluded)} if document_ids else {}
        version_ids = {c["version_id"] for c in evidence_rows}
        versions = set(session.scalars(select(DocumentVersion.id).where(DocumentVersion.id.in_(version_ids)))) if version_ids else set()
        safe = []
        for message in history:
            if getattr(message, "context_purged", False):
                continue
            snapshot = snapshots.get(message.context_snapshot_id)
            if snapshot is None:
                # Legacy user conversations have no captured provenance. Preserve normal
                # continuity, but cannot prove them safe under a new sharing restriction.
                if not message.context_snapshot_id and not excluded and options.document_search and not options.document_ids:
                    safe.append(message)
                continue
            if snapshot.payload.get("history_provenance_unknown") and (excluded or not options.document_search or options.document_ids):
                continue
            if (set(snapshot.context_categories) | set(snapshot.payload.get("history_categories", []))
                    | set(snapshot.payload.get("document_categories", []))).intersection(str(c) for c in excluded):
                continue
            evidence = payload_evidence(snapshot.payload)
            if evidence and not options.document_search:
                continue
            if any(c["document_id"] not in visible or c["version_id"] not in versions or
                   (options.document_ids and c["document_id"] not in options.document_ids)
                   for c in evidence):
                continue
            safe.append(message)
        return PreparedHistory(safe, snapshots, decision.withheld_ids, decision.withheld_categories)

    def preview(self, session: Session, query: str, conversation: AdvisorConversation | None,
                options: AskOptions) -> dict:
        """What would be shared for this question — nothing is persisted or sent."""
        route, package, _, prepared = self.prepare_context(session, query, conversation, options)
        session.rollback()
        inspector = package.inspector()
        inspector["context_snapshot_id"] = None
        return {"route": route.as_dict(), **inspector, **prepared.decision().as_dict()}

    @staticmethod
    def build_request(model: str, history: HistoryDecision, package: ContextPackage, query: str,
                      excluded: frozenset[Category]) -> LLMRequest:
        """The only place an outbound request is assembled; it re-checks the privacy policy on every part."""
        leaked = excluded & {Category(c) for c in [*package.categories,
                                                   *package.payload.get("document_categories", [])]}
        if leaked:  # a builder bug must fail closed, never send
            raise AdvisorError("context package contains an excluded category", provider_code="privacy_violation")
        notes = []
        if history.withheld_ids:
            notes.append({"role": "developer", "content": (
                f"이전 대화 메시지 {len(history.withheld_ids)}개는 사용자가 현재 공유를 막은 범주"
                f"({', '.join(history.withheld_categories)})의 정보를 포함할 수 있어 전달하지 않았습니다. "
                "그 내용을 기억하거나 추측하지 말고, 필요하면 사용자에게 다시 물어보세요.")})
        available_refs = {c["ref"] for c in payload_citations(package.payload)}
        # Keep dialogue continuity while omitting citations outside the excerpt budget.
        replayed = ({"role": m.role, "content": DOCUMENT_REFERENCE_PATTERN.sub(
            lambda match: match.group(0) if match.group(1) in available_refs else "[과거 문서 근거 생략]",
            m.content)} for m in history.kept)
        return LLMRequest(
            model=model,
            instructions=SYSTEM_PROMPT + HISTORICAL_EVIDENCE_RULES,
            input=[
                *notes,
                *replayed,
                {"role": "developer",
                 "content": "Context Package (JSON, 사용자 데이터의 유일한 출처):\n" + package.text},
                {"role": "user", "content": query},
            ],
        )

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
        try:
            route, package, options, prepared = await asyncio.to_thread(
                self.prepare_context, session, query, conversation, options, conversation.id)
        except AdvisorError as exc:  # e.g. over the context budget: nothing is sent or stored
            session.rollback()
            yield {"type": "error", **exc.as_dict()}
            return
        excluded = self.sharing_exclusions(session, options)
        user_msg = message_handler.create(session, {
            "conversation_id": conversation.id, "role": "user", "content": query,
            "context_snapshot_id": package.snapshot_id,
        })
        conversation_handler.update(session, conversation, {"updated_at": datetime.now(UTC)})
        session.commit()
        yield {"type": "context", "route": route.as_dict(), **package.inspector(), **prepared.decision().as_dict()}

        model = None
        parts: list[str] = []
        settled = False
        try:
            model = await self.gateway.resolve_model(session)
            request = self.build_request(model, prepared.decision(), package, query, excluded)
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
        except Exception:  # transport errors, malformed provider payloads: fail the turn, not the stream
            logger.exception("advisor turn failed for conversation %s", conversation.id)
            session.rollback()
            self._settle_unanswered(session, conversation.id, user_msg, parts, package.snapshot_id, model)
            settled = True
            yield {"type": "error", **AdvisorError().as_dict()}
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
    router=context_router,
    builder=context_builder_manager,
    history_limit=settings.history_message_limit,
)
