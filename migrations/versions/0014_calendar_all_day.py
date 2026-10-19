"""Mark calendar events that span whole local days.

Existing events keep all_day = false, so their stored start and end times mean what they meant before.

Revision ID: 0014_calendar_all_day
Revises: 0013_goal_values_as_text
"""

import sqlalchemy as sa
from alembic import op

revision = "0014_calendar_all_day"
down_revision = "0013_goal_values_as_text"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("calendar_events", sa.Column("all_day", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    with op.batch_alter_table("calendar_events") as batch:
        batch.drop_column("all_day")
