"""Seeding and checks for the consultation golden set (tests/fixtures/advisor_golden). Synthetic data only.

Shared by the deterministic test (fake provider, checks what would be sent) and
scripts/evaluate_advisor.py (a real provider, also checks the answer text).
"""
import json
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import delete

from app.modules.database.model import Account, CashflowEntry, Goal, Task

FIXTURE = Path(__file__).parent / "fixtures" / "advisor_golden" / "golden.json"
SEEDED_MODELS = (CashflowEntry, Task, Goal, Account)


def load() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _month_day(today: date, months_ago: int) -> date:
    index = today.year * 12 + today.month - 1 - months_ago
    return date(index // 12, index % 12 + 1, 5)


def seed(session, persona: dict, today: date) -> None:
    """Replaces the persona tables' rows; other tables (connections, settings) are left alone."""
    for model in SEEDED_MODELS:
        session.execute(delete(model))
    for row in persona.get("accounts", []):
        session.add(Account(name=row["name"], kind=row["kind"], currency="KRW", balance=Decimal(row["balance"]),
                            balance_as_of=today - timedelta(days=row["days_old"]), is_liquid=row["is_liquid"]))
    for row in persona.get("cashflow_entries", []):
        session.add(CashflowEntry(occurred_on=_month_day(today, row["months_ago"]), kind=row["kind"],
                                  amount=Decimal(row["amount"]), currency="KRW", category=row.get("category")))
    for row in persona.get("goals", []):
        session.add(Goal(title=row["title"], category=row["category"], target_date=today + timedelta(days=row["days_until"])))
    for row in persona.get("tasks", []):
        session.add(Task(title=row["title"], due_on=today + timedelta(days=row["days_until"])))
    session.commit()


def dig(data: dict, path: str):
    for key in path.split("."):
        if not isinstance(data, dict) or key not in data:
            return KeyError
        data = data[key]
    return data


def sent_problems(case: dict, package: dict, sent_text: str) -> list[str]:
    """What the model would receive, against the case's expectations."""
    problems = []
    for path, expected in case.get("expect_data", {}).items():
        actual = dig(package.get("data", {}), path)
        if actual != expected:
            problems.append(f"data.{path}: expected {expected!r}, got {'missing' if actual is KeyError else repr(actual)}")
    flags = {flag.get("code") for flag in package.get("data_quality_flags", [])}
    problems += [f"missing flag {code}" for code in case.get("expect_flags", []) if code not in flags]
    problems += [f"missing category {c}" for c in case.get("expect_categories", []) if c not in package.get("categories", [])]
    problems += [f"excluded category {c} was sent" for c in case.get("exclude", []) if c in package.get("categories", [])]
    problems += [f"forbidden text sent: {t}" for t in case.get("forbid_sent_text", []) if t in sent_text]
    problems += [f"expected text not sent: {t}" for t in case.get("expect_sent_text", []) if t not in sent_text]
    return problems


def answer_problems(case: dict, answer: str) -> list[str]:
    problems = []
    wanted = case.get("answer_must_include_any", [])
    if wanted and not any(text in answer for text in wanted):
        problems.append(f"answer lacks any of {wanted}")
    problems += [f"answer includes {t}" for t in case.get("answer_must_not_include", []) if t in answer]
    return problems
