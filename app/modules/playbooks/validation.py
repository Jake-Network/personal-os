"""Playbooks hold reusable procedure, never a person's records ("lessons, not logs").

A model proposal with any finding is refused; text the user writes is kept with the
findings shown as warnings. Generic thresholds ("6개월", "30% 이상") stay allowed.
"""
import re

from app.enums.context_category import ALL_CATEGORIES
from app.modules.context.content_safety import LABELS as SAFETY_LABELS, findings as safety_findings

SLUG = re.compile(r"^[a-z0-9가-힣][a-z0-9가-힣-]{1,39}$")
RECORD_REF = re.compile(r"\[[a-z_]+:\d+\]")
CURRENCY_AMOUNT = re.compile(
    r"\d[\d,.]*\s*(?:억|만|천)?\s*(?:원|달러|유로|엔)|[₩$€¥]\s*\d|\d[\d,.]*\s*(?:KRW|USD|EUR|JPY)\b", re.IGNORECASE)
CALENDAR_DATE = re.compile(r"\b\d{4}-\d{1,2}-\d{1,2}\b|\d{4}\s*년\s*\d{1,2}\s*월\s*\d{1,2}\s*일")

LABELS = {
    **SAFETY_LABELS,
    "record_reference": "개인 기록 참조([표:번호])",
    "personal_amount": "구체적인 금액",
    "specific_date": "특정 날짜(절차가 아닌 기록으로 보임)",
}


class PlaybookInvalid(ValueError):
    def __init__(self, codes: list[str]):
        self.codes = codes
        super().__init__("플레이북에 저장할 수 없는 내용이 있습니다: " + ", ".join(LABELS.get(c, c) for c in codes))


def normalize_triggers(triggers) -> list[str]:
    result = []
    for value in triggers or []:
        term = str(value).strip()
        if 2 <= len(term) <= 40 and term.casefold() not in {t.casefold() for t in result}:
            result.append(term)
    return result[:12]


def content_findings(title: str, summary: str, body: str, triggers: list[str]) -> list[str]:
    text = "\n".join([title, summary, body, *triggers])
    codes = safety_findings(text)
    if RECORD_REF.search(text):
        codes.append("record_reference")
    if CURRENCY_AMOUNT.search(text):
        codes.append("personal_amount")
    if CALENDAR_DATE.search(text):
        codes.append("specific_date")
    return codes


def validate(*, slug: str | None, title: str, summary: str, body: str, triggers, categories,
             source: str) -> tuple[dict, list[str]]:
    """Return normalized content and display warnings; raise for anything a model wrote."""
    if slug is not None and not SLUG.match(slug):
        raise ValueError("플레이북 이름은 2~40자의 소문자·숫자·한글·하이픈만 사용할 수 있습니다.")
    allowed = {str(c) for c in ALL_CATEGORIES}
    values = [str(c) for c in categories or []]
    if set(values) - allowed:
        raise ValueError("알 수 없는 범주입니다.")
    content = {"title": title.strip(), "summary": summary.strip(), "body": body.strip(),
               "triggers": normalize_triggers(triggers), "categories": sorted(set(values))}
    if not content["title"] or not content["summary"] or not content["body"]:
        raise ValueError("제목·요약·본문은 비울 수 없습니다.")
    codes = content_findings(content["title"], content["summary"], content["body"], content["triggers"])
    if codes and source != "user":
        raise PlaybookInvalid(codes)
    return content, codes
