"""Preserve the twelve decimal places accepted by local holdings in their audit log."""

from alembic import op
import sqlalchemy as sa

revision = "0012_manual_history_precision"
down_revision = "0011_advisor_checkpoints"
branch_labels = None
depends_on = None


def _change_precision(old_type, new_type):
    with op.batch_alter_table("manual_value_changes") as batch:
        for column in ("old_value", "new_value"):
            batch.alter_column(column, existing_type=old_type, type_=new_type,
                               existing_nullable=True)
    # SQLite's batch operation recreates the table, which drops its triggers.
    # PostgreSQL alters the columns in place and retains the original trigger.
    if op.get_bind().dialect.name == "sqlite":
        for action in ("UPDATE", "DELETE"):
            op.execute(f"""CREATE TRIGGER manual_value_changes_no_{action.lower()}
                BEFORE {action} ON manual_value_changes
                BEGIN SELECT RAISE(ABORT, 'Manual value history is append-only'); END""")


def upgrade():
    _change_precision(sa.Numeric(28, 8), sa.Numeric(32, 12))


def downgrade():
    _change_precision(sa.Numeric(32, 12), sa.Numeric(28, 8))
