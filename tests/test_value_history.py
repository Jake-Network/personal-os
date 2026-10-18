"""Manual financial edits keep an append-only history; current-state tables stay the read path."""
from datetime import date
from decimal import Decimal

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import DatabaseError

from app.modules.database.model import Account, Holding, ManualValueChange


def history(client, resource, item_id):
    res = client.get(f"/api/data/{resource}/{item_id}/history")
    assert res.status_code == 200
    return [(r["field"], r["change_kind"], r["old_value"], r["new_value"], r["as_of"]) for r in res.json()]


ACCOUNT = {"name": "급여통장", "kind": "checking", "currency": "KRW", "balance": "1000000.5",
           "balance_as_of": "2026-09-30", "is_liquid": True}


def test_balance_edits_are_appended_not_overwritten(client):
    acc = client.post("/api/data/accounts", json=ACCOUNT).json()
    client.put(f"/api/data/accounts/{acc['id']}", json={**ACCOUNT, "balance": "1250000.25",
                                                         "balance_as_of": "2026-10-15"})
    client.put(f"/api/data/accounts/{acc['id']}", json={**ACCOUNT, "name": "renamed", "balance": "1250000.25",
                                                         "balance_as_of": "2026-10-15"})  # no value change
    assert client.get("/api/data/accounts").json()[0]["balance"] == "1250000.2500"  # current state
    rows = history(client, "accounts", acc["id"])
    assert [(f, k) for f, k, *_ in rows] == [("balance", "create"), ("balance", "update")]
    assert Decimal(rows[1][2]) == Decimal("1000000.5") and Decimal(rows[1][3]) == Decimal("1250000.25")
    assert rows[1][4] == "2026-10-15"

    client.delete(f"/api/data/accounts/{acc['id']}")
    rows = history(client, "accounts", acc["id"])  # history outlives the record
    assert rows[-1][1] == "delete" and rows[-1][3] is None


def test_holding_quantity_and_average_cost_history(client):
    h = client.post("/api/data/holdings", json={"symbol": "005930", "currency": "KRW", "quantity": "10",
                                                "avg_cost": "70000"}).json()
    client.put(f"/api/data/holdings/{h['id']}", json={"symbol": "005930", "currency": "KRW", "quantity": "12",
                                                      "avg_cost": "71000"})
    client.put(f"/api/data/holdings/{h['id']}", json={"symbol": "005930", "currency": "KRW", "quantity": "12",
                                                      "avg_cost": "71000", "last_price": "80000"})  # price only
    rows = history(client, "holdings", h["id"])
    assert [(f, k) for f, k, *_ in rows] == [("quantity", "create"), ("avg_cost", "create"),
                                             ("quantity", "update"), ("avg_cost", "update")]
    assert Decimal(rows[2][3]) == Decimal("12")


def test_holding_average_cost_history_preserves_twelve_decimal_places(client):
    original = {"symbol": "AAPL", "currency": "USD", "quantity": "1",
                "avg_cost": "0.987654321987"}
    response = client.post("/api/data/holdings", json=original)
    assert response.status_code == 201, response.text
    holding_id = response.json()["id"]
    updated = {**original, "quantity": "2", "avg_cost": "0.000000000002"}
    response = client.put(f"/api/data/holdings/{holding_id}", json=updated)
    assert response.status_code == 200, response.text
    rows = history(client, "holdings", holding_id)
    for field, before, after in (("quantity", original["quantity"], updated["quantity"]),
                                 ("avg_cost", original["avg_cost"], updated["avg_cost"])):
        changes = [r for r in rows if r[0] == field]
        assert [(r[1], None if r[2] is None else Decimal(r[2]), Decimal(r[3]))
                for r in changes] == [("create", None, Decimal(before)),
                                      ("update", Decimal(before), Decimal(after))]


def test_history_precision_migration_preserves_rows_and_immutability(tmp_path):
    config = Config("alembic.ini")
    url = f"sqlite:///{tmp_path / 'precision.db'}"
    config.attributes["database_url"] = url
    command.upgrade(config, "0011_advisor_checkpoints")
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("""INSERT INTO manual_value_changes
            (id, table_name, record_id, field, old_value, new_value, currency,
             as_of, change_kind, recorded_at)
            VALUES (1, 'holdings', 1, 'quantity', 0.12345678, 0.87654321,
                    'USD', '2026-10-18', 'update', '2026-10-18')"""))
        original = connection.execute(text("SELECT * FROM manual_value_changes")).all()
    command.upgrade(config, "head")
    command.check(config)
    columns = {c["name"]: c["type"] for c in inspect(engine).get_columns("manual_value_changes")}
    for name in ("old_value", "new_value"):
        assert (columns[name].precision, columns[name].scale) == (32, 12)
    with engine.begin() as connection:
        assert connection.execute(text("SELECT * FROM manual_value_changes")).all() == original
    for statement in ("UPDATE manual_value_changes SET new_value=0", "DELETE FROM manual_value_changes"):
        with pytest.raises(DatabaseError, match="append-only"):
            with engine.begin() as connection:
                connection.execute(text(statement))
    command.downgrade(config, "0011_advisor_checkpoints")
    with engine.begin() as connection:
        assert connection.execute(text("SELECT * FROM manual_value_changes")).all() == original
    with pytest.raises(DatabaseError, match="append-only"):
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM manual_value_changes"))
    engine.dispose()


def test_record_from_before_the_history_table_gets_a_baseline(client, session):
    legacy = Account(name="old", kind="savings", currency="KRW", balance=Decimal("500"),
                     balance_as_of=date(2026, 1, 31), is_liquid=True)
    session.add(legacy)
    session.commit()
    client.put(f"/api/data/accounts/{legacy.id}", json={**ACCOUNT, "kind": "savings", "balance": "700"})
    rows = [(kind, old and Decimal(old), Decimal(new), as_of)
            for _, kind, old, new, as_of in history(client, "accounts", legacy.id)]
    assert rows == [("baseline", None, Decimal("500"), "2026-01-31"),
                    ("update", Decimal("500"), Decimal("700"), "2026-09-30")]


def test_history_rows_cannot_be_rewritten_through_the_orm(client, session):
    acc = client.post("/api/data/accounts", json=ACCOUNT).json()
    row = session.query(ManualValueChange).filter_by(record_id=acc["id"]).one()
    row.new_value = Decimal("1")
    with pytest.raises(ValueError, match="append-only"):
        session.commit()
    session.rollback()
    session.delete(session.get(ManualValueChange, row.id))
    with pytest.raises(ValueError, match="append-only"):
        session.commit()


def test_migration_backfills_baselines_without_touching_existing_rows(tmp_path):
    config = Config("alembic.ini")
    url = f"sqlite:///{tmp_path / 'existing.db'}"
    config.attributes["database_url"] = url
    command.upgrade(config, "0004_portfolio_identity")
    engine = create_engine(url)
    with engine.begin() as c:
        c.execute(text("""INSERT INTO accounts (id, name, kind, currency, balance, balance_as_of, is_liquid,
            created_at, updated_at) VALUES (1, 'a', 'checking', 'KRW', 1234.5678, '2026-09-30', 1,
            '2026-09-30', '2026-09-30')"""))
        c.execute(text("""INSERT INTO holdings (id, symbol, asset_class, currency, quantity, avg_cost,
            created_at, updated_at) VALUES (1, 'AAPL', 'equity', 'USD', 3.12345678, NULL,
            '2026-09-30', '2026-09-30')"""))
    command.upgrade(config, "head")
    command.check(config)
    with engine.begin() as c:
        assert Decimal(str(c.execute(text("SELECT balance FROM accounts WHERE id=1")).scalar_one())) \
            == Decimal("1234.5678")
        rows = c.execute(text("""SELECT table_name, field, new_value, as_of, change_kind
            FROM manual_value_changes ORDER BY id""")).all()
    assert [(r[0], r[1], r[4]) for r in rows] == [("accounts", "balance", "baseline"),
                                                   ("holdings", "quantity", "baseline")]
    assert str(rows[0][3]) == "2026-09-30"
    for statement in ("UPDATE manual_value_changes SET new_value=0", "DELETE FROM manual_value_changes"):
        with pytest.raises(DatabaseError, match="append-only"):
            with engine.begin() as c:
                c.execute(text(statement))
    command.downgrade(config, "0004_portfolio_identity")
    with engine.begin() as c:
        assert c.execute(text("SELECT count(*) FROM accounts")).scalar_one() == 1
    engine.dispose()


def test_trade_date_dates_the_history_row_without_a_schema_change(client, session):
    h = client.post("/api/data/holdings", json={"symbol": "AAPL", "currency": "USD", "quantity": "3",
                                                "trade_date": "2026-08-14"})
    assert h.status_code == 201 and h.json()["trade_date"] is None  # not stored on the holding
    hid = h.json()["id"]
    client.put(f"/api/data/holdings/{hid}", json={"symbol": "AAPL", "currency": "USD", "quantity": "5",
                                                  "trade_date": "2026-09-02"})
    client.put(f"/api/data/holdings/{hid}", json={"symbol": "AAPL", "currency": "USD", "quantity": "6"})
    as_of = [r[4] for r in history(client, "holdings", hid)]
    assert as_of[:2] == ["2026-08-14", "2026-09-02"]
    assert as_of[2] not in ("2026-08-14", "2026-09-02")  # no trade date → the recording date
    assert "trade_date" not in Holding.__table__.columns
