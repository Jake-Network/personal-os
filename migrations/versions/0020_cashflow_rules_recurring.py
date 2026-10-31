"""Add ledger category rules and recurring cash flows.

Both tables are new; no existing row is read or changed. Imported CSV rows reuse
finance_import_mappings for their source identity, so no column is added to cashflow_entries.
"""

import sqlalchemy as sa
from alembic import op

revision = "0020_cashflow_rules_recurring"
down_revision = "0019_fx_rate_per_pair"
branch_labels = None
depends_on = None


def timestamp(name):
    return sa.Column(name, sa.DateTime(timezone=True), nullable=False)


def upgrade():
    op.create_table(
        "cashflow_category_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("match_text", sa.String(200), nullable=False),
        sa.Column("match_kind", sa.String(16), nullable=False),
        sa.Column("category", sa.String(64), nullable=False),
        timestamp("created_at"),
        timestamp("updated_at"),
        sa.UniqueConstraint("match_kind", "match_text", name="uq_cashflow_category_rules_match"),
    )
    op.create_table(
        "recurring_cashflows",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("amount", sa.Numeric(20, 4), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("category", sa.String(64), nullable=True),
        sa.Column("day_of_month", sa.Integer(), nullable=False),
        sa.Column("start_on", sa.Date(), nullable=False),
        sa.Column("end_on", sa.Date(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        timestamp("created_at"),
        timestamp("updated_at"),
    )


def downgrade():
    op.drop_table("recurring_cashflows")
    op.drop_table("cashflow_category_rules")
