"""Keep the saved answer identity behind a decision, including answer revisions."""
from alembic import op
import sqlalchemy as sa

revision = "0015_decision_source_message"
down_revision = "0014_calendar_all_day"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("decision_journal", sa.Column("source_message_id", sa.Integer(),
        sa.ForeignKey("advisor_messages.id", name="fk_decision_source_message", ondelete="SET NULL"), nullable=True))


def downgrade():
    op.drop_constraint("fk_decision_source_message", "decision_journal", type_="foreignkey")
    op.drop_column("decision_journal", "source_message_id")
