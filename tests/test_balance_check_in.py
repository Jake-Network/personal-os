"""Bulk balance check-in: per-account version checks and append-only history. Synthetic data only."""

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.modules.database.model import Account, ManualValueChange
from app.modules.finance.clock import local_today


def account(session, name, balance, days_old=10):
    row = Account(name=name, kind="checking", currency="KRW", balance=Decimal(balance),
                  balance_as_of=local_today() - timedelta(days=days_old), is_liquid=True)
    session.add(row)
    session.commit()
    return row


def test_updates_confirms_and_refuses_each_account_on_its_own(client, session):
    a, b, c = account(session, "합성 A", "100"), account(session, "합성 B", "200"), account(session, "합성 C", "300")
    stale_version = c.updated_at.isoformat()
    c.balance = Decimal("350")
    session.commit()
    response = client.post("/api/finance/balance-check-in", json={"items": [
        {"account_id": a.id, "expected_version": a.updated_at.isoformat(), "balance": "150.25"},
        {"account_id": b.id, "expected_version": b.updated_at.isoformat(), "balance": None},
        {"account_id": c.id, "expected_version": stale_version, "balance": "999"},
        {"account_id": 999999, "expected_version": stale_version},
    ]})
    assert response.status_code == 200, response.text
    assert [r["status"] for r in response.json()] == ["updated", "confirmed", "conflict", "not_found"]
    session.expire_all()
    today = local_today()
    assert (session.get(Account, a.id).balance, session.get(Account, a.id).balance_as_of) == (Decimal("150.25"), today)
    assert (session.get(Account, b.id).balance, session.get(Account, b.id).balance_as_of) == (Decimal("200"), today)
    assert session.get(Account, c.id).balance == Decimal("350")
    history = session.scalars(select(ManualValueChange).where(ManualValueChange.record_id == a.id)
                              .order_by(ManualValueChange.id)).all()
    assert [(h.change_kind, h.new_value) for h in history][-1] == ("update", Decimal("150.25"))
    assert any(h.change_kind == "baseline" for h in history)


def test_duplicate_accounts_are_rejected(client, session):
    a = account(session, "합성 A", "100")
    item = {"account_id": a.id, "expected_version": a.updated_at.isoformat(), "balance": "1"}
    assert client.post("/api/finance/balance-check-in", json={"items": [item, item]}).status_code == 422
    session.expire_all()
    assert session.get(Account, a.id).balance == Decimal("100")
