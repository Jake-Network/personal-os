"""Final answer with citation, numeric and web-link verification."""
import re

from app.modules.advisor.runtime.nodes.base import limits
from app.modules.advisor.runtime.numeric_guard import validated_numeric_answer
from app.modules.advisor.runtime.schemas import FinalAnswer
from app.modules.advisor.runtime.web import validate_web_links
from app.modules.context.types import payload_citations
from app.modules.database.model import ContextSnapshot
from app.modules.llm.errors import AdvisorError


async def finish(ctx, state):
    await ctx.progress('answering', model_calls=state['model_calls'])
    if state.get('single_response'):
        answer = await ctx.call(state, '')
        return {**state, 'answer': answer}
    if state['model_calls'] >= limits(state)[0]:
        return {**state, 'answer': '분석 한도에 도달했습니다. 저장된 조사 결과와 대안을 확인하고 필요한 조건을 보완해 주세요.',
                'limitations': [*state['limitations'], '모델 호출 한도에 도달하여 최종 답변을 생성하지 않았습니다.']}
    try:
        result = await ctx.call(state, '사용자 질문에 근거를 바탕으로 답하세요. Context Package의 advisor_data_operations는 '
            '서버가 이미 수행한 데이터 작업의 결과입니다. status=saved인 작업만 저장·수정·삭제 완료로 설명하고, '
            'needs_input/failed는 필요한 정보나 실패를 알려주세요. read는 조회 결과이며 저장 성공이 아닙니다. '
            '이미 처리한 작업을 다시 승인 대기 제안으로 만들지 마세요. 이 실행에서 수행되지 않은 행동은 승인 대기 제안만 '
            '만들고 기억은 사용자가 확인할 후보만 만드세요. 이번 대안의 가정을 장기 기억으로 제안하지 마세요. '
            '답변 코드 블록에 행동·기억 데이터를 넣지 마세요.', FinalAnswer,
            {'plan': state.get('plan'), 'research': state['results'], 'scenarios': state['scenarios'],
             'limitations': state['limitations'], 'response': state.get('response')})
    except AdvisorError as exc:
        if exc.provider_code != 'analysis_budget_exceeded':
            raise
        return {**state, 'answer': '분석 한도에 도달했습니다. 저장된 조사 결과와 대안을 확인해 주세요.',
                'limitations': [*state['limitations'], '최종 답변 수정 요청 전에 호출 한도에 도달했습니다.']}
    snapshot = ctx.session.get(ContextSnapshot, state['snapshot_id']) if ctx.session is not None else None
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
        validate_web_links(answer, snapshot.payload)
    numeric_limits = ['서버 근거·명시적 가정에서 확인되지 않은 수치 설명을 생략했습니다.'] if withheld else []
    return {**state, 'answer': answer, 'proposals': [p.model_dump() for p in result.proposals],
            'memories': [m.model_dump() for m in result.memories],
            'limitations': [*state['limitations'], *numeric_limits]}
