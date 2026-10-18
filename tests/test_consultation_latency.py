"""Auto mode uses fewer provider boundaries without bypassing answer validation."""
import asyncio
import json
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage

from app.modules.advisor.runtime import graph as module


def execute(monkeypatch, query, outputs, *, depth='auto', tool_registry=None):
    requests, events = [], []

    class Assembler:
        def __init__(self, *args, **kwargs):
            self.last_context = {'type': 'context'}

        async def assemble(self, query, **kwargs):
            requests.append(kwargs)
            return SimpleNamespace(), SimpleNamespace(snapshot_id=f's{len(requests)}', payload={})

        async def history_overflow(self, query):
            raise AssertionError('Auto mode must not add a history-summary provider call')

    class Model:
        def __init__(self, *args):
            pass

        async def ainvoke(self, *args, **kwargs):
            assert outputs, 'Unexpected additional provider call'
            return AIMessage(content=outputs.pop(0))

    async def progress(event):
        events.append(event)

    monkeypatch.setattr(module, 'ContextAssembler', Assembler)
    monkeypatch.setattr(module, 'GatewayChatModel', Model)
    monkeypatch.setattr(module, 'read_tools', lambda _: tool_registry or {})
    graph = module.build_conversation_graph(None, SimpleNamespace(gateway=None), SimpleNamespace(id=1),
                                            None, 'fake', on_progress=progress)
    state = asyncio.run(graph.ainvoke(module.initial_state(query, depth=depth)))
    assert not outputs
    return state, requests, events


@pytest.mark.parametrize('query', [
    'McKinsey 내 성장·승진 가능성',
    '현재 커리어 고민을 정리해줘. ' * 100,
    '현재 순자산 알려줘',
])
def test_auto_dialogue_one_validated_call(monkeypatch, query):
    result, requests, events = execute(monkeypatch, query, ['{"answer":"조건을 확인해 판단할 수 있습니다."}'])
    assert result['model_calls'] == len(requests) == 1
    assert 'FinalAnswer' in requests[0]['instruction']
    assert not {'planning', 'reviewing', 'summarizing'} & {e['stage'] for e in events}
    assert next(e for e in events if e['stage'] == 'model_started')['schema'] == 'FinalAnswer'


def test_auto_final_still_withholds_unbacked_numbers(monkeypatch):
    result, _, _ = execute(monkeypatch, '내 성장 가능성', ['{"answer":"승진 확률은 99%입니다."}'])
    assert '99%' not in result['answer']
    assert result['limitations']


def test_auto_comparison_keeps_tools_and_server_calculations(monkeypatch):
    from langchain_core.tools import StructuredTool
    from pydantic import BaseModel

    class Input(BaseModel):
        query: str

    invoked = []

    async def read(query):
        invoked.append(query)
        return {'snapshot_id': 'cash-source', 'data': {'computed': {'net_worth': {
            'spendable_liquidity': '800', 'spendable_liquidity_complete': True, 'currency': 'KRW'}}}}

    registry = {'get_accounts_summary': StructuredTool.from_function(coroutine=read, name='get_accounts_summary',
                description='synthetic account evidence', args_schema=Input)}
    plan = {'objective': '퇴사 준비 비교', 'tasks': [{'id': 'cash', 'tool': 'get_accounts_summary', 'query': '생활비'}],
            'scenarios': [{'title': '준비', 'assumptions': {'financial': {'monthly_expense': '100', 'monthly_income': '20'}}}]}
    result, requests, events = execute(monkeypatch, '퇴사 준비 시나리오 비교', [json.dumps(plan), '{"answer":"조건부 런웨이는 10개월입니다."}'],
                                      tool_registry=registry)
    assert result['model_calls'] == 2
    assert invoked == ['생활비']
    assert result['scenarios'][0]['results']['server_calculations']['financial']['months'] == '10.0'
    assert result['answer'] == '조건부 런웨이는 10개월입니다.'
    assert not {'reviewing'} & {e['stage'] for e in events}
    assert [e['schema'] for e in events if e['stage'] == 'model_started'] == ['Plan', 'FinalAnswer']


def test_selected_scenario_and_explicit_deep_keep_analysis():
    assert module.needs_analysis(module.initial_state('수정해줘', selected_scenario={'title': '기존 대안'}))
    assert module.needs_analysis(module.initial_state('안녕', depth='deep'))
    assert module.needs_analysis(module.initial_state('이직 커리어 장단점'))
    assert module.needs_analysis(module.initial_state('주 40시간 근무, 56시간 수면, 10시간 약속, 20시간 공부가 가능할까?'))


def test_fenced_json_validates_without_repair_call(monkeypatch):
    result, _, _ = execute(monkeypatch, '안녕', ['```json\n{"answer":"안녕하세요"}\n```'])
    assert result['model_calls'] == 1


def test_schema_failure_repair_diagnostics_never_include_output_or_unknown_keys(monkeypatch):
    secret = 'private-user-data'
    result, _, events = execute(monkeypatch, '안녕', [json.dumps({'answer': '답변', secret: 'secret-value'}), '{"answer":"수정 답변"}'])
    assert result['model_calls'] == 2
    failures = [event for event in events if event['stage'] == 'structured_output_invalid']
    assert len(failures) == 1
    assert failures[0]['schema'] == 'FinalAnswer'
    assert failures[0]['errors'] == [{'type': 'extra_forbidden', 'path': []}]
    assert secret not in json.dumps(events) and 'secret-value' not in json.dumps(events)


def test_surrounding_prose_and_multiple_objects_remain_invalid():
    for value in ['답변: {"answer":"안녕"}', '{"answer":"하나"}{"answer":"둘"}',
                  '```json\n{"answer":"안녕"}\n``` trailing']:
        with pytest.raises(ValueError):
            module.structured_response(value, module.FinalAnswer)


@pytest.mark.parametrize('query', [
    '생활비를 월 200만원으로 바꾸면?',
    '근무를 주 30시간으로 줄이면?',
    '매달 지출 100만원이고 수입 30만원이면 퇴사 가능할까?',
])
def test_quantitative_followup_keeps_calculation_path(query):
    assert module.needs_analysis(module.initial_state(query))
