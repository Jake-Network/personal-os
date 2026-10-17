"""Append-only history of manual balance, quantity and average-cost edits.

Existing rows are not modified. Each current account balance and holding quantity / average cost
gets one `baseline` history row so the value in place before this migration is preserved.
"""
from datetime import UTC, datetime

from alembic import op
import sqlalchemy as sa

revision = "0005_manual_value_history"
down_revision = "0004_portfolio_identity"
branch_labels = None
depends_on = None

TABLE = "manual_value_changes"


def upgrade():
    changes = op.create_table(TABLE,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("table_name", sa.String(32), nullable=False),
        sa.Column("record_id", sa.Integer(), nullable=False),
        sa.Column("field", sa.String(32), nullable=False),
        sa.Column("old_value", sa.Numeric(28, 8), nullable=True),
        sa.Column("new_value", sa.Numeric(28, 8), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("change_kind", sa.String(16), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_manual_value_changes_record", TABLE, ["table_name", "record_id", "id"])

    bind = op.get_bind()
    now = datetime.now(UTC)
    rows = []
    accounts = sa.table("accounts", sa.column("id"), sa.column("balance", sa.Numeric(20, 4)),
                        sa.column("currency"), sa.column("balance_as_of", sa.Date()))
    for a in bind.execute(sa.select(accounts)).mappings():
        rows.append({"table_name": "accounts", "record_id": a["id"], "field": "balance", "old_value": None,
                     "new_value": a["balance"], "currency": a["currency"], "as_of": a["balance_as_of"],
                     "change_kind": "baseline", "recorded_at": now})
    holdings = sa.table("holdings", sa.column("id"), sa.column("quantity", sa.Numeric(24, 8)),
                        sa.column("avg_cost", sa.Numeric(20, 4)), sa.column("currency"))
    for h in bind.execute(sa.select(holdings)).mappings():
        for field in ("quantity", "avg_cost"):
            if h[field] is not None:
                rows.append({"table_name": "holdings", "record_id": h["id"], "field": field, "old_value": None,
                             "new_value": h[field], "currency": h["currency"], "as_of": now.date(),
                             "change_kind": "baseline", "recorded_at": now})
    if rows:
        op.bulk_insert(changes, rows)

    dialect = bind.dialect.name
    if dialect == "postgresql":
        op.execute("""CREATE FUNCTION reject_manual_value_change_mutation() RETURNS trigger
            LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'Manual value history is append-only'; END; $$""")
        op.execute(f"""CREATE TRIGGER manual_value_changes_immutable BEFORE UPDATE OR DELETE
            ON {TABLE} FOR EACH ROW EXECUTE FUNCTION reject_manual_value_change_mutation()""")
    elif dialect == "sqlite":
        for action in ("UPDATE", "DELETE"):
            op.execute(f"""CREATE TRIGGER manual_value_changes_no_{action.lower()} BEFORE {action}
                ON {TABLE} BEGIN SELECT RAISE(ABORT, 'Manual value history is append-only'); END""")


def downgrade():
    op.drop_index("ix_manual_value_changes_record", table_name=TABLE)
    op.drop_table(TABLE)
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP FUNCTION reject_manual_value_change_mutation()")
