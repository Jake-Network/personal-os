"""Consultation graph state and the query predicates that route it."""
import re
from typing import Annotated, TypedDict


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
    data_operations: list[dict]
    data_command_handled: bool
    pending_data_commands: dict | None
    playbook_slugs: list[str]
    catalog_refs: list[dict]


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
                  previous_analysis=False, explicit_scenario=False, pending_data_commands=None):
    selected = scenarios or ([selected_scenario] if selected_scenario else [])
    if not explicit_scenario and not scenario_followup(query):
        selected = []
    sources = list(dict.fromkeys(item['source_snapshot_id'] for item in selected if item.get('source_snapshot_id')))
    return {'query': query, 'depth': depth, 'single_response': single_response,
            'pending_data_commands': pending_data_commands,
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
    # Recalling an earlier consultation needs a planned search_sessions call, not just recent turns.
    past_session = re.search(r'지난\s*(?:번|상담|대화)|예전에|이전\s*(?:상담|대화)|과거\s*(?:상담|대화)|'
                             r'전에\s*(?:상담|얘기|이야기|말했|물어|물었)', query)
    financial_calculation = re.search(r'생활비|지출|소득|잔고|현금|만원|런웨이', query) and re.search(r'버틸|계산|런웨이|면.{0,30}얼마', query)
    time_feasibility = re.search(r'시간|수면|근무', query) and re.search(r'가능|여유|할\s*수|남는|남을|계산|부족', query)
    quantitative_change = (re.search(r'생활비|지출|소득|수입|현금|잔고|근무|시간|수면', query)
        and re.search(r'\d', query)
        and re.search(r'바꾸면|줄이면|늘리면|쓴다면|벌면|가능|충분|부족|남을|남는', query))
    multiple = len(re.findall(r'[?？]', query)) > 1 and bool(constraints)
    return bool(explicit or past_session or (comparison and constraints) or financial_calculation or time_feasibility
                or quantitative_change or multiple)
