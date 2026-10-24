"""Checks for text that will be stored and later placed in a model request.

Memories, playbooks and the user's style note are injected into future prompts. Text a
model proposed is blocked on any finding; text the user wrote is kept with a visible
warning, since the user is its author. Matching is conservative pattern detection, not
a guarantee that unflagged text is safe.
"""
import re
import unicodedata

INJECTION = re.compile(
    r"(?:ignore|disregard|forget|override)\s+(?:all\s+|any\s+|the\s+)?(?:previous|prior|above|earlier|system)\s+"
    r"(?:instructions?|rules?|prompts?|messages?)|"
    r"(?:이전|위의?|앞의?|기존|시스템)\s*(?:의\s*)?(?:지시|지침|규칙|명령|프롬프트)\S*\s*(?:을|를|은|는)?\s*(?:모두\s*)?(?:무시|잊|어기|따르지)|"
    r"\bsystem\s*prompt\b|\bdeveloper\s*(?:message|mode)\b|시스템\s*프롬프트|개발자\s*(?:메시지|모드)|"
    r"\byou\s+are\s+now\b|\bact\s+as\b|(?:너|당신)는\s*이제|역할을\s*(?:바꾸|변경)|"
    r"\b(?:call|run|execute|invoke)\s+(?:the\s+|a\s+)?(?:tool|function|command|shell)\b|"
    r"(?:도구|함수|명령|셸)(?:를|을)?\s*(?:호출|실행)|권한(?:을|를)?\s*(?:변경|부여|상승|올리)|"
    r"\b(?:send|upload|post|exfiltrate|forward)\b[^\n]{0,40}(?:https?://|\bto\s+\S+@)|외부로\s*(?:전송|보내|업로드)",
    re.IGNORECASE)
SECRET = re.compile(
    r"\bsk-[A-Za-z0-9_-]{16,}|\bbearer\s+[A-Za-z0-9._~+/-]{16,}|"
    r"\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|token|password|passwd|secret)\s*[=:]\s*\S{6,}|"
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----|\bgh[pousr]_[A-Za-z0-9]{20,}|\bAKIA[0-9A-Z]{16}\b",
    re.IGNORECASE)


def invisible_characters(text: str) -> bool:
    # Format characters (zero-width, bidi overrides, tag characters) hide instructions from review.
    return any(unicodedata.category(ch) == "Cf" for ch in text)


def findings(text: str) -> list[str]:
    """Stable finding codes for display; the matched text itself is never logged."""
    codes = []
    if INJECTION.search(text or ""):
        codes.append("prompt_injection")
    if SECRET.search(text or ""):
        codes.append("secret")
    if invisible_characters(text or ""):
        codes.append("invisible_unicode")
    return codes


LABELS = {
    "prompt_injection": "모델 지시·권한 변경으로 해석될 수 있는 문장",
    "secret": "키·토큰·비밀번호로 보이는 값",
    "invisible_unicode": "보이지 않는 제어 문자",
}
