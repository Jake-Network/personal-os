"""Career source records; timeline is derived without duplicating facts."""
from alembic import op
import sqlalchemy as sa

revision = "0008_career_records"
down_revision = "0007_document_job_attempts"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("career_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("parent_id", sa.Integer(), sa.ForeignKey("career_records.id", ondelete="RESTRICT")),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("company", sa.String(120)),
        sa.Column("organization", sa.String(120)),
        sa.Column("role", sa.String(160)),
        sa.Column("started_on", sa.String(10)),
        sa.Column("ended_on", sa.String(10)),
        sa.Column("description", sa.Text()),
        sa.Column("approach", sa.Text()),
        sa.Column("outcome", sa.Text()),
        sa.Column("lessons", sa.Text()),
        sa.Column("evidence_url", sa.String(2000)),
        sa.Column("skills", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("progress", sa.String(16), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("source_message_id", sa.Integer(), sa.ForeignKey("advisor_messages.id", ondelete="SET NULL")),
        sa.Column("source_references", sa.JSON(), nullable=False),
        sa.Column("source_document_version_id", sa.Integer(), sa.ForeignKey("document_versions.id", ondelete="SET NULL")),
        sa.Column("share_with_advisor", sa.Boolean(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sqlite_autoincrement=True,
    )


def downgrade():
    op.drop_table("career_records")
