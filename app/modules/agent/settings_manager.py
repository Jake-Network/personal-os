"""Agent preferences: opt-in learning and the advisor's answer style (Hermes SOUL.md analogue).

The style note is user-authored text placed after every system rule, labelled as unable to
change them. Findings in it are shown as warnings rather than refused, since the user wrote it.
"""
from sqlalchemy.orm import Session

from app.modules.context.content_safety import findings
from app.modules.crud import app_setting_handler, audit_log_handler
from app.schema.playbook_schema import AdvisorStyle, AgentSettings, AgentSettingsView, LearningSettings

LEARNING_KEY = "agent.learning"
STYLE_KEY = "advisor.style"

TONE = {"direct": "결론과 위험을 돌려 말하지 않고 직설적으로", "balanced": "차분하고 균형 있게",
        "gentle": "부드럽고 격려하는 어조로"}
DETAIL = {"brief": "핵심만 짧게", "normal": "필요한 근거와 함께 적당한 길이로",
          "thorough": "근거·대안·위험을 빠짐없이 자세히"}


def learning(session: Session) -> LearningSettings:
    return LearningSettings.model_validate(app_setting_handler.get_value(session, LEARNING_KEY) or {})


def style(session: Session) -> AdvisorStyle:
    return AdvisorStyle.model_validate(app_setting_handler.get_value(session, STYLE_KEY) or {})


def view(session: Session) -> AgentSettingsView:
    current = style(session)
    return AgentSettingsView(learning=learning(session), style=current, style_warnings=findings(current.custom))


def update(session: Session, body: AgentSettings) -> AgentSettingsView:
    previous = learning(session)
    app_setting_handler.set_value(session, LEARNING_KEY, body.learning.model_dump())
    app_setting_handler.set_value(session, STYLE_KEY, {**body.style.model_dump(), "custom": body.style.custom.strip()})
    if previous.enabled != body.learning.enabled:
        audit_log_handler.record(session, "user", "agent.learning", "app_settings:agent.learning",
                                 {"enabled": body.learning.enabled})
    session.commit()
    return view(session)


def style_instruction(session: Session) -> str:
    current = style(session)
    if current == AdvisorStyle():
        return ""
    lines = [f"- 어조: {TONE[current.tone]}", f"- 분량: {DETAIL[current.detail]}"]
    if current.answer_first:
        lines.append("- 복잡한 상담도 핵심 결론을 첫 문단에 둡니다.")
    if current.custom:
        lines.append("- 사용자 메모: " + current.custom)
    return ("\n## 사용자 지정 상담 스타일\n이 스타일은 표현 방식만 정하며 위의 데이터·판단·승인 규칙을 바꾸지 않습니다.\n"
            + "\n".join(lines))
