"""Explicit official LangGraph checkpoint schema (pinned saver versions)."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0011_advisor_checkpoints"
down_revision = "0010_advisor_runtime"
branch_labels = None
depends_on = None


def upgrade():
    postgres = op.get_bind().dialect.name == "postgresql"
    op.create_table("checkpoints",
        sa.Column("thread_id", sa.Text(), primary_key=True),
        sa.Column("checkpoint_ns", sa.Text(), primary_key=True, server_default=""),
        sa.Column("checkpoint_id", sa.Text(), primary_key=True),
        sa.Column("parent_checkpoint_id", sa.Text()),
        sa.Column("type", sa.Text()),
        sa.Column("checkpoint", JSONB() if postgres else sa.LargeBinary(), nullable=not postgres),
        sa.Column("metadata", JSONB() if postgres else sa.LargeBinary(), nullable=not postgres,
                  server_default=sa.text("'{}'::jsonb") if postgres else None))
    op.create_index("checkpoints_thread_id_idx", "checkpoints", ["thread_id"])
    if postgres:
        op.create_table("checkpoint_blobs",
            sa.Column("thread_id", sa.Text(), primary_key=True),
            sa.Column("checkpoint_ns", sa.Text(), primary_key=True, server_default=""),
            sa.Column("channel", sa.Text(), primary_key=True),
            sa.Column("version", sa.Text(), primary_key=True),
            sa.Column("type", sa.Text(), nullable=False),
            sa.Column("blob", sa.LargeBinary()))
        op.create_index("checkpoint_blobs_thread_id_idx", "checkpoint_blobs", ["thread_id"])
    name = "checkpoint_writes" if postgres else "writes"
    op.create_table(name,
        sa.Column("thread_id", sa.Text(), primary_key=True),
        sa.Column("checkpoint_ns", sa.Text(), primary_key=True, server_default=""),
        sa.Column("checkpoint_id", sa.Text(), primary_key=True),
        sa.Column("task_id", sa.Text(), primary_key=True),
        *([sa.Column("task_path", sa.Text(), nullable=False, server_default="")] if postgres else []),
        sa.Column("idx", sa.Integer(), primary_key=True),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("type", sa.Text()),
        sa.Column("blob" if postgres else "value", sa.LargeBinary(), nullable=not postgres))
    op.create_index(f"{name}_thread_id_idx", name, ["thread_id"])
    if postgres:
        op.create_table("checkpoint_migrations", sa.Column("v", sa.Integer(), primary_key=True))
        # Versions 0..9 are exactly the schema expected by checkpoint-postgres 3.0.4.
        op.bulk_insert(sa.table("checkpoint_migrations", sa.column("v", sa.Integer())), [{"v": i} for i in range(10)])


def downgrade():
    postgres = op.get_bind().dialect.name == "postgresql"
    if postgres:
        op.drop_table("checkpoint_migrations")
        op.drop_table("checkpoint_blobs")
    op.drop_table("checkpoint_writes" if postgres else "writes")
    op.drop_table("checkpoints")
