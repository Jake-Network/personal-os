"""LangChain retrieval interfaces retaining the app's source and sharing metadata."""
from typing import Any

from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from pydantic import ConfigDict

from app.enums.context_category import ALL_CATEGORIES
from app.modules.advisor.history_service import history_service
from app.modules.advisor.types import AskOptions
from app.modules.context.privacy_manager import privacy_manager
from app.modules.documents import retrieval
from app.modules.context.source_policy import source_allowed
from app.modules.llm.errors import AdvisorError


class HistoryRetriever(BaseRetriever):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    session: Any
    conversation_id: int
    excluded: frozenset = frozenset()
    options: AskOptions
    limit: int = 6
    prepared_documents: list[Document] | None = None

    def _prepared(self):
        excluded = self.excluded | privacy_manager.get_excluded(self.session)
        document_scope = {'enabled': self.options.document_search, 'document_ids': self.options.document_ids or []}
        memo = {}
        for document in self.prepared_documents or []:
            if not source_allowed(self.session, [document.metadata['source_reference']], excluded,
                    document_scope=document_scope, memo=memo):
                raise AdvisorError('과거 대화 근거의 공유 설정이 변경되었습니다.', provider_code='source_policy_changed')
        return self.prepared_documents

    def _get_relevant_documents(self, query, *, run_manager):
        if self.prepared_documents is not None:
            # The assembler just loaded this batch under the current policy and
            # retains its snapshots. Expiring each adapter discards that batch
            # and creates one lazy snapshot query per message. Transport still
            # independently expires and rechecks the complete outbound request.
            return self._prepared()
        self.session.expire_all()
        excluded = self.excluded | privacy_manager.get_excluded(self.session)
        rows, snapshots, flags = history_service.related(self.session, query,
            self.conversation_id, excluded, self.options, self.limit)
        return [Document(page_content=row.content, id=f"advisor_messages:{row.id}", metadata={
            "source_reference": {"table": "advisor_messages", "id": row.id},
            "conversation_id": row.conversation_id, "context_snapshot_id": row.context_snapshot_id,
            "historical": True, "created_at": row.created_at.isoformat(),
            "data_quality_flags": flags}) for row in rows]

    async def _aget_relevant_documents(self, query, *, run_manager):
        return self._get_relevant_documents(query, run_manager=run_manager)


class DocumentRetriever(BaseRetriever):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    session: Any
    categories: frozenset = frozenset(ALL_CATEGORIES)
    excluded: frozenset = frozenset()
    document_ids: tuple[int, ...] | None = None
    limit: int = 6
    prepared_documents: list[Document] | None = None

    def _get_relevant_documents(self, query, *, run_manager):
        excluded = self.excluded | privacy_manager.get_excluded(self.session)
        if self.prepared_documents is not None:
            scope = {'enabled': True, 'document_ids': self.document_ids or []}
            memo = {}
            for document in self.prepared_documents:
                if not source_allowed(self.session, [document.metadata['source_reference']], excluded,
                        document_scope=scope, memo=memo):
                    raise AdvisorError('문서 근거의 공유 설정이 변경되었습니다.', provider_code='source_policy_changed')
            return self.prepared_documents
        self.session.expire_all()
        result = retrieval.search(self.session, query, self.categories - excluded,
            document_ids=self.document_ids, limit=self.limit, excluded_categories=excluded)
        return [Document(page_content=citation["text"], id=citation["ref"], metadata={
            **{key: value for key, value in citation.items() if key != "text"},
            "source_reference": {"table": "document_versions", "id": citation["version_id"]},
            "data_quality_flags": result.flags}) for citation in result.data.get("citations", [])]

    async def _aget_relevant_documents(self, query, *, run_manager):
        return self._get_relevant_documents(query, run_manager=run_manager)
