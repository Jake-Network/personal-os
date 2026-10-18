"""App-owned history selection; checkpoints never become a second message store."""
from sqlalchemy import select, func

from app.modules.advisor.history import replay_safe_messages
from app.modules.advisor.memory_history_manager import (
    index_history, memory_history_manager, relevant_experiences, relevant_history,
)
from app.modules.advisor.types import PreparedHistory
from app.modules.context.history_privacy_manager import history_privacy_manager
from app.modules.context.source_policy import source_allowed
from app.modules.context.types import payload_evidence
from app.modules.crud import message_handler
from app.modules.database.model import AdvisorMessage, ContextSnapshot, ConversationSummary, DocumentVersion
from app.modules.documents.retrieval import visible_documents


class HistoryService:
    def prepare(self, session, conversation_id, before_id, options, excluded, history_limit=20):
        replayable = message_handler.get_replayable_before(session, conversation_id, before_id)
        decision = history_privacy_manager.filter(session, replayable, excluded)
        history = decision.kept if history_limit is None else (decision.kept[-history_limit:] if history_limit else [])
        snapshot_ids = {m.context_snapshot_id for m in history if m.context_snapshot_id}
        snapshots = {s.id: s for s in session.scalars(select(ContextSnapshot).where(
            ContextSnapshot.id.in_(snapshot_ids)))} if snapshot_ids else {}
        evidence = [c for snapshot in snapshots.values() for c in payload_evidence(snapshot.payload)]
        document_ids = {c["document_id"] for c in evidence}
        visible = {d.id for d in visible_documents(session, document_ids=document_ids,
            excluded_categories=excluded)} if document_ids else set()
        version_ids = {c["version_id"] for c in evidence}
        versions = set(session.scalars(select(DocumentVersion.id).where(
            DocumentVersion.id.in_(version_ids)))) if version_ids else set()
        safe = replay_safe_messages(history, snapshots, excluded, options, visible, versions)
        eligible = [m for m in safe if source_allowed(session,
            [{"table": "advisor_messages", "id": m.id}], excluded)]
        withheld = list(dict.fromkeys([*decision.withheld_ids,
            *(m.id for m in history if m not in eligible)]))
        return PreparedHistory(eligible, snapshots, withheld, decision.withheld_categories)

    related = staticmethod(relevant_history)
    experiences = staticmethod(relevant_experiences)
    index = staticmethod(index_history)

    def summaries(self, session, conversation_id):
        return memory_history_manager.summaries(session, conversation_id)

    def summarize(self, session, conversation_id, body):
        return memory_history_manager.summarize(session, conversation_id, body)

    def overflow(self, session, conversation_id, options, excluded, history_limit, current_message_id=None):
        if not history_limit:
            return None
        count = session.scalar(select(func.count()).select_from(AdvisorMessage).where(
            AdvisorMessage.conversation_id == conversation_id, AdvisorMessage.status == 'complete'))
        if count <= history_limit:
            return None
        prepared = self.prepare(session, conversation_id, None, options, excluded, history_limit=None)
        rows = [message for message in prepared.messages if message.id != current_message_id]
        overflow = rows[:-history_limit]
        if not overflow:
            return None
        return {'messages': [{'id': m.id, 'role': m.role, 'content': m.content} for m in overflow],
            'source_message_ids': [m.id for m in overflow],
            'source_snapshot_ids': list(dict.fromkeys(m.context_snapshot_id for m in overflow if m.context_snapshot_id)),
            'first_message_id': overflow[0].id, 'last_message_id': overflow[-1].id}

    def saved_summary(self, session, conversation_id, overflow, excluded, options):
        if not overflow:
            return None
        expected = set(overflow['source_message_ids'])
        summaries = session.scalars(select(ConversationSummary).where(
            ConversationSummary.conversation_id == conversation_id,
            ConversationSummary.first_message_id == overflow['first_message_id'],
            ConversationSummary.last_message_id == overflow['last_message_id'],
            ConversationSummary.generator.in_(['graph_summary_v1', 'runtime_extract_v1']))
            .order_by(ConversationSummary.id.desc()))
        scope = {'enabled': options.document_search, 'document_ids': options.document_ids or []}
        for summary in summaries:
            ids = {ref['id'] for ref in summary.source_references if ref.get('table') == 'advisor_messages'}
            if ids == expected and source_allowed(session,
                    [{'table': 'conversation_summaries', 'id': summary.id}], excluded, document_scope=scope):
                return summary
        return None

    def record_summary(self, session, conversation_id, content, overflow, *, generator='graph_summary_v1'):
        from app.modules.context.record_privacy import stamp_references
        summary = ConversationSummary(conversation_id=conversation_id,
            first_message_id=overflow['first_message_id'], last_message_id=overflow['last_message_id'],
            content=content, generator=generator,
            source_references=stamp_references(session,
                [{'table': 'advisor_messages', 'id': key} for key in overflow['source_message_ids']]))
        session.add(summary)
        session.flush()
        return summary


history_service = HistoryService()
