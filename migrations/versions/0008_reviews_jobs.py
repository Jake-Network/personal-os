"""Preserve repeated decision outcomes and opt-in local background review work."""
from alembic import op
import sqlalchemy as sa

revision = "0008_reviews_jobs"
down_revision = "0007_document_job_attempts"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("decision_reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("decision_id", sa.Integer(), sa.ForeignKey("decision_journal.id", ondelete="CASCADE"), nullable=False),
        sa.Column("actual_outcome", sa.Text(), nullable=False),
        sa.Column("lessons", sa.Text()), sa.Column("next_action", sa.Text()),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expected_outcome", sa.Text()),
        sa.Column("context_snapshot_id", sa.String(36), sa.ForeignKey("context_snapshots.id", ondelete="SET NULL")))
    op.create_index("ix_decision_reviews_decision_id", "decision_reviews", ["decision_id"])
    op.create_table("job_schedules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False), sa.Column("cadence", sa.String(16), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    # Preserve the old outcome once, with its original timestamp and evidence.
    op.execute(sa.text("""INSERT INTO decision_reviews
        (decision_id, actual_outcome, reviewed_at, expected_outcome, context_snapshot_id)
        SELECT id, actual_outcome, reviewed_at, expected_outcome, context_snapshot_id
        FROM decision_journal WHERE actual_outcome IS NOT NULL"""))
    op.create_table("period_reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("request_id", sa.String(100), nullable=False, unique=True),
        sa.Column("period", sa.String(16), nullable=False),
        sa.Column("start_on", sa.Date(), nullable=False), sa.Column("end_on", sa.Date(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False), sa.Column("content", sa.Text(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)))
    op.create_table("background_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("request_id", sa.String(100), nullable=False, unique=True),
        sa.Column("kind", sa.String(32), nullable=False), sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False), sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON()), sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("run_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_owner", sa.String(36)), sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.String(100)), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)))
    op.create_index("ix_background_jobs_status", "background_jobs", ["status"])


def downgrade():
    op.drop_table("job_schedules")
    op.drop_table("background_jobs")
    op.drop_table("period_reviews")
    op.drop_table("decision_reviews")
