"""Local owner authentication, revocable idle sessions, browser-bound OAuth attempts."""
from alembic import op
import sqlalchemy as sa

revision = "0008_app_security"
down_revision = "0007_document_job_attempts"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("app_owner", sa.Column("id", sa.Integer(), primary_key=True),
                    sa.Column("password_hash", sa.Text(), nullable=False),
                    sa.Column("failed_attempts", sa.Integer(), nullable=False),
                    sa.Column("blocked_until", sa.DateTime(timezone=True)),
                    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("app_sessions", sa.Column("token_hash", sa.String(64), primary_key=True),
                    sa.Column("csrf_token", sa.String(128), nullable=False),
                    sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=False),
                    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("app_oauth_attempts", sa.Column("state_hash", sa.String(64), primary_key=True),
                    sa.Column("session_hash", sa.String(64), nullable=False),
                    sa.Column("provider", sa.String(20), nullable=False),
                    sa.Column("proof_hash", sa.String(64), nullable=False),
                    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_app_oauth_attempts_session_hash", "app_oauth_attempts", ["session_hash"])


def downgrade():
    op.drop_table("app_oauth_attempts")
    op.drop_table("app_sessions")
    op.drop_table("app_owner")
