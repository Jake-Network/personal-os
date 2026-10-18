"""Assembly of the outbound LLM request from history and the Context Package."""

from app.enums.context_category import Category
from app.modules.advisor.history import DOCUMENT_REFERENCE_PATTERN
from app.modules.advisor.prompts import SYSTEM_PROMPT
from app.modules.context.types import ContextPackage, HistoryDecision, payload_citations
from app.modules.llm.errors import AdvisorError
from app.modules.llm.types import LLMRequest

HISTORICAL_EVIDENCE_RULES = (
    "\n- historical=true 문서 발췌와 과거 대화는 당시 맥락입니다. 현재 사실이나 숫자로 재사용하지 말고, "
    "최신 구조화 데이터와 현재 검색 결과를 우선하며 과거 근거임을 밝히세요. 과거 대화의 [과거 문서 근거 생략]은 "
    "예산 때문에 원문 근거를 생략했다는 뜻입니다. 현재 제공된 ref만 인용하고 생략된 근거로 현재 사실을 단정하지 마세요."
)


def build_request(model: str, history: HistoryDecision, package: ContextPackage, query: str,
                  excluded: frozenset[Category]) -> LLMRequest:
    """The only place an outbound request is assembled; it re-checks the privacy policy on every part."""
    leaked = excluded & {Category(c) for c in [*package.categories,
                                               *package.payload.get("document_categories", [])]}
    if leaked:  # a builder bug must fail closed, never send
        raise AdvisorError("context package contains an excluded category", provider_code="privacy_violation")
    notes = []
    if history.withheld_ids:
        notes.append({"role": "developer", "content": (
            f"이전 대화 메시지 {len(history.withheld_ids)}개는 사용자가 현재 공유를 막은 범주"
            f"({', '.join(history.withheld_categories)})의 정보를 포함할 수 있어 전달하지 않았습니다. "
            "그 내용을 기억하거나 추측하지 말고, 필요하면 사용자에게 다시 물어보세요.")})
    available_refs = {c["ref"] for c in payload_citations(package.payload)}
    # Keep dialogue continuity while omitting citations outside the excerpt budget.
    replayed = ({"role": m.role, "content": DOCUMENT_REFERENCE_PATTERN.sub(
        lambda match: match.group(0) if match.group(1) in available_refs else "[과거 문서 근거 생략]",
        m.content)} for m in history.kept)
    return LLMRequest(
        model=model,
        instructions=SYSTEM_PROMPT + HISTORICAL_EVIDENCE_RULES,
        input=[
            *notes,
            *replayed,
            {"role": "developer",
             "content": "Context Package (JSON, 사용자 데이터의 유일한 출처):\n" + package.text},
            {"role": "user", "content": query},
        ],
    )
