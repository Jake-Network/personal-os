"""Retain the historical checkpoint revision as a PostgreSQL no-op.

The task_path column has been present in checkpoint_writes since revision 0011.
"""

revision = "0016_checkpoint_task_path"
down_revision = "0015_decision_source_message"
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
