"""Graph topology, structured validation, and interrupt resumption without external models."""
import asyncio
import json
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.modules.advisor.runtime import graph as module
from app.modules.advisor.runtime.calculations import calculate_scenario


def test_plan_rejects_cycles_and_unknown_dependencies():
    for dependencies in [['missing'], ['a']]:
        with pytest.raises(ValueError):
            module.Plan.model_validate({'objective': 'test', 'tasks': [
                {'id': 'a', 'tool': 'read', 'query': 'q', 'depends_on': dependencies}]})


def run_graph(monkeypatch, outputs, *, resume=None, tool_registry=None, on_progress=None):
    calls = []

    class Assembler:
        def __init__(self, *args, **kwargs):
            self.last_context = {'type': 'context'}

        async def assemble(self, query, **kwargs):
            calls.append((query, kwargs))
            return SimpleNamespace(), SimpleNamespace(snapshot_id=f's{len(calls)}', payload={})

    class Model:
        def __init__(self, *args):
            pass

        async def ainvoke(self, *args, **kwargs):
            return AIMessage(content=outputs.pop(0))

    monkeypatch.setattr(module, 'ContextAssembler', Assembler)
    monkeypatch.setattr(module, 'GatewayChatModel', Model)
    monkeypatch.setattr(module, 'read_tools', lambda _: tool_registry or {})
    graph = module.build_conversation_graph(None, SimpleNamespace(gateway=None), SimpleNamespace(id=1), None,
                                            'fake', checkpointer=InMemorySaver(), on_progress=on_progress)

    async def execute():
        config = {'configurable': {'thread_id': 'run'}}
        result = await graph.ainvoke(module.initial_state('질문'), config, durability='sync')
        if resume:
            assert result['__interrupt__'][0].value['question'] == '어느 기간인가요?'
            for answer in resume if isinstance(resume, list) else [resume]:
                result = await graph.ainvoke(Command(resume=answer), config, durability='sync')
        return result

    return asyncio.run(execute()), calls


def test_graph_structured_answer_uses_common_assembly(monkeypatch):
    result, calls = run_graph(monkeypatch, [
        '{"objective":"확인"}', '{"valid":true}', '{"answer":"근거에 따른 답변"}'])
    assert result['answer'] == '근거에 따른 답변'
    assert result['model_calls'] == len(calls) == 3
    assert calls[-1][1]['sources'] == ['s1', 's2']


def test_graph_interrupt_resumes_same_run(monkeypatch):
    result, calls = run_graph(monkeypatch, [
        '{"objective":"기간 확인","clarification":{"question":"어느 기간인가요?"}}',
        '{"objective":"3개월 검토"}', '{"valid":true}', '{"answer":"3개월 조건의 답변"}',
    ], resume='3개월')
    assert result['answer'] == '3개월 조건의 답변'
    assert '사용자 확인 응답: 3개월' in calls[-1][0]
    assert result['model_calls'] == 4


def test_structured_output_repair_is_counted(monkeypatch):
    result, _ = run_graph(monkeypatch, [
        'invalid', '{"objective":"확인"}', '{"valid":true}', '{"answer":"답변"}'])
    assert result['model_calls'] == 4


def test_dependency_waves_do_not_repeat_completed_tasks(monkeypatch):
    from langchain_core.tools import StructuredTool
    from pydantic import BaseModel
    order = []

    class Input(BaseModel):
        query: str

    async def read(query):
        order.append(query)
        return {'snapshot_id': 'tool-source', 'data': {'value': '100'}}

    registry = {'read': StructuredTool.from_function(coroutine=read, name='read', description='test', args_schema=Input)}
    result, _ = run_graph(monkeypatch, [
        '{"objective":"확인","tasks":[{"id":"a","tool":"read","query":"first"},'
        '{"id":"b","tool":"read","query":"second","depends_on":["a"]}]}',
        '{"valid":true}', '{"answer":"답변"}',
    ], tool_registry=registry)
    assert order == ['first', 'second']
    assert set(result['results']) == {'a', 'b'}
    assert result['tool_calls'] == 2


def test_unknown_tool_rejected_before_any_execution(monkeypatch):
    with pytest.raises(Exception, match='허용되지 않은 조사 도구'):
        run_graph(monkeypatch, ['{"objective":"확인","tasks":[{"id":"a","tool":"write_finances","query":"x"}]}'])


def test_scenario_calculations_preserve_missing_values_and_cash_policy():
    assumptions = {'financial': {'monthly_expense': '100', 'monthly_income': '20'}}
    assert calculate_scenario(assumptions, {})['financial']['available'] is False
    baseline = {'data': {'get_accounts_summary': {'computed': {'net_worth': {
        'spendable_liquidity': '800', 'total_assets': '90000000'}}}}}
    result = calculate_scenario(assumptions, baseline)['financial']
    assert result['months'] == '10.0'
    assert result['usable_cash'] == '800.00'
    assert result['basis'] == 'current_spendable_liquidity_and_scenario_assumptions'


def test_time_constraints_need_explicit_work_rest_and_commitment():
    assumptions = {'time': {'work_hours_per_week': '40', 'rest_hours_per_week': '70',
                            'committed_hours_per_week': '30', 'required_hours_per_week': '29'}}
    result = calculate_scenario(assumptions, {})['time']
    assert result['available_hours_per_week'] == '28'
    assert result['margin_hours_per_week'] == '-1'
    assert result['feasible_under_assumptions'] is False
    assumptions['time'].pop('rest_hours_per_week')
    assert calculate_scenario(assumptions, {})['time']['available'] is False


def test_scenario_subgraph_removes_unbacked_numbers(monkeypatch):
    result, _ = run_graph(monkeypatch, [
        '{"objective":"비교","scenarios":[{"title":"대안 A","assumptions":{},"constraints":{}}]}',
        '{"title":"대안 A","results":{"invented_profit":"990000"}}',
        '{"valid":true}', '{"answer":"확인되지 않은 수익은 제외했습니다."}',
    ])
    assert 'invented_profit' not in result['scenarios'][0]['results']
    assert result['scenarios'][0]['unknowns']
    assert result['baseline_snapshot_id'] in result['sources']


def test_external_call_boundary_markers_match_every_attempt(monkeypatch):
    events = []

    async def progress(event):
        events.append(event)

    result, _ = run_graph(monkeypatch, [
        'invalid', '{"objective":"확인"}', '{"valid":true}', '{"answer":"답변"}',
    ], on_progress=progress)
    markers = [event['stage'] for event in events if event['stage'].startswith('model_')]
    assert markers == ['model_started', 'model_finished'] * result['model_calls']
    assert all('query' not in event and 'answer' not in event for event in events)


@pytest.mark.parametrize('changed, expected', [
    (False, ['first', 'dependent', 'missing']),
    (True, ['first', 'dependent', 'changed', 'dependent', 'missing']),
])
def test_review_discovers_missing_issue_and_replans_with_dependency_invalidation(monkeypatch, changed, expected):
    from langchain_core.tools import StructuredTool
    from pydantic import BaseModel
    order = []

    class Input(BaseModel):
        query: str

    async def read(query):
        order.append(query)
        return {'snapshot_id': 'tool-source', 'data': {'value': '100'}}

    registry = {'read': StructuredTool.from_function(coroutine=read, name='read', description='test', args_schema=Input)}
    tasks = [{'id': 'a', 'tool': 'read', 'query': 'first'},
             {'id': 'b', 'tool': 'read', 'query': 'dependent', 'depends_on': ['a']}]
    revised = [dict(tasks[0], query='changed' if changed else 'first'), tasks[1],
               {'id': 'c', 'tool': 'read', 'query': 'missing', 'depends_on': ['b']}]
    result, _ = run_graph(monkeypatch, [
        json.dumps({'objective': '최초 조사', 'tasks': tasks}),
        '{"valid":false,"issues":["시간 제약 확인 누락"],"needs_replan":true}',
        json.dumps({'objective': '누락 쟁점 추가 조사', 'tasks': revised}),
        '{"valid":true}', '{"answer":"추가 쟁점까지 조사했습니다."}',
    ], tool_registry=registry)
    assert order == expected
    assert result['tool_calls'] == len(expected)
    assert result['replans'] == 1
    assert result['results']['c']['data'] == {'value': '100'}


def test_clarifications_exhaust_budget_into_partial_answer(monkeypatch):
    question = '{"objective":"확인","clarification":{"question":"어느 기간인가요?"}}'
    result, calls = run_graph(monkeypatch, [question] * 5 + ['{"answer":"추가 확인 한도로 현재 한계만 반환합니다."}'],
                              resume=['미정'] * 5)
    assert result['model_calls'] == 6
    assert result['answer']
    assert result['limitations']


def test_saved_scenario_recalculates_only_changed_components(monkeypatch):
    from copy import deepcopy
    from app.modules.advisor.runtime.calculations import financial_calculator
    assumptions = {'financial': {'monthly_expense': '100', 'monthly_income': '20'},
                   'time': {'work_hours_per_week': '40', 'rest_hours_per_week': '70',
                            'committed_hours_per_week': '30', 'required_hours_per_week': '20'}}
    baseline = {'data': {'get_accounts_summary': {'computed': {'net_worth': {'spendable_liquidity': '800'}}}}}
    original = calculate_scenario(assumptions, baseline)
    immutable = deepcopy(original)
    calls = []
    runway = financial_calculator.runway

    def counted(*args, **kwargs):
        calls.append(args)
        return runway(*args, **kwargs)

    monkeypatch.setattr(financial_calculator, 'runway', counted)
    changed_time = deepcopy(assumptions)
    changed_time['time']['required_hours_per_week'] = '29'
    revised = calculate_scenario(changed_time, baseline, previous_results={'server_calculations': original})
    assert revised['financial']['reused'] is True
    assert revised['time']['reused'] is False
    assert revised['time']['margin_hours_per_week'] == '-1'
    assert calls == []
    changed_cash = deepcopy(baseline)
    changed_cash['data']['get_accounts_summary']['computed']['net_worth']['spendable_liquidity'] = '1600'
    refreshed = calculate_scenario(changed_time, changed_cash, previous_results=revised)
    assert refreshed['financial']['reused'] is False
    assert refreshed['financial']['months'] == '20.0'
    assert refreshed['time']['reused'] is True
    assert len(calls) == 1
    assert original == immutable


def test_numeric_answer_uses_values_and_server_calculations_not_row_ids():
    basis = {'current_data': {'accounts': [{'id': 123, 'balance': '1,200.00', 'ref': 'accounts:999'}]},
             'calculations': {'months': '10.0'}, 'query': '2026-10-18부터 3개월'}
    answer, withheld = module.validated_numeric_answer(
        '1. 잔고는 1,200원입니다.\n런웨이는 10.0개월입니다.\n123원 이익입니다.\n999원 지출입니다.', basis)
    assert withheld
    assert '1,200원' in answer and '10.0개월' in answer
    assert '123원' not in answer and '999원' not in answer
    assert module.validated_numeric_answer('2026년 10월 18일부터 3개월입니다.', basis)[1] is False


def test_discovered_finance_task_supplies_common_calculation_baseline(monkeypatch):
    from langchain_core.tools import StructuredTool
    from pydantic import BaseModel

    class Input(BaseModel):
        query: str

    async def accounts(query):
        return {'snapshot_id': 'financial-source', 'data': {'computed': {'net_worth': {
            'spendable_liquidity': '800', 'spendable_liquidity_complete': True, 'currency': 'KRW'}}}}

    registry = {'get_accounts_summary': StructuredTool.from_function(coroutine=accounts,
        name='get_accounts_summary', description='synthetic', args_schema=Input)}
    plan = {'objective': '이직 준비', 'period': '3개월', 'constraints': {'employment': '퇴사 검토'},
            'assumptions': {'income': '중단'}, 'confirmed_facts': [], 'unresolved': [],
            'tasks': [{'id': 'cash', 'tool': 'get_accounts_summary', 'query': '생활비 현금 확인'}],
            'scenarios': [{'title': '퇴사 준비', 'assumptions': {'financial': {'monthly_expense': '100', 'monthly_income': '20'}}}]}
    result, _ = run_graph(monkeypatch, [json.dumps(plan), '{"title":"퇴사 준비"}',
        '{"valid":true}', '{"answer":"시나리오 조건의 런웨이는 10개월입니다."}'], tool_registry=registry)
    assert result['scenarios'][0]['results']['server_calculations']['financial']['months'] == '10.0'
    assert result['problem']['period'] == '3개월'
    assert result['problem']['constraints'] == {'employment': '퇴사 검토'}
    assert result['answer'] == '시나리오 조건의 런웨이는 10개월입니다.'
