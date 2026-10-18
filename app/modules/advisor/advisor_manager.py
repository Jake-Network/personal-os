"""PRD AdvisorService: query → route → context snapshot → LLM → persisted, grounded answer (§3.1)."""

from collections.abc import AsyncIterator
from dataclasses import replace

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.config import settings
from app.enums.context_category import ALL_CATEGORIES, Category
from app.modules.advisor.history import inherited_evidence
from app.modules.advisor.history_service import history_service
from app.modules.advisor.requests import build_request
from app.modules.advisor.types import AskOptions, PreparedHistory
from app.modules.context.context_builder_manager import ContextBuilderManager, context_builder_manager
from app.modules.context.routing import ContextRouter, context_router
from app.modules.context.privacy_manager import privacy_manager
from app.modules.context.types import RouteDecision
from app.modules.context.entity_routing import matched_investment_terms
from app.modules.crud import audit_log_handler, context_snapshot_handler, conversation_handler
from app.modules.database.model import AdvisorConversation
from app.modules.documents.retrieval import visible_documents
from app.modules.llm.llm_gateway_manager import LLMGatewayManager, llm_gateway_manager

_UNLOADED = object()


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
              options: AskOptions, last_snapshot=_UNLOADED) -> RouteDecision:
        previous = None
        if conversation is not None:
            last = context_snapshot_handler.get_latest_for_conversation(session, conversation.id) if last_snapshot is _UNLOADED else last_snapshot
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
                         options: AskOptions, last_snapshot=_UNLOADED) -> AskOptions:
        if options.document_ids is not None:
            return options
        last = (context_snapshot_handler.get_latest_for_conversation(session, conversation.id) if conversation else None) if last_snapshot is _UNLOADED else last_snapshot
        ids = last.payload.get("document_scope", {}).get("document_ids", []) if last else []
        return replace(options, document_ids=tuple(ids))

    def sharing_exclusions(self, session, options):
        """The policy for the whole outbound request: an explicit category override also restricts sharing."""
        excluded = self.excluded(session, options)
        if options.categories is not None:
            excluded |= frozenset(ALL_CATEGORIES) - (options.categories | {Category.PROFILE})
        return excluded

    def prepare_context(self, session, query, conversation, options, conversation_id=None):
        last_snapshot = context_snapshot_handler.get_latest_for_conversation(session, conversation.id) if conversation else None
        options = self.document_options(session, conversation, options, last_snapshot)
        route = self.route(session, query, conversation, options, last_snapshot)
        excluded = self.sharing_exclusions(session, options)
        if options.document_search and options.document_ids:
            docs = visible_documents(session, document_ids=options.document_ids, excluded_categories=excluded)
            topics = frozenset(Category(c) for d in docs for c in d.categories)
            route = replace(route, requested=route.requested | topics,
                            selected=(route.selected | topics) - excluded)
        prepared = self.prepare_history(session, conversation.id, None, options, excluded) if conversation else PreparedHistory([], {})
        related, related_snapshots, retrieval_flags = history_service.related(session, query, conversation.id if conversation else -1, excluded, options)
        prepared.messages = related + prepared.messages
        prepared.snapshots.update(related_snapshots)
        inherited = inherited_evidence(prepared)
        experiences = history_service.experiences(session, query, excluded, options)
        package = self.builder.build(session, route, conversation_id=conversation_id, query=query,
                                     document_search=options.document_search,
                                     document_ids=options.document_ids or (), excluded=excluded,
                                     inherited_citations=inherited.citations,
                                     inherited_dependencies=inherited.dependencies,
                                     inherited_categories=inherited.categories,
                                     inherited_unknown=inherited.unknown,
                                     history_document_refs=inherited.document_refs,
                                     history_message_refs=[m.id for m in prepared.messages],
                                     history_search_flags=retrieval_flags, historical_experiences=experiences)
        return route, package, options, prepared

    def prepare_history(self, session, conversation_id, before_id, options, excluded=None):
        """Replayable messages minus category-tainted turns (cumulative), then per-turn document checks."""
        excluded = self.sharing_exclusions(session, options) if excluded is None else excluded
        return history_service.prepare(session, conversation_id, before_id, options, excluded, self.history_limit)

    def preview(self, session: Session, query: str, conversation: AdvisorConversation | None,
                options: AskOptions) -> dict:
        """What would be shared for this question — nothing is persisted or sent."""
        route, package, _, prepared = self.prepare_context(session, query, conversation, options)
        # The same total request budget applies to previews, without resolving a provider.
        build_request("preview", prepared.decision(), package, query, self.sharing_exclusions(session, options))
        session.rollback()
        inspector = package.inspector()
        inspector["context_snapshot_id"] = None
        return {"route": route.as_dict(), **inspector, **prepared.decision().as_dict(),
                'web_search': {'enabled': options.web_search,
                    'query': options.web_query.strip() if options.web_search and options.web_query else None,
                    'collection_pending': options.web_search}}

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
        from app.modules.database.model.advisor_runtime import AdvisorRun
        from app.modules.advisor.runtime.checkpoints import delete_run_checkpoints
        run_ids = list(session.scalars(update(AdvisorRun).where(AdvisorRun.conversation_id == conversation_id)
            .values(lease_generation=AdvisorRun.lease_generation + 1, lease_owner=None,
                    lease_until=None, status='cancelled').returning(AdvisorRun.id)))
        delete_run_checkpoints(session, run_ids)
        context_snapshot_handler.delete_for_conversation(session, conversation_id)
        conversation_handler.delete(session, conv)
        audit_log_handler.record(session, "user", "conversation.delete", f"advisor_conversations:{conversation_id}")
        session.commit()

    # --- ask -----------------------------------------------------------------------------

    async def ask(self, session: Session, conversation: AdvisorConversation, query: str,
                  options: AskOptions | None = None) -> AsyncIterator[dict]:
        from app.modules.advisor.runtime.service import ConversationRuntime
        async for event in ConversationRuntime(self).single_response(session, conversation, query, options):
            yield event


advisor_manager = AdvisorManager(
    gateway=llm_gateway_manager,
    router=context_router,
    builder=context_builder_manager,
    history_limit=settings.history_message_limit,
)
