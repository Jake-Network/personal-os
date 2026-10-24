"""Fresh context assembly shared by every graph model boundary."""
import asyncio
import json
import uuid
import re
from datetime import UTC, datetime
from dataclasses import replace
from zoneinfo import ZoneInfo

from langchain_core.documents import Document
from langsmith import tracing_context

from app.modules.advisor.requests import build_request
from app.modules.llm.types import LLMRequest
from app.modules.llm.errors import AdvisorError
from app.modules.advisor.memory_store import ConfirmedMemoryStore
from app.modules.advisor.retrievers import HistoryRetriever, DocumentRetriever
from app.enums.context_category import ALL_CATEGORIES
from app.modules.advisor.history_service import history_service


def bounded_history_excerpt(messages, budget=4000):
    """Keep early constraints and recent overflow within a total serialized budget."""
    budget = max(0, budget)
    selected = {}
    # Reserve room for an explicit omission notice, including large message IDs.
    reserve = min(budget, 200)
    used = 0
    order = [0, *range(len(messages) - 1, 0, -1)] if messages else []
    for index in order:
        message = messages[index]
        excerpt = f"[{message['role']} message:{message['id']}] {message['content'][:500]}"
        cost = len(json.dumps(excerpt, ensure_ascii=False)) + 1
        if used + cost <= budget - reserve:
            selected[index] = excerpt
            used += cost
    omitted = [message['id'] for index, message in enumerate(messages) if index not in selected]
    pieces = [selected[index] for index in sorted(selected)]
    if omitted:
        pieces.append(f'[이전 대화 {len(omitted)}개 메시지 생략: ID 범위 {omitted[0]}~{omitted[-1]}. '
                      '생략된 조건이 있을 수 있으므로 필요한 경우 다시 확인하세요.]')
    content = '\n'.join(pieces)
    # Very small budgets may not even accommodate the omission notice. The
    # package quality flag still discloses omission, without sending raw text.
    return content if len(json.dumps(content, ensure_ascii=False)) - 2 <= budget else ''


class ContextAssembler:
    def __init__(self, session, manager, conversation, options, model, *, guard=None, current_message_id=None,
                 authorization=None):
        self.session, self.manager, self.conversation = session, manager, conversation
        self.options, self.model, self.guard = options, model, guard
        self.current_message_id = current_message_id
        self.authorization = authorization
        self.lock = asyncio.Lock()
        self.last_context = {}
        self.last_history = []
        self.baseline_snapshot_id = None
        self.data_operations = []
        self.memory_store = ConfirmedMemoryStore(session,
            allowed=frozenset(ALL_CATEGORIES) - manager.sharing_exclusions(session, options),
            document_scope={'enabled': options.document_search, 'document_ids': options.document_ids or []})

    async def validate_interfaces(self, query, package, options, history):
        """Consume common retrieval interfaces without repeating searches or model payloads.

        The domain builder owns selection and budgets. Retrievers adapt those exact
        selected results and revalidate provenance; the store owns confirmed-memory
        reads. No extra retrieval result is appended to the request.
        """
        excluded = self.manager.sharing_exclusions(self.session, options)
        history_retriever = HistoryRetriever(session=self.session, conversation_id=self.conversation.id,
            excluded=excluded, options=options, prepared_documents=[Document(page_content=m.content,
                id=f'advisor_messages:{m.id}', metadata={'source_reference': {'table': 'advisor_messages', 'id': m.id}})
                for m in history.messages])
        from app.modules.context.types import payload_citations
        document_retriever = DocumentRetriever(session=self.session, excluded=excluded,
            document_ids=options.document_ids, prepared_documents=[Document(page_content=c['text'], id=c['ref'],
                metadata={'source_reference': {'table': 'document_versions', 'id': c['version_id']}})
                for c in payload_citations(package.payload)])
        with tracing_context(enabled=False):
            historical = await history_retriever.ainvoke(query, config={'callbacks': []})
            documents = await document_retriever.ainvoke(query, config={'callbacks': []})
        safe_ids = {document.id for document in historical}
        history.messages = [m for m in history.messages if f'advisor_messages:{m.id}' in safe_ids]
        if len(documents) != len(payload_citations(package.payload)):
            raise AdvisorError('문서 근거 선택이 변경되었습니다.', provider_code='source_policy_changed')
        self.memory_store.allowed = frozenset(ALL_CATEGORIES) - excluded
        self.memory_store.request_query = query
        self.memory_store.document_scope = {'enabled': options.document_search, 'document_ids': options.document_ids or []}
        from app.config import settings
        historical_date = re.search(r'(?<!\d)(\d{4}-\d{2}-\d{2})(?!\d)', query)
        self.memory_store.at = None
        if historical_date:
            try:
                self.memory_store.at = datetime.fromisoformat(historical_date.group(1)).replace(tzinfo=ZoneInfo(settings.timezone))
            except ValueError:
                pass
        for memory in package.payload.get('data', {}).get('get_profile', {}).get('confirmed_memories', []):
            memory_id = memory.get('ref', '').removeprefix('personal_memories:')
            if not memory_id.isdecimal() or await self.memory_store.aget(self.memory_store.namespace, memory_id) is None:
                raise AdvisorError('확정 기억의 유효 기간이나 공유 범위가 변경되었습니다.', provider_code='source_policy_changed')

    async def check(self):
        if self.guard:
            await self.guard()
        self.session.expire_all()

    def validate_sources(self, snapshots):
        from app.modules.context.source_policy import require_live_request_sources
        for snapshot_id in snapshots:
            require_live_request_sources(self.session, LLMRequest(
                model=self.model, instructions='', input=[], source_snapshot_id=snapshot_id,
                excluded_categories=tuple(str(c) for c in self.manager.sharing_exclusions(self.session, self.options))))

    async def history_overflow(self, query):
        await self.check()
        options = self.manager.document_options(self.session, self.conversation, self.options)
        return history_service.overflow(self.session, self.conversation.id, options,
            self.manager.sharing_exclusions(self.session, options), self.manager.history_limit,
            self.current_message_id)

    async def search_web(self):
        """Only the explicitly approved public query can cross the search boundary."""
        from app.config import settings
        from app.modules.web_search import WebSearchService, WebSearchError
        from app.modules.advisor.runtime.web import save_web_snapshot, WebResearchError
        async with self.lock:
            await self.check()
            from app.modules.llm.run_policy import require
            require(self.session, self.authorization)
            if not self.options.web_search or not self.options.web_query or not self.options.web_query.strip():
                raise WebResearchError('웹 검색 허용과 공개 검색어를 확인하세요.', 'web_search_not_allowed')
            query = self.options.web_query.strip()
            self.session.commit()
        try:
            result = await WebSearchService(api_key=settings.web_search_api_key).search(query)
        except WebSearchError as exc:
            raise WebResearchError(str(exc), exc.code) from exc
        async with self.lock:
            await self.check()
            require(self.session, self.authorization)
            snapshot_id = save_web_snapshot(self.session, self.conversation.id, result)
            self.session.commit()
            return snapshot_id

    def saved_history_summary(self, overflow):
        options = self.manager.document_options(self.session, self.conversation, self.options)
        return history_service.saved_summary(self.session, self.conversation.id, overflow,
            self.manager.sharing_exclusions(self.session, options), options)

    def store_history_summary(self, content, overflow, *, generator='graph_summary_v1'):
        return history_service.record_summary(self.session, self.conversation.id, content, overflow, generator=generator)

    async def assemble(self, query, *, instruction='', derived=None, sources=(), history_source_ids=(),
                       structured_output=False):
        async with self.lock:
            await self.check()
            self.validate_sources(sources)
            route, package, options, history = self.manager.prepare_context(
                self.session, query, self.conversation, self.options, self.conversation.id)
            summary = None
            if not history_source_ids:
                overflow = history_service.overflow(self.session, self.conversation.id, options,
                    self.manager.sharing_exclusions(self.session, options), self.manager.history_limit,
                    self.current_message_id)
                summary = history_service.saved_summary(self.session, self.conversation.id, overflow,
                    self.manager.sharing_exclusions(self.session, options), options)
                if overflow and summary is None:
                    # Deterministic compatibility/budget fallback. It preserves
                    # source identity and explicitly marks excerpt truncation.
                    content = bounded_history_excerpt(overflow['messages'])
                    summary = self.store_history_summary(content, overflow, generator='runtime_extract_v1')
            if self.baseline_snapshot_id:
                from app.modules.context.snapshots import to_package
                from app.modules.database.model import ContextSnapshot
                self.validate_sources([self.baseline_snapshot_id])
                row = self.session.get(ContextSnapshot, self.baseline_snapshot_id)
                if row is None:
                    raise AdvisorError('비교 기준 근거가 삭제되었습니다.', provider_code='source_policy_changed')
                package = to_package(row, True)
            if sources or summary is not None or history_source_ids or self.data_operations:
                from app.modules.context.snapshots import content_hash, to_package
                from app.modules.database.model import ContextSnapshot
                snapshot_id = str(uuid.uuid4())
                payload = {**package.payload, 'context_snapshot_id': snapshot_id,
                    'generated_at': datetime.now(UTC).isoformat(),
                    'derived_snapshot_ids': list(dict.fromkeys([*sources,
                        *(overflow['source_snapshot_ids'] if summary is not None else []),
                        *([self.baseline_snapshot_id] if self.baseline_snapshot_id else [])]))}
                from app.modules.advisor.runtime.web import merge_web_sources
                from app.config import settings
                payload = merge_web_sources(payload,
                    [self.session.get(ContextSnapshot, key) for key in sources], settings.context_char_limit)
                refs = list(package.record_references)
                categories = list(package.categories)
                from app.modules.context.record_privacy import stamp_references
                if self.data_operations:
                    from app.modules.personal_data.personal_data_manager import RESOURCES
                    from app.modules.context.record_privacy import RECORD_CATEGORY
                    from app.modules.context.source_policy import source_allowed
                    excluded = self.manager.sharing_exclusions(self.session, options)
                    safe_operations = []
                    for operation in self.data_operations:
                        resource = RESOURCES.get(operation.get('resource'))
                        table = resource.handler.model.__tablename__ if resource else None
                        category = RECORD_CATEGORY.get(table)
                        evidence = list(operation.get('record_refs', []))
                        if operation.get('record_ref') and operation.get('operation') != 'delete':
                            evidence.append(operation['record_ref'])
                        evidence.extend({'table': table, 'id': item['id']} for item in operation.get('candidates', []) if table)
                        has_data = bool(operation.get('record') or operation.get('records') or operation.get('candidates'))
                        if has_data and (category in excluded or not source_allowed(self.session, evidence, excluded)):
                            safe_operations.append({key: operation[key] for key in ('operation', 'resource', 'status') if key in operation} |
                                {'message': '이 작업 결과의 상세 기록은 삭제되었거나 상담 공유에서 제외되었습니다.'})
                            continue
                        safe_operations.append(operation)
                        refs.extend(stamp_references(self.session, evidence))
                        # A pending command/clarifying answer can contain private input
                        # even before a row exists. Preserve its category for later sharing checks.
                        if category and category not in excluded and category not in categories:
                            categories.append(category)
                        if category and category not in excluded:
                            payload['history_categories'] = list(dict.fromkeys([
                                *payload.get('history_categories', []), category]))
                    payload['data'] = {**payload.get('data', {}), 'advisor_data_operations': safe_operations}
                refs.extend(stamp_references(self.session,
                    [{'table': 'advisor_messages', 'id': key} for key in history_source_ids]))
                if summary is not None:
                    data = {**payload.get('data', {})}
                    experiences = data.get('search_past_experiences')
                    if experiences:
                        data['search_past_experiences'] = {**experiences, 'summaries': [item for item in
                            experiences.get('summaries', []) if item.get('conversation_id') != self.conversation.id]}
                    data['conversation_summary'] = {'historical': True, 'derived_not_confirmed_facts': True,
                        'ref': f'conversation_summaries:{summary.id}', 'content': summary.content,
                        'first_message_id': summary.first_message_id, 'last_message_id': summary.last_message_id,
                        'generator': summary.generator}
                    payload['data'] = data
                    refs.extend(stamp_references(self.session,
                        [{'table': 'conversation_summaries', 'id': summary.id}]))
                    if summary.generator == 'runtime_extract_v1':
                        flags = [*payload.get('data_quality_flags', []), {'code': 'history_summary_extractive_fallback',
                            'category': 'system', 'detail': '이전 대화의 메시지별 최대 500자, 전체 최대 4000자 발췌입니다. '
                                f"원본 범위는 메시지 ID {summary.first_message_id}~{summary.last_message_id}입니다. "
                                '예산에 따라 메시지와 내용이 생략됩니다. 발췌가 비어 있으면 이 범위 전체가 생략되었습니다.'}]
                        payload['data_quality_flags'] = flags
                if self.baseline_snapshot_id:
                    payload['comparison_baseline'] = {'snapshot_id': self.baseline_snapshot_id,
                        'generated_at': package.payload.get('generated_at')}
                if summary is not None and summary.generator == 'runtime_extract_v1':
                    from app.config import settings
                    # Re-budget cached legacy extracts too. Provenance continues
                    # to cover the complete original range, including omissions.
                    payload['data']['conversation_summary']['content'] = ''
                    empty_package = replace(package, payload=payload)
                    base_request = build_request(self.model, history.decision(), empty_package, query,
                        self.manager.sharing_exclusions(self.session, options), structured_output=structured_output)
                    base_request.instructions += '\n' + instruction
                    if derived:
                        base_request.input.insert(-1, {'role': 'developer', 'content':
                            '이번 실행의 파생 분석(확정 사실이나 장기 기억이 아님):\n' + json.dumps(derived, ensure_ascii=False)})
                    size = len(json.dumps({'instructions': base_request.instructions,
                                          'input': base_request.input}, ensure_ascii=False))
                    room = min(4000, settings.context_char_limit - len(empty_package.text),
                               (settings.request_char_limit - size) // 2)
                    payload['data']['conversation_summary']['content'] = bounded_history_excerpt(
                        overflow['messages'], room)
                row = ContextSnapshot(id=snapshot_id, conversation_id=self.conversation.id,
                    context_categories=categories, excluded_categories=package.excluded_categories,
                    record_references=refs, source_updated_at=package.source_updated_at,
                    data_quality_flags=payload.get('data_quality_flags', package.data_quality_flags), payload=payload, content_hash=content_hash(payload))
                self.session.add(row)
                self.session.flush()
                from app.modules.documents.evidence import record_references
                record_references(self.session, row)
                package = to_package(row, False)
            if self.current_message_id is not None:
                history.messages = [m for m in history.messages if m.id != self.current_message_id]
            # Async LangChain callbacks may yield. Release SQLite's snapshot write
            # lock before them so the independent lease heartbeat can proceed.
            # Every source is revalidated again at the final gateway boundary.
            self.session.commit()
            await self.validate_interfaces(query, package, options, history)
            self.last_history = [{'ref': f'advisor_messages:{m.id}', 'role': m.role, 'content': m.content,
                'context_snapshot_id': m.context_snapshot_id, 'created_at': m.created_at.isoformat(),
                'historical': True} for m in history.messages]
            request = build_request(self.model, history.decision(), package, query,
                                    self.manager.sharing_exclusions(self.session, options),
                                    structured_output=structured_output)
            request.authorization = self.authorization
            if instruction:
                request.instructions += '\n' + instruction
            if derived:
                request.input.insert(-1, {'role': 'developer', 'content':
                    '이번 실행의 파생 분석(확정 사실이나 장기 기억이 아님):\n' + json.dumps(derived, ensure_ascii=False)})
            from app.config import settings
            if len(package.text) > settings.context_char_limit:
                raise AdvisorError('이전 대화 요약과 필수 근거가 컨텍스트 예산을 초과했습니다. '
                    '새 상담을 시작하거나 공유 범위를 줄여 주세요.', provider_code='context_budget_exceeded')
            if len(json.dumps({'instructions': request.instructions, 'input': request.input}, ensure_ascii=False)) > settings.request_char_limit:
                raise AdvisorError('분석 요청의 전체 전송 예산을 초과했습니다.', provider_code='request_budget_exceeded')
            self.session.commit()
            self.last_context = {'type': 'context', 'route': route.as_dict(), **package.inspector(), **history.decision().as_dict()}
            return request, package
