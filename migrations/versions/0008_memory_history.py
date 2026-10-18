"""Version memories without rewriting original IDs and source-linked summary drafts."""
from alembic import op
import sqlalchemy as sa
revision = "0008_memory_history"
down_revision = "0007_document_job_attempts"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("memory_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("memory_id", sa.Integer(), sa.ForeignKey("personal_memories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False), sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False), sa.Column("scope", sa.String(200)),
        sa.Column("valid_from", sa.DateTime(timezone=True)), sa.Column("valid_until", sa.DateTime(timezone=True)),
        sa.Column("review_on", sa.DateTime(timezone=True)),
        sa.Column("external_allowed", sa.Boolean(), nullable=False),
        sa.Column("source_references", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("memory_id", "revision", name="uq_memory_revision"))
    op.create_index("ix_memory_revisions_memory_id", "memory_revisions", ["memory_id"])
    op.create_table("conversation_summaries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("advisor_conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("first_message_id", sa.Integer(), nullable=False), sa.Column("last_message_id", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False), sa.Column("status", sa.String(16), nullable=False),
        sa.Column("source_references", sa.JSON(), nullable=False), sa.Column("generator", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_conversation_summaries_conversation_id", "conversation_summaries", ["conversation_id"])
    op.create_table("history_search_index",
        sa.Column("message_id", sa.Integer(), sa.ForeignKey("advisor_messages.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("content_hash", sa.String(64), nullable=False), sa.Column("model", sa.String(200), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False), sa.Column("vector", sa.JSON(), nullable=False),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("conversation_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("advisor_conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False), sa.Column("target", sa.String(200), nullable=False),
        sa.UniqueConstraint("conversation_id", "kind", "target", name="uq_conversation_link"))
    op.create_index("ix_conversation_links_conversation_id", "conversation_links", ["conversation_id"])
    bind = op.get_bind()
    memories = sa.table("personal_memories", sa.column("id"), sa.column("kind"), sa.column("content"),
        sa.column("status"), sa.column("source_message_id"), sa.column("created_at"), sa.column("confirmed_at"))
    revisions = sa.table("memory_revisions", sa.column("memory_id"), sa.column("revision"), sa.column("kind"),
        sa.column("content"), sa.column("status"), sa.column("external_allowed"), sa.column("source_references", sa.JSON()),
        sa.column("created_at"), sa.column("confirmed_at"))
    from datetime import UTC
    messages = sa.table("advisor_messages", sa.column("id"), sa.column("created_at", sa.DateTime(timezone=True)))
    for row in bind.execute(sa.select(memories)).mappings():
        sources = []
        if row["source_message_id"]:
            reference = {"table": "advisor_messages", "id": row["source_message_id"]}
            created = bind.execute(sa.select(messages.c.created_at).where(messages.c.id == row["source_message_id"])).scalar()
            if created:
                reference["source_created_at"] = (created if created.tzinfo else created.replace(tzinfo=UTC)).isoformat()
            sources.append(reference)
        bind.execute(revisions.insert().values(memory_id=row["id"], revision=0, kind=row["kind"], content=row["content"],
            status=row["status"], external_allowed=True, created_at=row["created_at"], confirmed_at=row["confirmed_at"],
            source_references=sources))


def downgrade():
    op.drop_table("conversation_links")
    op.drop_table("history_search_index")
    op.drop_table("conversation_summaries")
    op.drop_table("memory_revisions")
