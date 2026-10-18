"""Per-category sharing control (PRD §3.3, §7.5, AC-19)."""

from sqlalchemy.orm import Session

from app.enums.context_category import Category
from app.modules.crud import app_setting_handler, audit_log_handler

PRIVACY_KEY = "privacy.excluded_categories"


class PrivacyManager:
    def get_excluded(self, session: Session) -> frozenset[Category]:
        names = (app_setting_handler.get_value(session, PRIVACY_KEY) or {}).get("categories", [])
        return frozenset(Category(n) for n in names if n in Category._value2member_map_)

    def set_excluded(self, session: Session, categories: list[Category]) -> frozenset[Category]:
        names = sorted({c.value for c in categories})
        app_setting_handler.set_value(session, PRIVACY_KEY, {"categories": names})
        audit_log_handler.record(session, "user", "privacy.update", detail={"excluded_categories": names})
        session.commit()
        return frozenset(Category(n) for n in names)


privacy_manager = PrivacyManager()
