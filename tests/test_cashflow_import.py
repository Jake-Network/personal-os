"""Household ledger CSV import: column mapping, Decimal parsing, re-import identity and rules. Synthetic data only."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.modules.database.model import AuditLog, CashflowCategoryRule, CashflowEntry
from app.modules.finance import cashflow_import
from app.schema.cashflow_import_schema import CashflowCategoryRuleCreate, CashflowImportInput

CARD = (
    "거래일,가맹점,이용금액,분류\n"
    "2026.08.03,Synthetic Mart,\"12,300\",식비\n"
    "2026.08.03,Synthetic Mart,\"12,300\",\n"
    "2026-08-15,SYNTHETIC CAFE 강남,4500원,\n"
    "20260820,Synthetic Refund,-2000,\n"
)
CARD_MAPPING = {"date": "거래일", "amount": "이용금액", "description": "가맹점", "category": "분류"}


def body(text=CARD, mapping=CARD_MAPPING, **extra):
    return CashflowImportInput.model_validate(
        {"source_id": "synthetic-card", "csv_text": text, "mapping": mapping, "amount_sign": "positive_is_expense", **extra})


def entries(session):
    return list(session.scalars(select(CashflowEntry).order_by(CashflowEntry.id)))


def test_preview_parses_bank_formats_without_saving(session):
    result = cashflow_import.public_preview(session, body())
    rows = result["rows"]
    assert [r["occurred_on"] for r in rows] == [date(2026, 8, 3), date(2026, 8, 3), date(2026, 8, 15), date(2026, 8, 20)]
    assert [r["amount"] for r in rows] == [Decimal("12300"), Decimal("12300"), Decimal("4500"), Decimal("2000")]
    assert [r["kind"] for r in rows] == ["expense", "expense", "expense", "income"]
    assert rows[0]["category"] == "식비" and rows[0]["category_source"] == "csv"
    assert all(r["status"] == "new" and not r["issues"] and r["currency"] == "KRW" for r in rows)
    assert "_ref" not in rows[0]
    assert result["coverage"]["partial_months"] == ["2026-08"]
    assert entries(session) == []


def test_import_is_idempotent_and_keeps_same_day_repeats(session):
    first = cashflow_import.commit(session, body())
    assert first["imported"] == 4
    stored = entries(session)
    assert [(e.kind, e.amount, e.currency) for e in stored][:2] == [("expense", Decimal("12300"), "KRW")] * 2
    assert session.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == "data.import")) == 1

    # An overlapping later export: the same four rows plus one new one.
    again = cashflow_import.commit(session, body(CARD + "2026-08-31,Synthetic Gym,50000,\n"))
    assert (again["imported"], again["existing"]) == (1, 4)
    assert len(entries(session)) == 5


def test_deleted_entry_is_not_brought_back(session):
    cashflow_import.commit(session, body())
    session.delete(entries(session)[2])
    session.commit()
    result = cashflow_import.commit(session, body())
    assert (result["imported"], result["deleted"]) == (0, 1)
    assert len(entries(session)) == 3


def test_issue_blocks_import_until_the_row_is_excluded(session):
    text = CARD + "날짜없음,Synthetic Broken,1000,\n2026-08-21,Synthetic Zero,0,\n"
    preview = cashflow_import.public_preview(session, body(text))
    assert [r["issues"] for r in preview["rows"][4:]] == [["날짜를 읽을 수 없습니다"], ["금액이 없거나 0입니다"]]
    with pytest.raises(ValueError):
        cashflow_import.commit(session, body(text))
    assert entries(session) == []
    result = cashflow_import.commit(session, body(text, exclude_rows=[5, 6]))
    assert (result["imported"], result["excluded"]) == (4, 2)


def test_excluding_a_row_does_not_shift_other_identities(session):
    cashflow_import.commit(session, body(exclude_rows=[1]))
    result = cashflow_import.commit(session, body())
    # Row 2 is the second identical purchase; it was imported first time and stays "existing".
    assert (result["imported"], result["existing"]) == (1, 3)


def test_debit_credit_columns_and_precision_limits(session):
    text = ("일자,적요,출금,입금\n"
            "2026-09-01,Synthetic Salary,0,3000000\n"
            "2026-09-02,Synthetic Rent,800000,\n"
            "2026-09-03,Synthetic Both,10,10\n"
            "2026-09-04,Synthetic Precise,1.23456,\n"
            "2026-09-05,Synthetic Huge,99999999999999999,\n")
    mapping = {"date": "일자", "description": "적요", "debit": "출금", "credit": "입금"}
    rows = cashflow_import.public_preview(session, body(text, mapping))["rows"]
    assert [(r["kind"], r["amount"]) for r in rows[:2]] == [("income", Decimal("3000000")), ("expense", Decimal("800000"))]
    assert rows[2]["issues"] == ["출금과 입금이 한 행에 함께 있습니다"]
    assert rows[3]["issues"] == ["금액은 소수 넷째 자리까지만 저장합니다"]
    assert rows[4]["issues"] == ["금액이 저장 한도를 넘습니다"]


def test_preamble_tab_delimiter_and_missing_column(session):
    text = "Synthetic Bank statement\n조회기간 2026-09\n일자\t적요\t금액\n2026-09-01\tSynthetic Coffee\t-4500\n"
    mapping = {"date": "일자", "description": "적요", "amount": "금액"}
    preview = cashflow_import.public_preview(session, CashflowImportInput.model_validate(
        {"source_id": "synthetic-bank", "csv_text": text, "mapping": mapping, "skip_rows": 2}))
    assert [(r["kind"], r["amount"]) for r in preview["rows"]] == [("expense", Decimal("4500"))]
    with pytest.raises(ValueError, match="없는 열"):
        cashflow_import.public_preview(session, body(mapping={**CARD_MAPPING, "description": "상호"}))


def test_possible_duplicate_of_a_manual_entry_is_flagged_not_dropped(session):
    session.add(CashflowEntry(occurred_on=date(2026, 8, 15), kind="expense", amount=Decimal("4500.0000"), currency="KRW"))
    session.commit()
    rows = cashflow_import.public_preview(session, body())["rows"]
    assert [r["possible_duplicate"] for r in rows] == [False, False, True, False]
    assert rows[2]["status"] == "new"


def test_rules_suggest_and_remembered_overrides_become_rules(session):
    cashflow_import.create_rule(session, CashflowCategoryRuleCreate(match_text="cafe", match_kind="contains", category="카페"))
    cashflow_import.create_rule(session, CashflowCategoryRuleCreate(match_text="Synthetic Mart", category="장보기"))
    rows = cashflow_import.public_preview(session, body())["rows"]
    # The CSV category wins over a rule; an empty CSV category falls back to rules.
    assert [(r["category"], r["category_source"]) for r in rows] == [
        ("식비", "csv"), ("장보기", "rule"), ("카페", "rule"), (None, None)]

    result = cashflow_import.commit(session, body(category_overrides={"4": "환불"}, remember_rows=[4]))
    assert result["rules_created"] == 1
    assert entries(session)[3].category == "환불"
    rule = session.scalar(select(CashflowCategoryRule).where(CashflowCategoryRule.category == "환불"))
    assert (rule.match_kind, rule.match_text) == ("equals", "synthetic refund")
    # Rules suggest only: existing entries keep the category they were stored with.
    cashflow_import.create_rule(session, CashflowCategoryRuleCreate(match_text="Synthetic Refund", category="기타"))
    assert entries(session)[3].category == "환불"


def test_imported_partial_month_does_not_make_runway_available(session):
    """Importing two months leaves the three-full-month expense rule in charge."""
    from app.modules.dashboard.dashboard_manager import dashboard_manager

    text = "date,desc,amount\n2026-08-05,Synthetic,-100\n2026-09-05,Synthetic,-100\n"
    cashflow_import.commit(session, CashflowImportInput.model_validate(
        {"source_id": "synthetic", "csv_text": text, "mapping": {"date": "date", "description": "desc", "amount": "amount"}}))
    summary = dashboard_manager.summary(session, datetime(2026, 10, 20, 3, tzinfo=UTC))
    expense = summary["data"]["get_cashflow_summary"]["monthly_expense"]
    assert expense["available"] is False and expense["reason"] == "insufficient_coverage"


def test_http_contract_and_presets(client):
    payload = {"source_id": "synthetic-card", "csv_text": CARD, "mapping": CARD_MAPPING, "amount_sign": "positive_is_expense"}
    preview = client.post("/api/finance/cashflow/import/preview", json=payload)
    assert preview.status_code == 200
    assert preview.json()["rows"][0]["amount"] == "12300"
    assert client.post("/api/finance/cashflow/import", json=payload).json()["imported"] == 4
    bad = client.post("/api/finance/cashflow/import/preview", json={**payload, "mapping": {"date": "거래일"}})
    assert bad.status_code == 422

    preset = {"name": "Synthetic card", "mapping": CARD_MAPPING, "amount_sign": "positive_is_expense", "skip_rows": 0}
    assert client.put("/api/finance/cashflow/import/presets", json={"presets": [preset, preset]}).status_code == 422
    assert client.put("/api/finance/cashflow/import/presets", json={"presets": [preset]}).status_code == 200
    assert client.get("/api/finance/cashflow/import/presets").json()["presets"][0]["name"] == "Synthetic card"

    rule = client.post("/api/finance/cashflow/category-rules", json={"match_text": "Cafe", "match_kind": "contains", "category": "카페"})
    assert rule.status_code == 201 and rule.json()["match_text"] == "cafe"
    assert client.delete(f"/api/finance/cashflow/category-rules/{rule.json()['id']}").status_code == 204
    assert client.get("/api/finance/cashflow/category-rules").json() == []
