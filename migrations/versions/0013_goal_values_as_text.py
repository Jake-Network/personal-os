"""Store goal progress values as free-form text.

Revision ID: 0013_goal_values_as_text
Revises: 0012_manual_history_precision
"""

from decimal import Decimal, InvalidOperation

import sqlalchemy as sa
from alembic import op

revision = "0013_goal_values_as_text"
down_revision = "0012_manual_history_precision"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("goals", "target_value", existing_type=sa.Numeric(20, 4), type_=sa.Text(),
                    existing_nullable=True, postgresql_using="target_value::text")
    op.alter_column("goals", "current_value", existing_type=sa.Numeric(20, 4), type_=sa.Text(),
                    existing_nullable=True, postgresql_using="current_value::text")


def downgrade():
    bind = op.get_bind()
    values = bind.execute(sa.text("SELECT target_value, current_value FROM goals")).all()
    try:
        for row in values:
            for value in row:
                if value is not None and not Decimal(value).is_finite():
                    raise ValueError
    except (InvalidOperation, ValueError) as exc:
        raise RuntimeError("Goal values contain free-form text and cannot be safely converted back") from exc

    op.alter_column("goals", "target_value", existing_type=sa.Text(), type_=sa.Numeric(20, 4),
                    existing_nullable=True, postgresql_using="target_value::numeric(20,4)")
    op.alter_column("goals", "current_value", existing_type=sa.Text(), type_=sa.Numeric(20, 4),
                    existing_nullable=True, postgresql_using="current_value::numeric(20,4)")
