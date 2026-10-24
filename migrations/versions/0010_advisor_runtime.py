"""Add durable advisor runs, events, clarification inputs and versioned scenarios."""
from alembic import op
import sqlalchemy as sa

revision = "0010_advisor_runtime"
down_revision = "0009_merge_local_os"
branch_labels = None
depends_on = None

def fk(name, target, ondelete="CASCADE", nullable=False):
    return sa.Column(name, sa.String(36) if target.startswith(("advisor_runs.", "advisor_scenarios.")) else sa.Integer(),
                     sa.ForeignKey(target, ondelete=ondelete), nullable=nullable)

def timestamp(name):
    return sa.Column(name, sa.DateTime(timezone=True), nullable=False)

def upgrade():
    op.create_table("advisor_runtime_lock",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("generation", sa.Integer(), nullable=False))
    op.create_table("advisor_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        fk("conversation_id", "advisor_conversations.id"),
        sa.Column("request_id", sa.String(128), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("depth", sa.String(16), nullable=False),
        sa.Column("input_payload", sa.JSON(), nullable=False),
        fk("user_message_id", "advisor_messages.id", "SET NULL", True),
        fk("assistant_message_id", "advisor_messages.id", "SET NULL", True),
        sa.Column("authorization", sa.JSON(), nullable=False),
        sa.Column("runtime_metadata", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON()),
        sa.Column("checkpoint", sa.JSON(), nullable=False),
        sa.Column("clarification", sa.JSON()),
        sa.Column("error", sa.Text()),
        sa.Column("provider", sa.String(80)), sa.Column("model", sa.String(80)),
        sa.Column("account_binding", sa.String(200)),
        sa.Column("lease_owner", sa.String(80)),
        sa.Column("lease_generation", sa.Integer(), nullable=False),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("last_event_seq", sa.Integer(), nullable=False),
        sa.Column("answer_revision", sa.Integer(), nullable=False),
        timestamp("created_at"), timestamp("updated_at"),
        sa.UniqueConstraint("conversation_id", "request_id", name="uq_advisor_run_request"))
    op.create_index("ix_advisor_runs_conversation_id", "advisor_runs", ["conversation_id"])
    op.create_index("ix_advisor_runs_status", "advisor_runs", ["status"])
    condition = sa.text("status NOT IN ('completed','cancelled','failed')")
    op.create_index("uq_advisor_active_conversation", "advisor_runs", ["conversation_id"],
                    unique=True, postgresql_where=condition)
    op.create_table("advisor_run_events",
        sa.Column("id", sa.Integer(), primary_key=True), fk("run_id", "advisor_runs.id"),
        sa.Column("seq", sa.Integer(), nullable=False), sa.Column("event_key", sa.String(200), nullable=False),
        sa.Column("type", sa.String(40), nullable=False), sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False), timestamp("created_at"),
        sa.UniqueConstraint("run_id", "seq", name="uq_advisor_event_seq"),
        sa.UniqueConstraint("run_id", "event_key", name="uq_advisor_event_key"))
    op.create_index("ix_advisor_run_events_run_id", "advisor_run_events", ["run_id"])
    op.create_table("advisor_run_responses",
        sa.Column("id", sa.Integer(), primary_key=True), fk("run_id", "advisor_runs.id"),
        sa.Column("request_id", sa.String(128), nullable=False),
        sa.Column("question_id", sa.String(80), nullable=False),
        sa.Column("response", sa.Text(), nullable=False), timestamp("created_at"),
        sa.UniqueConstraint("run_id", "request_id", name="uq_advisor_response_request"),
        sa.UniqueConstraint("run_id", "question_id", name="uq_advisor_question_response"))
    op.create_table("advisor_scenarios",
        sa.Column("id", sa.String(36), primary_key=True), fk("conversation_id", "advisor_conversations.id"),
        fk("run_id", "advisor_runs.id", "SET NULL", True), fk("parent_id", "advisor_scenarios.id", "SET NULL", True),
        sa.Column("request_id", sa.String(128), nullable=False), sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("assumptions", sa.JSON(), nullable=False), sa.Column("constraints", sa.JSON(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False), sa.Column("results", sa.JSON(), nullable=False),
        sa.Column("unknowns", sa.JSON(), nullable=False), timestamp("created_at"),
        sa.UniqueConstraint("conversation_id", "request_id", name="uq_advisor_scenario_request"))
    op.create_index("ix_advisor_scenarios_conversation_id", "advisor_scenarios", ["conversation_id"])
    op.create_table("advisor_workspaces",
        fk("conversation_id", "advisor_conversations.id"),
        fk("selected_scenario_id", "advisor_scenarios.id", "SET NULL", True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("problem", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("conversation_id"))

def downgrade():
    for table in ("advisor_workspaces", "advisor_scenarios", "advisor_run_responses",
                  "advisor_run_events", "advisor_runs", "advisor_runtime_lock"):
        op.drop_table(table)
