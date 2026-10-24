"""Preserve the twelve decimal places accepted by local holdings in their audit log."""

from alembic import op
import sqlalchemy as sa

revision = "0012_manual_history_precision"
down_revision = "0011_advisor_checkpoints"
branch_labels = None
depends_on = None


def _change_precision(old_type, new_type):
    for column in ("old_value", "new_value"):
        op.alter_column("manual_value_changes", column, existing_type=old_type, type_=new_type,
                        existing_nullable=True)


def upgrade():
    _change_precision(sa.Numeric(28, 8), sa.Numeric(32, 12))


def downgrade():
    _change_precision(sa.Numeric(32, 12), sa.Numeric(28, 8))
