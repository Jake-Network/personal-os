"""Join published agent and checkpoint security histories without changing their data."""

revision = "0017_merge_agent_security"
down_revision = ("0016_agent_playbooks_inbox", "0016_checkpoint_task_path")
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
