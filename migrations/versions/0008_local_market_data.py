"""Local finance identities and public quotes, preserving legacy imports."""

from alembic import op
import sqlalchemy as sa

revision = "0008_local_market_data"
down_revision = "0007_document_job_attempts"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "holding_write_receipts",
        sa.Column("request_id", sa.String(120), primary_key=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "local_finance_coverage",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kinds", sa.JSON(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "finance_import_mappings",
        sa.Column("source_ref", sa.String(500), primary_key=True),
        sa.Column("table_name", sa.String(32), nullable=False),
        sa.Column("record_id", sa.Integer(), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
    )
    with op.batch_alter_table("holdings") as batch:
        batch.alter_column(
            "quantity",
            existing_type=sa.Numeric(24, 8),
            type_=sa.Numeric(32, 12),
            existing_nullable=False,
        )
        batch.alter_column(
            "avg_cost",
            existing_type=sa.Numeric(20, 4),
            type_=sa.Numeric(32, 12),
            existing_nullable=True,
        )
        batch.alter_column(
            "last_price",
            existing_type=sa.Numeric(20, 4),
            type_=sa.Numeric(32, 12),
            existing_nullable=True,
        )
    op.create_table(
        "financial_transactions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("request_id", sa.String(120), nullable=False, unique=True),
        sa.Column(
            "reverses_id",
            sa.Integer(),
            sa.ForeignKey("financial_transactions.id"),
            unique=True,
        ),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_index(
        "ix_financial_transactions_kind", "financial_transactions", ["kind"]
    )
    op.create_table(
        "local_positions",
        sa.Column("position_id", sa.String(120), primary_key=True),
        sa.Column(
            "holding_id",
            sa.Integer(),
            sa.ForeignKey("holdings.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("quote_mode", sa.String(16), nullable=False),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("source_ref", sa.String(300), unique=True),
    )
    op.create_table(
        "market_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("spreadsheet_id", sa.String(200), nullable=False),
        sa.Column("source_identity", sa.String(500), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
    )
    op.create_table(
        "market_observations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("fingerprint", sa.String(64), nullable=False, unique=True),
        sa.Column("symbol", sa.String(80), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_index("ix_market_observations_symbol", "market_observations", ["symbol"])


def downgrade():
    op.drop_table("holding_write_receipts")
    op.drop_table("local_finance_coverage")
    op.drop_table("finance_import_mappings")
    op.drop_table("financial_transactions")
    op.drop_table("market_observations")
    op.drop_table("market_settings")
    op.drop_table("local_positions")
