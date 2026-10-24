"""Withhold sensitive numeric claims that the supplied evidence does not contain."""
import re
from decimal import Decimal, InvalidOperation


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
