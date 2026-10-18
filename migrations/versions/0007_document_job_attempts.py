"""Bound document indexing retries: claim count and transient-error backoff.

Existing versions start at zero attempts with no backoff. Stop indexing workers before
either direction of this migration.
"""
from alembic import op
import sqlalchemy as sa

revision = "0007_document_job_attempts"
down_revision = "0006_merge_docs_value_history"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("document_versions", sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("document_versions", sa.Column("retry_after", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_column("document_versions", "retry_after")
    op.drop_column("document_versions", "attempts")
