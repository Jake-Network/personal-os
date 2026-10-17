"""Dedicated encrypted Google Sheets OAuth connection and durable single-use states."""
from alembic import op
import sqlalchemy as sa

revision = "0003_google_oauth"
down_revision = "0002_portfolio"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("google_oauth_connections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("subject", sa.String(255)),
        sa.Column("email", sa.String(320)),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary()),
        sa.Column("access_expires_at", sa.DateTime(timezone=True)),
        sa.Column("last_error_code", sa.String(80)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("google_oauth_pending",
        sa.Column("state_hash", sa.String(64), primary_key=True),
        sa.Column("binding_hash", sa.String(64), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False))


def downgrade():
    op.drop_table("google_oauth_pending")
    op.drop_table("google_oauth_connections")
