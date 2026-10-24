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
from app.modules.agent.settings_manager import style_instruction


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
                 authorization=None, run_id=None, run_owner=None, run_generation=None):
        self.session, self.manager, self.conversation = session, manager, conversation
        self.options, self.model, self.guard = options, model, guard
        self.current_message_id = current_message_id
        self.authorization = authorization
        self.run_id, self.run_owner, self.run_generation = run_id, run_owner, run_generation
        self.lock = asyncio.Lock()
        self.last_context = {}
        self.last_history = []
        self.baseline_snapshot_id = None
        # Playbook catalog entries offered earlier in this run (persisted by the graph state).
        self.run_catalog_refs = []
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
                excluded_categories=tuple(str(c) for c in self.manager.sharing_exclusions(self.session, self.options))),
                outbound=False)

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

    async def search_sessions(self, query):
        """Filtered past-session excerpts and their refs; assemble() snapshots and budgets them."""
        from app.modules.advisor.memory_history_manager import search_sessions
        async with self.lock:
            await self.check()
            options = self.manager.document_options(self.session, self.conversation, self.options)
            return search_sessions(self.session, query, self.conversation.id,
                                   self.manager.sharing_exclusions(self.session, options), options)

    def saved_history_summary(self, overflow):
        options = self.manager.document_options(self.session, self.conversation, self.options)
        return history_service.saved_summary(self.session, self.conversation.id, overflow,
            self.manager.sharing_exclusions(self.session, options), options)

    def store_history_summary(self, content, overflow, *, generator='graph_summary_v1'):
        return history_service.record_summary(self.session, self.conversation.id, content, overflow, generator=generator)

    async def assemble(self, query, *, instruction='', derived=None, sources=(), history_source_ids=(),
                       structured_output=False, context_data=None, record_sources=(), context_flags=()):
        async with self.lock:
            await self.check()
            self.validate_sources(sources)
            from app.modules.context.source_policy import source_allowed
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
            if (sources or summary is not None or history_source_ids or context_data or record_sources or context_flags
                    or self.run_catalog_refs):
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
                payload['data'] = {**payload.get('data', {}), **(context_data or {})}
                payload['data_quality_flags'] = [*payload.get('data_quality_flags', []), *context_flags]
                # Discovery is optional. Drop whole catalog entries before failing a full context;
                # procedure steps and required reflection evidence are never silently truncated.
                catalog = payload['data'].get('playbook_catalog')
                if catalog:
                    catalog = {**catalog, 'items': dict(catalog.get('items', {}))}
                    payload['data']['playbook_catalog'] = catalog
                refs = list(package.record_references)
                from app.modules.context.record_privacy import stamp_references
                extra_refs = list(record_sources)
                if not source_allowed(self.session, extra_refs,
                        self.manager.sharing_exclusions(self.session, options),
                        document_scope={'enabled': options.document_search,
                                        'document_ids': list(options.document_ids or [])}):
                    raise AdvisorError('상담 절차나 회고 근거가 변경되었습니다.', provider_code='source_policy_changed')
                refs.extend(stamp_references(self.session, extra_refs))
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
                    # Mandatory history gets its room before optional procedure discovery.
                    # Counting the catalog here could fail before the later whole-entry cull.
                    empty_payload = {**payload, 'data': {name: value for name, value in payload['data'].items()
                                                        if name != 'playbook_catalog'}}
                    empty_package = replace(package, payload=empty_payload)
                    base_request = build_request(self.model, history.decision(), empty_package, query,
                        self.manager.sharing_exclusions(self.session, options), structured_output=structured_output,
                        style=style_instruction(self.session))
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
                if catalog:
                    def catalog_fits():
                        candidate = replace(package, payload=payload)
                        if len(candidate.text) > settings.context_char_limit:
                            return False
                        try:
                            preview = build_request(self.model, history.decision(), candidate, query,
                                self.manager.sharing_exclusions(self.session, options),
                                structured_output=structured_output, style=style_instruction(self.session))
                        except AdvisorError as exc:
                            if exc.provider_code == 'request_budget_exceeded':
                                return False
                            raise
                        preview.instructions += ('\n' + instruction) if instruction else ''
                        if derived:
                            preview.input.insert(-1, {'role': 'developer', 'content':
                                '이번 실행의 파생 분석(확정 사실이나 장기 기억이 아님):\n' + json.dumps(derived, ensure_ascii=False)})
                        return len(json.dumps({'instructions': preview.instructions, 'input': preview.input},
                                              ensure_ascii=False)) <= settings.request_char_limit

                    omission = None
                    while catalog['items'] and not catalog_fits():
                        catalog['items'].popitem()
                        if omission is None:
                            omission = {'code': 'playbook_catalog_omitted', 'category': 'system', 'count': 0}
                            payload['data_quality_flags'].append(omission)
                        omission['count'] += 1
                    catalog_refs = [{'table': 'playbook_revisions', 'id': int(ref.split(':')[1])}
                                    for ref in catalog['items']]
                else:
                    catalog_refs = []
                # Discovery metadata is checked at transport, but is never evidence of the answer:
                # revoking a listed procedure later must not withhold answers that never used it.
                # Every later call of this run carries the catalog it was planned from.
                catalog_refs = list({(ref['table'], ref['id']): ref for ref in
                                     [*self.run_catalog_refs, *catalog_refs]}.values())
                if catalog_refs:
                    from app.modules.context.source_policy import procedures_sendable
                    if not procedures_sendable(self.session, catalog_refs, self.manager.sharing_exclusions(self.session, options)):
                        raise AdvisorError('상담 절차의 공유 설정이 변경되었습니다.', provider_code='source_policy_changed')
                    # Kept beside the evidence (never in the sent payload), marked so history checks skip it.
                    refs.extend({**ref, 'role': 'catalog'} for ref in stamp_references(self.session, catalog_refs))
                row = ContextSnapshot(id=snapshot_id, conversation_id=self.conversation.id,
                    context_categories=package.categories, excluded_categories=package.excluded_categories,
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
                                    structured_output=structured_output, style=style_instruction(self.session))
            request.authorization = self.authorization
            request.run_id, request.run_owner, request.run_generation = self.run_id, self.run_owner, self.run_generation
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
