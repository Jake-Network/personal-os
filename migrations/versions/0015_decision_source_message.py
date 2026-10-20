"""Keep the saved answer identity behind a decision, including answer revisions."""
from alembic import op
import sqlalchemy as sa

revision = "0015_decision_source_message"
down_revision = "0014_calendar_all_day"
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().dialect.name == "sqlite":
        # Inline nullable REFERENCES is supported by SQLite ADD COLUMN. Avoid a
        # batch rebuild: dropping the parent table can cascade outcome history.
        op.execute("ALTER TABLE decision_journal ADD COLUMN source_message_id INTEGER "
                   "REFERENCES advisor_messages(id) ON DELETE SET NULL")
    else:
        op.add_column("decision_journal", sa.Column("source_message_id", sa.Integer(),
            sa.ForeignKey("advisor_messages.id", name="fk_decision_source_message", ondelete="SET NULL"), nullable=True))


def downgrade():
    if op.get_bind().dialect.name != "sqlite":
        op.drop_constraint("fk_decision_source_message", "decision_journal", type_="foreignkey")
    op.drop_column("decision_journal", "source_message_id")
