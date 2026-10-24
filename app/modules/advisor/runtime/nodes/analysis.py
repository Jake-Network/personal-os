"""Scenario analysis on a shared evidence baseline, and evidence review."""
import json
import re

from langgraph.graph import END, START, StateGraph
from langsmith import tracing_context

from app.modules.advisor.runtime.calculations import calculate_scenario
from app.modules.advisor.runtime.nodes.base import limits
from app.modules.advisor.runtime.schemas import Review, Scenario
from app.modules.advisor.runtime.state import ConsultationState


async def analyze(ctx, state):
    await ctx.progress('analyzing', alternatives=len(state['plan']['scenarios']))
    # Every alternative receives the same explicit evidence baseline and its own assumptions.
    if not state.get('baseline_snapshot_id') and state['plan']['scenarios']:
        _, baseline = await ctx.assembler.assemble(state['query'], sources=state['sources'])
        state['baseline_snapshot_id'] = baseline.snapshot_id
        state['baseline_payload'] = baseline.payload
        data = dict(baseline.payload.get('data', {}))
        for task in state['plan']['tasks']:
            research = state['results'].get(task['id'])
            if research is not None and task['tool'].startswith('get_'):
                data[task['tool']] = research.get('data')
        state['baseline_payload'] = {**baseline.payload, 'data': data,
            'research_snapshot_ids': [r['snapshot_id'] for r in state['results'].values() if r is not None],
            'data_quality_flags': [*baseline.payload.get('data_quality_flags', []),
                *(flag for r in state['results'].values() if r is not None for flag in r.get('data_quality_flags', []))]}
        state['sources'] = list(dict.fromkeys([*state['sources'], baseline.snapshot_id]))
    scenarios = []
    async def isolated(input_state):
        scenario = input_state['selected_scenarios'][0]
        result = await ctx.call(input_state, '이 대안 하나만 검토하세요. 다른 대안의 임시 가정을 섞지 마세요. '
            '숫자는 제공된 서버 계산 결과만 사용하고 미확인 값은 unknowns에 남기세요. '
            '수치 계산 결과를 새로 만들지 마세요.', Scenario,
            {'scenario': scenario, 'evidence': input_state['results'], 'user_response': input_state.get('response')})
        validated = result.model_dump()
        validated.update(title=scenario['title'], assumptions=scenario.get('assumptions', {}),
                         constraints=scenario.get('constraints', {}))
        # Computed fields must be backed by server evidence, never free-form model arithmetic.
        for key, value in list(validated['results'].items()):
            numbers = re.findall(r'-?\d+(?:\.\d+)?', json.dumps(value, ensure_ascii=False))
            if numbers:
                validated['results'].pop(key)
                validated['unknowns'].append(f'{key}: 서버 계산 근거가 없어 수치를 표시하지 않았습니다.')
        validated['results']['server_calculations'] = calculate_scenario(scenario.get('assumptions', {}),
            input_state.get('baseline_payload', {}), previous_results=input_state.get('previous_scenario_results'))
        return {**input_state, 'scenarios': [validated]}
    subgraph = StateGraph(ConsultationState)
    subgraph.add_node('alternative', isolated)
    subgraph.add_edge(START, 'alternative')
    subgraph.add_edge('alternative', END)
    compiled_alternative = subgraph.compile()
    for scenario in state['plan']['scenarios']:
        if state.get('depth') != 'deep':
            # The final answer explains all alternatives together; calculations stay server owned.
            scenarios.append({**scenario, 'results': {'server_calculations': calculate_scenario(
                scenario.get('assumptions', {}), state.get('baseline_payload', {}),
                previous_results=state.get('previous_scenario_results'))}})
            continue
        if state['model_calls'] >= limits(state)[0] - 2:
            state['limitations'].append('호출 한도로 일부 대안의 상세 분석을 생략했습니다.')
            break
        isolated_state = {**state, 'selected_scenarios': [scenario], 'scenarios': []}
        with tracing_context(enabled=False):
            result = await compiled_alternative.ainvoke(isolated_state)
        state['model_calls'], state['sources'] = result['model_calls'], result['sources']
        state['context'], state['snapshot_id'] = result['context'], result['snapshot_id']
        scenarios.extend(result['scenarios'])
    return {**state, 'scenarios': scenarios}


async def review(ctx, state):
    await ctx.progress('reviewing', model_calls=state['model_calls'])
    if state['model_calls'] >= limits(state)[0] - 1:
        return state
    result = await ctx.call(state, '근거·인용·필수 제약의 누락과 상충을 검토하세요. '
        '기존 작업의 실패는 retry_tasks로, 새로운 의존 쟁점이나 누락된 조회가 필요하면 '
        'needs_replan=true와 구체적 issues로 반환하세요.', Review,
        {'plan': state['plan'], 'results': state['results'], 'scenarios': state['scenarios']})
    state['limitations'] += result.issues
    # Only failed tasks are repeated; dependency consumers are invalidated as well.
    retry = set(result.retry_tasks) & set(state['results'])
    can_replan = state['replans'] < limits(state)[2] and state['model_calls'] < limits(state)[0] - 2
    if can_replan and (result.needs_replan or (not result.valid and result.issues and not retry)):
        state['replans'] += 1
        state['needs_replan'] = True
        return state
    if retry and can_replan:
        for _ in state['plan']['tasks']:
            retry |= {t['id'] for t in state['plan']['tasks'] if set(t['depends_on']) & retry}
        if state['tool_calls'] + len(retry) <= limits(state)[1]:
            state['replans'] += 1
            state['results'] = {k: None if k in retry else v for k, v in state['results'].items()}
    return state
