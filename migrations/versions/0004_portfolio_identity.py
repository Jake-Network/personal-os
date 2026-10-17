"""Bind imported values and current quote proof to the Google principal."""
from alembic import op
import sqlalchemy as sa

revision = "0004_portfolio_identity"
down_revision = "0003_google_oauth"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("portfolio_settings", sa.Column("verified_identity", sa.String(500), nullable=True))
    op.add_column("portfolio_imports", sa.Column("source_identity", sa.String(500), nullable=True))


def downgrade():
    op.drop_column("portfolio_imports", "source_identity")
    op.drop_column("portfolio_settings", "verified_identity")
