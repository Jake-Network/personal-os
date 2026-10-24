"""Join agent and workout-record histories without rewriting published revisions."""

revision = "0018_merge_advisor_records"
down_revision = ("0017_merge_agent_security", "0017_workout_duration_seconds")
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
