"""Add approved advisor playbooks, a local inbox and briefing schedules.

Additive only: existing schedules stay period reviews and existing conversations
stay user conversations through server defaults; no existing row is rewritten.
"""
from alembic import op
import sqlalchemy as sa

revision = "0016_agent_playbooks_inbox"
down_revision = "0015_decision_source_message"
branch_labels = None
depends_on = None


def timestamp(name, nullable=False):
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def upgrade():
    op.create_table("playbooks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slug", sa.String(40), nullable=False, unique=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("external_allowed", sa.Boolean(), nullable=False),
        timestamp("created_at"), timestamp("updated_at"))
    op.create_table("playbook_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("playbook_id", sa.Integer(), sa.ForeignKey("playbooks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("summary", sa.String(300), nullable=False),
        sa.Column("triggers", sa.JSON(), nullable=False),
        sa.Column("categories", sa.JSON(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("base_revision_id", sa.Integer(),
                  sa.ForeignKey("playbook_revisions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("rationale", sa.Text()),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("source_references", sa.JSON(), nullable=False),
        sa.Column("proposed_by_job_id", sa.Integer(),
                  sa.ForeignKey("background_jobs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("source_purged", sa.Boolean(), nullable=False),
        timestamp("created_at"), timestamp("decided_at", nullable=True),
        sa.UniqueConstraint("playbook_id", "revision", name="uq_playbook_revision"))
    op.create_index("ix_playbook_revisions_playbook_id", "playbook_revisions", ["playbook_id"])
    op.create_index("ix_playbook_revisions_status", "playbook_revisions", ["status"])
    active = sa.text("status = 'active'")
    op.create_index("uq_playbook_active_revision", "playbook_revisions", ["playbook_id"],
                    unique=True, postgresql_where=active)
    op.create_table("playbook_usages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("revision_id", sa.Integer(), sa.ForeignKey("playbook_revisions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("advisor_runs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("context_snapshot_id", sa.String(36),
                  sa.ForeignKey("context_snapshots.id", ondelete="SET NULL"), nullable=True),
        timestamp("created_at"))
    op.create_index("ix_playbook_usages_revision_id", "playbook_usages", ["revision_id"])
    op.create_table("inbox_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("links", sa.JSON(), nullable=False),
        sa.Column("dedupe_key", sa.String(160), nullable=False, unique=True),
        sa.Column("status", sa.String(16), nullable=False),
        timestamp("created_at"), timestamp("read_at", nullable=True))
    op.create_index("ix_inbox_items_status", "inbox_items", ["status"])

    # ADD COLUMN with constant defaults is additive on PostgreSQL; no table rebuild.
    op.add_column("job_schedules", sa.Column("kind", sa.String(32), nullable=False,
                                             server_default="period_review"))
    op.add_column("job_schedules", sa.Column("local_time", sa.String(5), nullable=True))
    op.add_column("job_schedules", sa.Column("options", sa.JSON(), nullable=False,
                                             server_default=sa.text("'{}'")))
    op.add_column("job_schedules", sa.Column("authorization", sa.JSON(), nullable=True))
    op.add_column("job_schedules", sa.Column("paused_reason", sa.String(64), nullable=True))
    op.add_column("advisor_conversations", sa.Column("origin", sa.String(16), nullable=False,
                                                     server_default="user"))


def downgrade():
    op.drop_column("advisor_conversations", "origin")
    for column in ("paused_reason", "authorization", "options", "local_time", "kind"):
        op.drop_column("job_schedules", column)
    op.drop_table("inbox_items")
    op.drop_table("playbook_usages")
    op.drop_table("playbook_revisions")
    op.drop_table("playbooks")
