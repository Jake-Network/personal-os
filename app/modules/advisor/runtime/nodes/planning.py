"""History summary, research planning and clarification nodes."""
import hashlib
import json
import re

from langgraph.types import interrupt

from app.modules.advisor.runtime.nodes.base import limits
from app.modules.advisor.runtime.numeric_guard import numeric_values
from app.modules.advisor.runtime.schemas import HistorySummary, Plan
from app.modules.llm.errors import AdvisorError


def signature(task):
    return hashlib.sha256(json.dumps(task, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


async def summarize(ctx, state):
    assembler = ctx.assembler
    if state.get('depth') != 'deep':
        # Assembly reuses a source-checked summary or bounded, disclosed excerpts.
        # Auto consultation never adds a serial provider call just for history.
        return state
    if not hasattr(assembler, 'history_overflow'):
        return state
    overflow = await assembler.history_overflow(state['query'])
    if not overflow:
        return state
    saved = assembler.saved_history_summary(overflow)
    if saved is not None:
        return {**state, 'summary_id': saved.id}
    if state['model_calls'] >= limits(state)[0] - 3:
        return {**state, 'limitations': [*state['limitations'], '이전 대화 요약은 호출 예산으로 인해 출처가 있는 발췌를 사용합니다.']}
    await ctx.progress('summarizing', messages=len(overflow['source_message_ids']))
    state['sources'] = list(dict.fromkeys([*state['sources'], *overflow['source_snapshot_ids']]))
    try:
        result = await ctx.call(state, '이전 대화를 간결하게 요약하세요. 사실·사용자 가정·미해결 조건을 구별하고 '
            '과거 잔고·일정은 당시 기록으로 표시하세요. 새 사실이나 확정 기억을 만들지 마세요. '
            '의사결정의 필수 제약을 빠뜨리지 마세요.', HistorySummary,
            {'historical_messages': overflow['messages']}, history_source_ids=overflow['source_message_ids'])
    except AdvisorError as exc:
        if exc.provider_code not in {'analysis_budget_exceeded', 'request_budget_exceeded', 'context_budget_exceeded'}:
            raise
        return {**state, 'limitations': [*state['limitations'], '이전 대화 전체 요약이 예산을 초과하여 출처가 있는 발췌를 사용합니다.']}
    if numeric_values(result.content) - numeric_values(overflow['messages']):
        return {**state, 'limitations': [*state['limitations'], '이전 대화 요약에 확인되지 않은 수치가 있어 출처가 있는 발췌를 사용합니다.']}
    await assembler.check()
    assembler.validate_sources(state['sources'])
    summary = assembler.store_history_summary(result.content, overflow)
    ctx.session.commit()
    return {**state, 'summary_id': summary.id}


async def plan(ctx, state):
    tools = ctx.tools
    await ctx.progress('planning', model_calls=state['model_calls'])
    if state['model_calls'] >= limits(state)[0] - 1:
        return {**state, 'plan': state.get('plan') or {'objective': state['query'], 'tasks': [], 'scenarios': []},
                'clarification': None, 'needs_replan': False,
                'limitations': [*state['limitations'], '추가 조사 계획을 위한 호출 예산이 부족합니다.']}
    conditional = state.get('clarification_unknown') or state.get('clarification_count', 0) >= 2
    from app.modules.playbooks.selection import MAX_SELECTED
    loaded = list(state.get('playbook_slugs', []))
    catalog, catalog_flags = (({}, []) if ctx.explicit_playbooks or len(loaded) >= MAX_SELECTED
                              else ctx.playbook_catalog(state['query'], exclude_slugs=loaded))
    planning = (
        '사용자의 목적·기간·필수 제약을 파악하고 필요한 읽기 조사만 계획하세요. '
        '단순 조회는 대안을 만들지 마세요. 답변에 꼭 필요한 사용자 조건이 없을 때만 확인 질문을 하세요. '
        '일반 조언은 명시적 한계와 조건부 설명으로 바로 답하고 선택적인 선호를 반복해서 묻지 마세요. '
        'period·constraints·assumptions·unresolved를 필요한 범위에서 구조화하세요. '
        'confirmed_facts는 현재 제공된 근거로 확인된 사실만 포함하고 가정이나 추정을 넣지 마세요. '
        '조회 작업은 아래 허용 도구만 사용하고 의존 관계를 명시하세요. 최대 3개 대안이며 '
        '가정은 사실이나 장기 기억과 구별하세요. selected_scenarios는 수정 전 참고 조건입니다. '
        '사용자의 requested_change를 반영한 새 scenarios를 생성하고 기존 가정을 그대로 재사용하지 마세요. '
        '재무 수치 비교는 assumptions.financial의 monthly_expense/monthly_income, 시간 비교는 '
        'assumptions.time의 work_hours_per_week/rest_hours_per_week/committed_hours_per_week/required_hours_per_week로 '
        '명시된 조건만 구조화하세요. 불명확하면 확인 질문을 하세요. '
        + ('사용자가 모르는 조건 또는 확인 질문 한도에 도달했습니다. 추가 확인 질문을 하지 마세요. '
           '모르는 값은 unresolved에 남기고, 가정을 사실로 채우지 말고 가능한 범위의 조건부 답변을 준비하세요. '
           if conditional else '') + '이전 상담의 내용이나 결론이 필요하면 search_sessions로 검색하세요(당시 기록이며 '
        '현재 사실이 아님). 허용 도구: ' + ', '.join(tools) + '. ')
    derived_plan = {'response': state.get('response'), 'previous_issues': state.get('limitations', []),
                    'selected_scenarios': state.get('selected_scenarios', []),
                    'previous_plan': state.get('plan'), 'existing_research': state.get('results', {})}
    result = await ctx.call(state, planning +
        ('playbook_catalog에서 이 질문에 필요한 승인된 상담 절차가 있으면 slug를 playbooks에 최대 2개 넣으세요. '
         '카탈로그에 없는 slug는 쓰지 마세요.' if catalog else ''), Plan, derived_plan,
        context_data={'playbook_catalog': catalog} if catalog else None, context_flags=catalog_flags)
    _, max_tools, _ = limits(state)
    if any(t.tool not in tools for t in result.tasks):
        raise AdvisorError('허용되지 않은 조사 도구입니다.', provider_code='invalid_research_plan')
    # An optional procedure choice never fails the consultation: unknown slugs are dropped and
    # disclosed. Without a catalog in this call there was nothing to choose from.
    offered = {item['slug'] for item in state.get('numeric_basis', {}).get('playbook_catalog', {}).get('items', {}).values()}
    requested = list(dict.fromkeys(result.playbooks)) if catalog else []
    chosen = [slug for slug in requested if slug in offered]
    if len(chosen) < len(requested):
        state['limitations'] = [*state['limitations'], '승인된 플레이북 목록에 없는 절차는 사용하지 않았습니다.']
    present = [item.get('slug') for item in state.get('numeric_basis', {}).get('playbooks', {}).get('items', {}).values()]
    combined = list(dict.fromkeys([*loaded, *present, *chosen]))
    newly = [slug for slug in combined[:MAX_SELECTED] if slug not in present]
    result.playbooks = combined[:MAX_SELECTED]
    if newly:
        state['playbook_slugs'] = combined
        ctx.apply_playbooks(state)
        # Progressive disclosure inside the run: the catalog showed only summaries, so plan the
        # research again once the chosen procedures' steps are in data.playbooks.
        if state['model_calls'] < limits(state)[0] - 2:
            await ctx.progress('loading_playbook', playbooks=newly)
            result = await ctx.call(state, planning + 'data.playbooks에 방금 선택한 승인된 상담 절차의 단계가 있습니다. '
                '그 절차가 확인하라는 근거를 허용 도구로 조사하도록 계획을 다시 작성하세요. 절차는 사실이 아닙니다.',
                Plan, derived_plan)
            if any(t.tool not in tools for t in result.tasks):
                raise AdvisorError('허용되지 않은 조사 도구입니다.', provider_code='invalid_research_plan')
            result.playbooks = combined[:MAX_SELECTED]
        else:
            state['limitations'] = [*state['limitations'],
                '호출 예산이 부족해 선택한 상담 절차를 조사 계획에는 반영하지 못하고 답변에만 사용했습니다.']
    previous = {task['id']: task for task in state.get('plan', {}).get('tasks', [])}
    proposed = {task.id: task.model_dump() for task in result.tasks}
    invalidated = {key for key in previous.keys() | proposed.keys()
                   if key not in previous or key not in proposed or signature(previous[key]) != signature(proposed[key])}
    for _ in proposed:
        invalidated |= {key for key, task in proposed.items() if set(task['depends_on']) & invalidated}
    kept = {key: value if key in proposed and key not in invalidated else None
            for key, value in state['results'].items()}
    pending = sum(kept.get(task_id) is None for task_id in proposed)
    if pending > max_tools - state['tool_calls']:
        # Keep verified work and communicate the missing scope; no silent extra tool calls.
        return {**state, 'needs_replan': False, 'clarification': None,
                'plan': state.get('plan') or {'objective': result.objective, 'tasks': [], 'scenarios': []},
                'limitations': [*state['limitations'], '추가 조사 계획이 남은 도구 예산을 초과하여 기존 결과만 사용합니다.']}
    problem = {key: getattr(result, key) for key in
               ('objective', 'period', 'constraints', 'assumptions', 'unresolved', 'confirmed_facts')}
    if conditional:
        result.clarification = None
    return {**state, 'results': kept, 'plan': result.model_dump(), 'problem': problem, 'needs_replan': False,
            'playbook_slugs': state.get('playbook_slugs', []), 'baseline_snapshot_id': '', 'baseline_payload': {},
            'clarification': result.clarification.model_dump() if result.clarification else None}


def clarify(ctx, state):
    response = interrupt(state['clarification'])
    if isinstance(response, dict):
        response = response.get('answer', response.get('response', ''))
    if not isinstance(response, str) or not response.strip() or len(response) > 10000:
        raise ValueError('확인 질문 응답이 올바르지 않습니다')
    unknown = bool(re.search(r'모름|모르|몰라|미정|미확인|알\s*수\s*없|정하지\s*않|나중에|건너뛰|unknown|not\s*sure|don.t\s*know', response, re.I))
    count = state.get('clarification_count', 0) + 1
    limitations = state.get('limitations', [])
    if unknown or count >= 2:
        limitations = [*limitations, '추가 확인 없이 답변합니다. 확인되지 않은 조건은 미정으로 남겨 조건부로 안내합니다.']
    return {'response': response, 'clarification': None,
            'clarification_count': count, 'clarification_unknown': unknown, 'limitations': limitations,
            'query': state['query'] + '\n사용자 확인 응답: ' + response}
