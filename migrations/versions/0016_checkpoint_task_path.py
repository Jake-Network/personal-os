"""Preserve SQLite pending task ordering for the patched checkpoint saver."""
from alembic import op
import sqlalchemy as sa


revision = "0016_checkpoint_task_path"
down_revision = "0015_decision_source_message"
branch_labels = None
depends_on = None


def upgrade():
    # PostgreSQL has carried this column since 0011; SQLite saver 3.1 adds it.
    # Runtime saver setup must never perform this DDL against an existing DB.
    if op.get_bind().dialect.name == "sqlite":
        op.add_column("writes", sa.Column("task_path", sa.Text(), nullable=False, server_default=""))


def downgrade():
    if op.get_bind().dialect.name == "sqlite":
        op.drop_column("writes", "task_path")
