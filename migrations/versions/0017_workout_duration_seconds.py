"""Store workout durations in seconds without rounding existing minute records."""

import sqlalchemy as sa
from alembic import op

revision = "0017_workout_duration_seconds"
down_revision = "0016_checkpoint_task_path"
branch_labels = None
depends_on = None


def upgrade():
    # Widen before multiplying, preserving the entire previous integer range.
    op.alter_column("workout_logs", "duration_minutes", new_column_name="duration_seconds",
                    type_=sa.BigInteger(), existing_type=sa.Integer(), existing_nullable=False)
    op.execute("UPDATE workout_logs SET duration_seconds = duration_seconds * 60")


def downgrade():
    connection = op.get_bind()
    incompatible = connection.execute(sa.text(
        "SELECT EXISTS (SELECT 1 FROM workout_logs WHERE duration_seconds % 60 <> 0 "
        "OR duration_seconds / 60 > 2147483647 OR duration_seconds / 60 < -2147483648)"
    )).scalar()
    if incompatible:
        raise RuntimeError("Cannot downgrade workout durations without losing seconds or overflowing minutes")
    op.execute("UPDATE workout_logs SET duration_seconds = duration_seconds / 60")
    op.alter_column("workout_logs", "duration_seconds", new_column_name="duration_minutes",
                    type_=sa.Integer(), existing_type=sa.BigInteger(), existing_nullable=False)
