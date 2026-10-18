"""Web evidence stays separate from private domain facts and executable instructions."""
import copy
import hashlib
import json
import re
from datetime import UTC, datetime
from uuid import uuid4

from app.modules.llm.errors import AdvisorError


class WebResearchError(AdvisorError):
    code = 'web_research_error'

    def __init__(self, message, provider_code):
        super().__init__(message, provider_code=provider_code)
        self.user_message = message


def save_web_snapshot(session, conversation_id, result):
    from app.modules.context.snapshots import content_hash
    from app.modules.database.model import ContextSnapshot

    data = copy.deepcopy(result)
    flags = [{'code': code, 'category': 'web'} for code in data.pop('data_quality_flags', [])]
    for page in data['pages']:
        page['ref'] = 'web:' + hashlib.sha256((page['url'] + page['content_hash']).encode()).hexdigest()[:20]
        page['untrusted_external_content'] = True
    snapshot_id = str(uuid4())
    payload = {'context_snapshot_id': snapshot_id, 'generated_at': datetime.now(UTC).isoformat(),
               'web_research_only': True,
               'data': {'web_search': data}, 'data_quality_flags': flags}
    row = ContextSnapshot(id=snapshot_id, conversation_id=conversation_id, context_categories=[],
        excluded_categories=[], record_references=[], source_updated_at={}, data_quality_flags=flags,
        payload=payload, content_hash=content_hash(payload))
    session.add(row)
    session.flush()
    return snapshot_id


def merge_web_sources(payload, snapshots, limit):
    """Merge bounded selected excerpts, never raw pages, before final request budgeting."""
    pages, flags, query = {}, [], None
    current_refs = {page['ref'] for snapshot in snapshots if snapshot.payload.get('web_research_only')
                    for page in snapshot.payload.get('data', {}).get('web_search', {}).get('pages', [])}
    for snapshot in snapshots:
        section = snapshot.payload.get('data', {}).get('web_search')
        if section is None:
            continue
        query = section['query']
        for page in section['pages']:
            pages[page['ref']] = copy.deepcopy(page)
            pages[page['ref']]['historical'] = page['ref'] not in current_refs
        flags.extend(flag for flag in snapshot.data_quality_flags if flag.get('category') == 'web')
    if query is None:
        return payload
    payload = copy.deepcopy(payload)
    flags = list({json.dumps(flag, sort_keys=True): flag for flag in
                 [*payload.get('data_quality_flags', []), *flags]}.values())
    payload['data_quality_flags'] = flags
    payload['data']['web_search'] = {'query': query, 'pages': list(pages.values())}
    # Trim web excerpts to the remaining room without dropping personal constraints.
    def size():
        return len(json.dumps(payload, ensure_ascii=False, separators=(',', ':')))
    trimmed = False
    while size() > limit:
        candidates = [(len(text), page, index) for page in payload['data']['web_search']['pages']
                      for index, text in enumerate(page['excerpts']) if len(text) > 240]
        if not candidates:
            raise WebResearchError('웹 근거와 필수 데이터가 컨텍스트 예산을 초과했습니다. 질문 범위를 줄여 주세요.',
                                   'context_budget_exceeded')
        _, page, index = max(candidates, key=lambda item: item[0])
        page['excerpts'][index] = page['excerpts'][index][:max(240, len(page['excerpts'][index]) // 2)]
        if not trimmed:
            flags.append({'code': 'web_excerpts_trimmed', 'category': 'web',
                          'detail': '컨텍스트 예산에 맞춰 웹 본문의 선택된 발췌 일부를 줄였습니다.'})
            trimmed = True
    return payload


def validate_web_links(answer, payload):
    section = payload.get('data', {}).get('web_search')
    if section is None:
        return
    pages = section.get('pages', [])
    allowed = {page['url'] for page in pages}
    # Match the exact collected URL, including balanced parentheses in URLs.
    cited = [url for url in allowed if f']({url})' in answer or f'](<{url}>)' in answer]
    for match in re.finditer(r'https?://', answer):
        if not any(answer.startswith(url, match.start()) and
                   (match.start() + len(url) == len(answer) or
                    answer[match.start() + len(url)] in ' \n\t)>]') for url in allowed):
            raise WebResearchError('답변의 웹 인용이 수집한 본문 근거와 일치하지 않습니다.', 'invalid_web_citation')
    if re.search(r'\]\((?!https?://|<https?://)[^)]*://', answer):
        raise WebResearchError('답변의 웹 인용이 수집한 본문 근거와 일치하지 않습니다.', 'invalid_web_citation')
    if pages and not cited:
        raise WebResearchError('웹 근거를 사용한 답변에 출처 링크가 없습니다. 다시 시도하세요.', 'missing_web_citation')
