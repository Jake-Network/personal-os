"""Bounded, resumable consultation graph; all writes remain in app services."""
import json
import re
import hashlib
from dataclasses import replace
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send, interrupt
from langsmith import tracing_context
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.advisor.runtime.adapters import GatewayChatModel, read_tools
from app.modules.advisor.runtime.context import ContextAssembler
from app.modules.advisor.runtime.calculations import calculate_scenario
from app.modules.llm.errors import AdvisorError


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class ResearchTask(StrictModel):
    id: str = Field(min_length=1, max_length=80)
    tool: str
    query: str = Field(min_length=1, max_length=4000)
    depends_on: list[str] = Field(default_factory=list)


class Question(StrictModel):
    question: str = Field(min_length=1, max_length=2000)
    reason: str = Field(default='', max_length=2000)
    options: list[str] = Field(default_factory=list, max_length=8)


class Scenario(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    assumptions: dict[str, Any] = Field(default_factory=dict)
    constraints: dict[str, Any] = Field(default_factory=dict)
    results: dict[str, Any] = Field(default_factory=dict)
    unknowns: list[str] = Field(default_factory=list)


class Plan(StrictModel):
    objective: str
    period: str | None = None
    constraints: dict = Field(default_factory=dict)
    assumptions: dict = Field(default_factory=dict)
    unresolved: list[str] = Field(default_factory=list)
    confirmed_facts: list[str] = Field(default_factory=list)
    tasks: list[ResearchTask] = Field(default_factory=list, max_length=24)
    clarification: Question | None = None
    scenarios: list[Scenario] = Field(default_factory=list, max_length=3)
    # Slugs from the provided playbook catalog whose full procedure this question needs.
    playbooks: list[str] = Field(default_factory=list, max_length=2)

    @model_validator(mode='after')
    def acyclic(self):
        ids = [task.id for task in self.tasks]
        if len(ids) != len(set(ids)):
            raise ValueError('duplicate task id')
        done = set()
        while len(done) < len(ids):
            ready = {task.id for task in self.tasks if task.id not in done and set(task.depends_on) <= done}
            if not ready:
                raise ValueError('cyclic or missing task dependency')
            done |= ready
        return self


class Proposal(StrictModel):
    action: Literal['create_task', 'calendar_update', 'goal_update']
    payload: dict
    rationale: str = ''


class Memory(StrictModel):
    kind: Literal['profile', 'preference', 'constraint', 'priority']
    content: str = Field(min_length=1)


class FinalAnswer(StrictModel):
    answer: str = Field(min_length=1)
    proposals: list[Proposal] = Field(default_factory=list)
    memories: list[Memory] = Field(default_factory=list)


class Review(StrictModel):
    valid: bool = True
    issues: list[str] = Field(default_factory=list)
    retry_tasks: list[str] = Field(default_factory=list)
    needs_replan: bool = False


class HistorySummary(StrictModel):
    content: str = Field(min_length=1, max_length=12000)


NUMBER_PATTERN = re.compile(r'(?<![A-Za-z0-9_])[-+]?\d[\d,]*(?:\.\d+)?')
# Exact-number membership is only a conservative guard for sensitive claims,
# not a general fact checker: ordinary arithmetic and advice introduce new numbers.
SENSITIVE_NUMERIC_CLAIM = re.compile(
    r'\d[\d,.]*\s*(?:억|만|천)?\s*(?:원|달러|유로|엔)|[₩$€¥]|'
    r'자산|부채|잔고|잔액|현금|생활비|지출|수입|수익|이익|손익|저축|연금|'
    r'금액|금리|환율|런웨이|증가율|감소율|확률|성공률|합격률|승진율|발생률|'
    r'가능성[^\n]*(?:%|퍼센트)|(?:%|퍼센트)[^\n]*가능성|'
    r'\b(?:KRW|USD|EUR|JPY|balance|cash|income|expense|profit|return|interest|'
    r'runway|probability|chance|odds)\b', re.IGNORECASE)
IGNORED_NUMERIC_FIELDS = {'id', 'ref', 'revision', 'revision_id', 'source_reference', 'source_references',
    'record_references', 'context_snapshot_id', 'source_snapshot_id', 'snapshot_id', 'dependency_hash',
    'calculation_version', 'created_at', 'updated_at', 'generated_at', 'first_message_id', 'last_message_id',
    'url', 'content_hash', 'retrieved_at'}


def numeric_values(value):
    """Normalized supplied numbers; persistence IDs and provenance metadata are never evidence."""
    if isinstance(value, bool) or value is None:
        return set()
    if isinstance(value, dict):
        if value.get('historical') is True:
            return set()
        return set().union(*(numeric_values(item) for key, item in value.items()
            if key not in IGNORED_NUMERIC_FIELDS and not key.endswith('_id') and not key.endswith('_ids'))) if value else set()
    if isinstance(value, (list, tuple)):
        return set().union(*(numeric_values(item) for item in value)) if value else set()
    text = re.sub(r'\[(?:document_chunks|advisor_messages):\d+\]', '', str(value))
    text = re.sub(r'https?://[^\s<>]+', '', text)
    text = re.sub(r'\b(\d{4})-(\d{1,2})-(\d{1,2})\b', r'\1 \2 \3', text)
    values = set()
    for match in NUMBER_PATTERN.finditer(text):
        try:
            number = Decimal(match.group().replace(',', ''))
            suffix = text[match.end():].lstrip()
            multiplier = Decimal(100000000) if suffix.startswith('억') else Decimal(10000) if suffix.startswith('만') else Decimal(1000) if suffix.startswith('천') else Decimal(1)
            values.add(number * multiplier)
        except InvalidOperation:
            continue
    return values


def validated_numeric_answer(answer, basis):
    """Withhold unbacked financial/statistical claims, preserving general numeric advice."""
    allowed = numeric_values(basis)
    chunks = re.split(r'\n|(?<=[.!?。])\s+(?=[^\d])', answer)
    verified, withheld = [], False
    for chunk in chunks:
        # Ordered-list markers organize text; they are not quantitative claims.
        content = re.sub(r'^\s*\d{1,2}[.)]\s+', '', chunk)
        if SENSITIVE_NUMERIC_CLAIM.search(content) and numeric_values(content) - allowed:
            withheld = True
            verified.append('[수치 근거를 확인할 수 없어 해당 설명을 생략했습니다.]')
        else:
            verified.append(chunk)
    return '\n'.join(verified), withheld


def merge_results(left, right):
    return {**(left or {}), **(right or {})}


class ConsultationState(TypedDict, total=False):
    query: str
    depth: str
    single_response: bool
    plan: dict
    results: Annotated[dict, merge_results]
    executed_tools: int
    tool_executions: Annotated[dict, merge_results]
    execution_id: str
    needs_replan: bool
    previous_scenario_results: dict
    selected_scenarios: list[dict]
    baseline_snapshot_id: str
    baseline_payload: dict
    task: dict
    scenarios: list[dict]
    answer: str
    proposals: list[dict]
    memories: list[dict]
    clarification: dict | None
    response: str
    snapshot_id: str
    context: dict
    model_calls: int
    tool_calls: int
    replans: int
    sources: list[str]
    limitations: list[str]
    problem: dict
    numeric_basis: dict
    summary_id: int
    web_snapshot_id: str
    previous_analysis: bool
    clarification_count: int
    clarification_unknown: bool
    playbook_slugs: list[str]


def scenario_followup(query):
    """A workspace selection applies to a requested revision, not every later question."""
    if re.search(r'다른\s*질문|새로운?\s*(?:질문|주제)|주제를?\s*바', query):
        return False
    return bool(re.search(r'(?:이|그|선택한)\s*(?:대안|시나리오)|수정해|조건\s*변경', query)
                or quantitative_followup(query))


def quantitative_followup(query):
    return bool(re.search(r'\d', query) and re.search(r'만원|원|시간|월\s*\d|주\s*\d', query)
                and re.search(r'그럼|그러면|이면|라면|바꾸면|줄이면|늘리면', query)
                and not re.search(r'다른\s*질문|새로운?\s*(?:질문|주제)', query))


def initial_state(query, depth='auto', single_response=False, scenarios=None, selected_scenario=None,
                  previous_analysis=False, explicit_scenario=False):
    selected = scenarios or ([selected_scenario] if selected_scenario else [])
    if not explicit_scenario and not scenario_followup(query):
        selected = []
    sources = list(dict.fromkeys(item['source_snapshot_id'] for item in selected if item.get('source_snapshot_id')))
    return {'query': query, 'depth': depth, 'single_response': single_response,
            'results': {}, 'scenarios': [], 'model_calls': 0, 'tool_calls': 0,
            'replans': 0, 'sources': sources, 'limitations': [], 'proposals': [], 'memories': [], 'executed_tools': 0,
            'selected_scenarios': selected, 'tool_executions': {}, 'needs_replan': False,
            'previous_analysis': previous_analysis, 'clarification_count': 0, 'clarification_unknown': False,
            'previous_scenario_results': selected[0].get('prior_results', {}) if selected else {}}


def needs_analysis(state):
    """Reserve planning for explicit analysis and comparisons with material constraints."""
    if state.get('depth') == 'deep' or state.get('selected_scenarios'):
        return True
    query = state.get('query', '')
    if state.get('previous_analysis') and quantitative_followup(query):
        return True
    comparison = re.search(r'비교|시나리오|대안|트레이드오프|장단점|선택|어느.{0,12}(좋|나)|뭐가\s*더|versus|\bvs\b', query, re.I)
    constraints = re.search(r'예산|생활비|지출|소득|잔고|퇴사|런웨이|시간|일정|조건|제약|개월|만원|억|이직|커리어|경력|투자|부채|목표|위험', query)
    explicit = re.search(r'심층|종합\s*분석|상세\s*분석|재무\s*분석|계산해|계산해줘', query)
    financial_calculation = re.search(r'생활비|지출|소득|잔고|현금|만원|런웨이', query) and re.search(r'버틸|계산|런웨이|면.{0,30}얼마', query)
    time_feasibility = re.search(r'시간|수면|근무', query) and re.search(r'가능|여유|할\s*수|남는|남을|계산|부족', query)
    quantitative_change = (re.search(r'생활비|지출|소득|수입|현금|잔고|근무|시간|수면', query)
        and re.search(r'\d', query)
        and re.search(r'바꾸면|줄이면|늘리면|쓴다면|벌면|가능|충분|부족|남을|남는', query))
    multiple = len(re.findall(r'[?？]', query)) > 1 and bool(constraints)
    return bool(explicit or (comparison and constraints) or financial_calculation or time_feasibility or quantitative_change or multiple)


def structured_response(content, schema):
    """Accept one complete JSON object, optionally wrapped in a Markdown fence."""
    value = str(content).strip()
    fenced = re.fullmatch(r'```(?:json)?\s*\n([\s\S]*?)\n```', value, re.I)
    if fenced:
        value = fenced.group(1).strip()
    return schema.model_validate_json(value)


def build_conversation_graph(session, manager, conversation, options, model, checkpointer=None,
                             guard=None, current_message_id=None, on_progress=None, run_authorization=None,
                             on_stream=None, run_id=None, run_owner=None, run_generation=None):
    assembler = ContextAssembler(session, manager, conversation, options, model,
                                 guard=guard, current_message_id=current_message_id, authorization=run_authorization, run_id=run_id,
                                 run_owner=run_owner, run_generation=run_generation)
    tools = read_tools(assembler)
    base_options = options
    explicit_playbooks = bool(getattr(options, 'playbook_ids', ()) or getattr(options, 'playbook_slugs', ()))

    def apply_playbooks(state):
        # A plan's choice persists in the checkpoint; a user's explicit choice always wins.
        if options is not None and not explicit_playbooks and state.get('playbook_slugs'):
            assembler.options = replace(base_options, playbook_slugs=tuple(state['playbook_slugs']))

    def playbook_catalog(query):
        if options is None or session is None:
            return {}, []
        from app.modules.playbooks.selection import catalog_context
        return catalog_context(session, manager.sharing_exclusions(session, options), query)

    async def progress(stage, **metadata):
        if on_progress:
            messages = {
                'planning': '질문과 필요한 근거를 확인하고 있습니다.',
                'research_started': '공유가 허용된 최신 기록을 확인하고 있습니다.',
                'research_finished': '기록 확인을 마쳤습니다.',
                'analyzing': '확인한 근거와 조건을 정리하고 있습니다.',
                'reviewing': '근거와 제약이 빠지지 않았는지 검토하고 있습니다.',
                'answering': '답변을 작성하고 있습니다. 검증을 마치면 표시합니다.',
                'model_finished': '모델 응답을 받았습니다. 결과를 확인하고 있습니다.',
                'structured_output_invalid': '응답 형식을 확인하고 다시 정리하고 있습니다.',
                'summarizing': '이전 대화에서 필요한 맥락을 정리하고 있습니다.',
                'web_searching': '허용한 공개 검색어로 웹 자료를 확인하고 있습니다.',
            }
            if stage == 'model_started':
                message = ('답변을 작성하고 있습니다. 검증을 마치면 표시합니다.'
                           if metadata.get('schema') == 'FinalAnswer' else '질문에 필요한 내용을 검토하고 있습니다.')
            else:
                message = messages.get(stage, '상담을 진행하고 있습니다.')
            await on_progress({'stage': stage, 'message': message, **metadata})

    def limits(state):
        return (12, 24, 3) if state.get('depth') == 'deep' else (6, 12, 2)

    def signature(task):
        return hashlib.sha256(json.dumps(task, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    def pending_tasks(state):
        return [task for task in state['plan']['tasks'] if state.get('results', {}).get(task['id']) is None]

    async def call(state, instruction, schema=None, derived=None, history_source_ids=(), context_data=None, context_flags=()):
        max_calls, _, _ = limits(state)
        assembler.baseline_snapshot_id = state.get('baseline_snapshot_id')
        attempts = 2 if schema else 1
        validation_errors = []
        apply_playbooks(state)
        for attempt in range(attempts):
            if state['model_calls'] >= max_calls:
                raise AdvisorError('상담 모델 호출 한도에 도달했습니다.', provider_code='analysis_budget_exceeded')
            state['model_calls'] += 1
            prompt = instruction
            if schema:
                prompt += '\nJSON 객체만 반환하세요. 스키마: ' + json.dumps(schema.model_json_schema(), ensure_ascii=False)
            if attempt:
                prompt += '\n직전 출력이 스키마 검증에 실패했습니다. 스키마에 맞게 한 번 수정하세요.'
                prompt += '\n검증 오류(필드 경로와 오류 유형만): ' + json.dumps(validation_errors, ensure_ascii=False)
                prompt += '\n필수 필드와 자료형을 확인하고, 스키마에 없는 필드와 JSON 밖의 설명은 빼세요.'
            extra = {'history_source_ids': history_source_ids} if history_source_ids else {}
            if context_data or context_flags:
                extra.update(context_data=context_data, context_flags=context_flags)
            request, package = await assembler.assemble(state['query'], instruction=prompt,
                derived=derived, sources=state.get('sources', []), structured_output=schema is not None, **extra)
            state['sources'] = list(dict.fromkeys([*state.get('sources', []), package.snapshot_id]))
            state['snapshot_id'], state['context'] = package.snapshot_id, assembler.last_context
            state['numeric_basis'] = getattr(package, 'payload', {}).get('data', {})
            async def stream_delta(text):
                if on_stream:
                    await on_stream({'type': 'delta', 'text': text})
            if state.get('single_response') and on_stream:
                await on_stream(state['context'])
            adapter = GatewayChatModel(manager.gateway, session, request, conversation.id,
                **({'on_delta': stream_delta} if state.get('single_response') and on_stream else {}))
            await progress('model_started', model_calls=state['model_calls'], snapshot_id=package.snapshot_id,
                           schema=schema.__name__ if schema else None)
            with tracing_context(enabled=False):
                response = await adapter.ainvoke([], config={'callbacks': []})
            await progress('model_finished', model_calls=state['model_calls'], snapshot_id=package.snapshot_id,
                           schema=schema.__name__ if schema else None)
            if schema is None:
                return str(response.content)
            try:
                return structured_response(response.content, schema)
            except ValueError as exc:
                # Content may contain private data; record only schema field names and error kinds.
                errors = exc.errors(include_input=False, include_context=False, include_url=False) if hasattr(exc, 'errors') else []
                validation_errors = [
                    {'type': item['type'], 'path': [str(part) for part in item['loc']
                        if not isinstance(part, str) or part in schema.model_fields]}
                    for item in errors[:8]]
                await progress('structured_output_invalid', schema=schema.__name__, attempt=attempt + 1,
                    errors=validation_errors)
                if attempt == attempts - 1:
                    raise AdvisorError('모델의 구조화된 분석 결과를 검증하지 못했습니다.', provider_code='invalid_structured_output')

    async def summarize(state):
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
        await progress('summarizing', messages=len(overflow['source_message_ids']))
        state['sources'] = list(dict.fromkeys([*state['sources'], *overflow['source_snapshot_ids']]))
        try:
            result = await call(state, '이전 대화를 간결하게 요약하세요. 사실·사용자 가정·미해결 조건을 구별하고 '
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
        session.commit()
        return {**state, 'summary_id': summary.id}

    async def plan(state):
        await progress('planning', model_calls=state['model_calls'])
        if state['model_calls'] >= limits(state)[0] - 1:
            return {**state, 'plan': state.get('plan') or {'objective': state['query'], 'tasks': [], 'scenarios': []},
                    'clarification': None, 'needs_replan': False,
                    'limitations': [*state['limitations'], '추가 조사 계획을 위한 호출 예산이 부족합니다.']}
        conditional = state.get('clarification_unknown') or state.get('clarification_count', 0) >= 2
        catalog, catalog_flags = ({}, []) if explicit_playbooks else playbook_catalog(state['query'])
        result = await call(state,
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
               if conditional else '') + '허용 도구: ' + ', '.join(tools) +
            ('. playbook_catalog에서 이 질문에 필요한 승인된 상담 절차가 있으면 slug를 playbooks에 최대 2개 넣으세요. '
             '카탈로그에 없는 slug는 쓰지 마세요.' if catalog else ''), Plan,
            {'response': state.get('response'), 'previous_issues': state.get('limitations', []),
             'selected_scenarios': state.get('selected_scenarios', []),
             'previous_plan': state.get('plan'), 'existing_research': state.get('results', {})},
            context_data={'playbook_catalog': catalog} if catalog else None, context_flags=catalog_flags)
        _, max_tools, _ = limits(state)
        if any(t.tool not in tools for t in result.tasks):
            raise AdvisorError('허용되지 않은 조사 도구입니다.', provider_code='invalid_research_plan')
        # An optional procedure choice never fails the consultation: unknown slugs are dropped and disclosed.
        offered = {item['slug'] for item in state.get('numeric_basis', {}).get('playbook_catalog', {}).get('items', {}).values()}
        chosen = [slug for slug in dict.fromkeys(result.playbooks) if slug in offered]
        if len(chosen) < len(set(result.playbooks)):
            state['limitations'] = [*state['limitations'], '승인된 플레이북 목록에 없는 절차는 사용하지 않았습니다.']
        result.playbooks = chosen
        if chosen:
            state['playbook_slugs'] = chosen
            apply_playbooks(state)
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

    def clarify(state):
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

    def dispatch(state):
        done = {key for key, value in state.get('results', {}).items() if value is not None}
        tasks = state['plan']['tasks']
        ready = [t for t in tasks if t['id'] not in done and set(t['depends_on']) <= done]
        if not ready:
            return 'analyze'
        return [Send('research', {'task': task, 'query': state['query'], 'sources': state.get('sources', []),
            'execution_id': f"{task['id']}:{state['replans']}:{signature(task)}"}) for task in ready]

    async def research(state):
        task = ResearchTask.model_validate(state['task'])
        await progress('research_started', task_id=task.id, tool=task.tool)
        assembler.baseline_snapshot_id = None
        # Calls share an ORM Session, so ContextAssembler serializes its DB access.
        with tracing_context(enabled=False):
            result = await tools[task.tool].ainvoke({'query': task.query}, config={'callbacks': []})
        await progress('research_finished', task_id=task.id, tool=task.tool)
        return {'results': {task.id: result}, 'tool_executions': {state['execution_id']: True}}

    def collected(state):
        sources = [r['snapshot_id'] for r in state['results'].values() if r is not None]
        return {'tool_calls': len(state.get('tool_executions', {})),
                'sources': list(dict.fromkeys([*state['sources'], *sources]))}

    async def analyze(state):
        await progress('analyzing', alternatives=len(state['plan']['scenarios']))
        # Every alternative receives the same explicit evidence baseline and its own assumptions.
        if not state.get('baseline_snapshot_id') and state['plan']['scenarios']:
            _, baseline = await assembler.assemble(state['query'], sources=state['sources'])
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
            result = await call(input_state, '이 대안 하나만 검토하세요. 다른 대안의 임시 가정을 섞지 마세요. '
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

    async def review(state):
        await progress('reviewing', model_calls=state['model_calls'])
        if state['model_calls'] >= limits(state)[0] - 1:
            return state
        result = await call(state, '근거·인용·필수 제약의 누락과 상충을 검토하세요. '
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

    async def finish(state):
        await progress('answering', model_calls=state['model_calls'])
        if state.get('single_response'):
            answer = await call(state, '')
            return {**state, 'answer': answer}
        if state['model_calls'] >= limits(state)[0]:
            return {**state, 'answer': '분석 한도에 도달했습니다. 저장된 조사 결과와 대안을 확인하고 필요한 조건을 보완해 주세요.',
                    'limitations': [*state['limitations'], '모델 호출 한도에 도달하여 최종 답변을 생성하지 않았습니다.']}
        try:
            result = await call(state, '사용자 질문에 근거를 바탕으로 답하세요. 행동은 승인 대기 제안만 '
                '만들고 기억은 사용자가 확인할 후보만 만드세요. 이번 대안의 가정을 장기 기억으로 제안하지 마세요. '
                '답변 코드 블록에 행동·기억 데이터를 넣지 마세요.', FinalAnswer,
                {'plan': state.get('plan'), 'research': state['results'], 'scenarios': state['scenarios'],
                 'limitations': state['limitations'], 'response': state.get('response')})
        except AdvisorError as exc:
            if exc.provider_code != 'analysis_budget_exceeded':
                raise
            return {**state, 'answer': '분석 한도에 도달했습니다. 저장된 조사 결과와 대안을 확인해 주세요.',
                    'limitations': [*state['limitations'], '최종 답변 수정 요청 전에 호출 한도에 도달했습니다.']}
        from app.modules.context.types import payload_citations
        from app.modules.database.model import ContextSnapshot
        snapshot = session.get(ContextSnapshot, state['snapshot_id']) if session is not None else None
        if snapshot is not None:
            refs = {citation['ref'] for citation in payload_citations(snapshot.payload)}
            cited = set(re.findall(r'\[(document_chunks:\d+)\]', result.answer))
            if cited - refs:
                raise AdvisorError('답변의 문서 인용 근거를 확인할 수 없습니다.', provider_code='invalid_citation')
        answer, withheld = validated_numeric_answer(result.answer, {
            'current_data': snapshot.payload.get('data', {}) if snapshot is not None else state.get('numeric_basis', {}),
            'query': state['query'], 'research': [r.get('data') for r in state['results'].values() if r is not None],
            'assumptions': [scenario.get('assumptions', {}) for scenario in state['scenarios']],
            'calculations': [scenario.get('results', {}).get('server_calculations', {}) for scenario in state['scenarios']]})
        if snapshot is not None:
            from app.modules.advisor.runtime.web import validate_web_links
            validate_web_links(answer, snapshot.payload)
        numeric_limits = ['서버 근거·명시적 가정에서 확인되지 않은 수치 설명을 생략했습니다.'] if withheld else []
        return {**state, 'answer': answer, 'proposals': [p.model_dump() for p in result.proposals],
                'memories': [m.model_dump() for m in result.memories],
                'limitations': [*state['limitations'], *numeric_limits]}

    async def web_research(state):
        await progress('web_searching')
        snapshot_id = await assembler.search_web()
        return {'web_snapshot_id': snapshot_id, 'sources': [*state['sources'], snapshot_id],
                'tool_calls': state['tool_calls'] + 1, 'tool_executions': {'web_search': True},
                'single_response': False}

    def route_analysis(state):
        return 'finish' if state.get('single_response') or not needs_analysis(state) else 'summarize'

    graph = StateGraph(ConsultationState)
    for name, node in [('summarize', summarize), ('plan', plan), ('clarify', clarify), ('research', research),
                       ('collected', collected), ('analyze', analyze), ('review', review), ('finish', finish),
                       ('web_search', web_research)]:
        graph.add_node(name, node)
    graph.add_conditional_edges(START, lambda state: 'web_search' if getattr(options, 'web_search', False) else route_analysis(state))
    graph.add_conditional_edges('web_search', route_analysis)
    graph.add_edge('summarize', 'plan')
    graph.add_conditional_edges('plan', lambda state: 'clarify' if state.get('clarification') else 'collected')
    graph.add_edge('clarify', 'plan')
    graph.add_conditional_edges('collected', dispatch)
    graph.add_edge('research', 'collected')
    graph.add_conditional_edges('analyze', lambda state: 'review' if state.get('depth') == 'deep' else 'finish')
    graph.add_conditional_edges('review', lambda state: 'plan' if state.get('needs_replan') else
                                'collected' if pending_tasks(state) else 'finish')
    graph.add_edge('finish', END)
    return graph.compile(checkpointer=checkpointer, store=getattr(assembler, 'memory_store', None))
