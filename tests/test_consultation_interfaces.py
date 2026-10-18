"""The real graph consumes Store/Retriever interfaces without duplicate context."""
import asyncio
import json
from collections import deque

from langgraph.checkpoint.memory import InMemorySaver

from app.modules.advisor.advisor_manager import AdvisorManager
from app.modules.advisor.memory_store import ConfirmedMemoryStore
from app.modules.advisor.retrievers import HistoryRetriever, DocumentRetriever
from app.modules.advisor.runtime.graph import build_conversation_graph, initial_state
from app.modules.advisor.types import AskOptions
from app.modules.context.context_builder_manager import context_builder_manager
from app.modules.context.routing import context_router
from app.modules.database.model import AdvisorConversation, PersonalMemory, MemoryRevision
from app.modules.llm.types import StreamEvent


def test_graph_uses_store_and_retrievers_once_per_selected_context(session, monkeypatch):
    conversation = AdvisorConversation(title='합성 상담')
    memory = PersonalMemory(kind='constraint', content='고유 합성 제약', status='confirmed', source='user')
    session.add_all([conversation, memory])
    session.flush()
    session.add(MemoryRevision(memory_id=memory.id, revision=1, kind='constraint',
                               content=memory.content, status='confirmed'))
    session.commit()
    observed = {'store': 0, 'history': 0, 'documents': 0}
    store_get = ConfirmedMemoryStore.aget
    history_get = HistoryRetriever._aget_relevant_documents
    documents_get = DocumentRetriever._aget_relevant_documents

    async def get_memory(self, *args, **kwargs):
        observed['store'] += 1
        return await store_get(self, *args, **kwargs)

    async def get_history(self, *args, **kwargs):
        observed['history'] += 1
        return await history_get(self, *args, **kwargs)

    async def get_documents(self, *args, **kwargs):
        observed['documents'] += 1
        return await documents_get(self, *args, **kwargs)

    monkeypatch.setattr(ConfirmedMemoryStore, 'aget', get_memory)
    monkeypatch.setattr(HistoryRetriever, '_aget_relevant_documents', get_history)
    monkeypatch.setattr(DocumentRetriever, '_aget_relevant_documents', get_documents)

    class Gateway:
        def __init__(self):
            self.requests = []
            self.outputs = deque([{'answer': '제약에 따른 답변'}])

        async def stream(self, session, request, conversation_id=None):
            self.requests.append(request)
            yield StreamEvent('delta', json.dumps(self.outputs.popleft(), ensure_ascii=False))
            yield StreamEvent('completed')

    gateway = Gateway()
    manager = AdvisorManager(gateway, context_router, context_builder_manager, 12)
    graph = build_conversation_graph(session, manager, conversation, AskOptions(), 'fake',
                                     checkpointer=InMemorySaver())
    result = asyncio.run(graph.ainvoke(initial_state('내 필수 제약은 무엇인가요?'),
        {'configurable': {'thread_id': 'interface-test'}}, durability='sync'))
    assert result['answer'] == '제약에 따른 답변'
    assert observed == {'store': 1, 'history': 1, 'documents': 1}
    assert isinstance(graph.store, ConfirmedMemoryStore)
    assert all(json.dumps(request.input, ensure_ascii=False).count('고유 합성 제약') == 1 for request in gateway.requests)


def test_selected_scenario_lineage_starts_in_graph_sources():
    state = initial_state('조건 변경', selected_scenario={'title': '기존 대안', 'source_snapshot_id': 'original-source'})
    assert state['sources'] == ['original-source']


def test_single_response_streams_context_before_real_provider_chunks(monkeypatch):
    from types import SimpleNamespace
    from app.modules.advisor.runtime import graph as module
    events = []

    class Assembler:
        def __init__(self, *args, **kwargs):
            self.last_context = {'type': 'context', 'context_snapshot_id': 'synthetic'}

        async def assemble(self, *args, **kwargs):
            return SimpleNamespace(), SimpleNamespace(snapshot_id='synthetic')

    class Gateway:
        async def stream(self, *args, **kwargs):
            assert events == [{'type': 'context', 'context_snapshot_id': 'synthetic'}]
            yield StreamEvent('delta', '첫 조각')
            assert events[-1] == {'type': 'delta', 'text': '첫 조각'}
            yield StreamEvent('delta', ' 다음 조각')
            yield StreamEvent('completed')

    async def observe(event):
        events.append(event)

    monkeypatch.setattr(module, 'ContextAssembler', Assembler)
    graph = build_conversation_graph(None, SimpleNamespace(gateway=Gateway()), SimpleNamespace(id=1),
                                    AskOptions(), 'fake', on_stream=observe)
    result = asyncio.run(graph.ainvoke(initial_state('질문', single_response=True)))
    assert result['answer'] == '첫 조각 다음 조각'
    assert [event['type'] for event in events] == ['context', 'delta', 'delta']


def test_real_graph_summarizes_overflow_once_with_source_range(session):
    from sqlalchemy import select
    from app.modules.crud import context_snapshot_handler, message_handler
    from app.modules.database.model import ConversationSummary
    conversation = AdvisorConversation(title='긴 합성 상담')
    session.add(conversation)
    session.flush()
    snapshot = context_snapshot_handler.create(session, {'id': 'long-history-source', 'conversation_id': conversation.id,
        'context_categories': ['career'], 'excluded_categories': [], 'record_references': [],
        'source_updated_at': {}, 'data_quality_flags': [], 'payload': {'data': {}}, 'content_hash': 'synthetic'})
    messages = [message_handler.create(session, {'conversation_id': conversation.id, 'role': role,
        'content': content, 'context_snapshot_id': snapshot.id}) for role, content in [
        ('user', '주말 근무는 불가능합니다.'), ('assistant', '제약을 확인했습니다.'),
        ('user', '최근 면접 질문'), ('assistant', '최근 면접 답변')]]
    session.commit()

    class Gateway:
        def __init__(self):
            self.requests = []
            self.outputs = deque([{'content': '과거 확인 조건: 주말 근무 불가.'},
                {'objective': '면접 검토'}, {'valid': True}, {'answer': '조건을 반영했습니다.'},
                {'objective': '면접 후속 검토'}, {'valid': True}, {'answer': '후속 조건을 반영했습니다.'}])

        async def stream(self, session, request, conversation_id=None):
            self.requests.append(request)
            yield StreamEvent('delta', json.dumps(self.outputs.popleft(), ensure_ascii=False))
            yield StreamEvent('completed')

    gateway = Gateway()
    manager = AdvisorManager(gateway, context_router, context_builder_manager, 2)

    async def execute():
        first = build_conversation_graph(session, manager, conversation, AskOptions(), 'fake')
        result = await first.ainvoke(initial_state('면접 계획을 검토해 주세요', depth='deep'))
        second = build_conversation_graph(session, manager, conversation, AskOptions(), 'fake')
        again = await second.ainvoke(initial_state('면접 후속 계획을 검토해 주세요', depth='deep'))
        return result, again

    result, again = asyncio.run(execute())
    summary = session.scalar(select(ConversationSummary))
    assert summary.generator == 'graph_summary_v1'
    assert (summary.first_message_id, summary.last_message_id) == (messages[0].id, messages[1].id)
    assert result['summary_id'] == again['summary_id'] == summary.id
    assert result['model_calls'] == 4 and again['model_calls'] == 3
    assert '주말 근무는 불가능합니다.' in json.dumps(gateway.requests[0].input, ensure_ascii=False)
    assert '과거 확인 조건: 주말 근무 불가.' in json.dumps(gateway.requests[-1].input, ensure_ascii=False)
    assert len(session.scalars(select(ConversationSummary)).all()) == 1
