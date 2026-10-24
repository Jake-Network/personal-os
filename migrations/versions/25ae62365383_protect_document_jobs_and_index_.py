"""Fence document jobs, index provenance, and adopt missing legacy protections.

Existing snapshot payloads remain unchanged. Duplicate derived chunks retain the
oldest id for each version/ordinal; raw uploads and captured excerpts are retained.
Downgrade removes lease/provenance metadata and cannot recreate deduplicated chunk
ids. Stop indexing workers before either direction of this migration.
"""
from alembic import op
import sqlalchemy as sa

revision = '25ae62365383'
down_revision = '6581e3048ce0'
branch_labels = None
depends_on = None


def _repair_legacy_triggers():
    op.execute('''CREATE OR REPLACE FUNCTION reject_monthly_snapshot_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'Monthly snapshots are append-only'; END; $$''')
    op.execute('''DO $$ BEGIN IF NOT EXISTS (
        SELECT 1 FROM pg_trigger WHERE tgname = 'monthly_snapshots_immutable'
        AND tgrelid = 'monthly_snapshots'::regclass) THEN
        CREATE TRIGGER monthly_snapshots_immutable BEFORE UPDATE OR DELETE
        ON monthly_snapshots FOR EACH ROW EXECUTE FUNCTION reject_monthly_snapshot_mutation();
        END IF; END $$''')


def _backfill_references(connection):
    snapshots = sa.table('context_snapshots', sa.column('id', sa.String), sa.column('payload', sa.JSON))
    references = sa.table('context_document_references', sa.column('snapshot_id', sa.String),
                          sa.column('document_id', sa.Integer), sa.column('version_id', sa.Integer))
    # Keyset batches keep memory bounded even on drivers that buffer result sets.
    after = ''
    while True:
        batch = connection.execute(sa.select(snapshots).where(snapshots.c.id > after)
                                   .order_by(snapshots.c.id).limit(200)).mappings().all()
        if not batch:
            break
        rows = []
        for snapshot in batch:
            payload = snapshot['payload'] or {}
            evidence = [*payload.get('document_dependencies', []),
                        *payload.get('data', {}).get('search_documents', {}).get('citations', [])]
            keys = {(int(item['document_id']), int(item.get('version_id') or 0))
                    for item in evidence if item.get('document_id') is not None}
            rows.extend({'snapshot_id': snapshot['id'], 'document_id': doc, 'version_id': version}
                        for doc, version in sorted(keys))
        if rows:
            connection.execute(references.insert(), rows)
        after = batch[-1]['id']


def _chunk_constraint(create):
    if create:
        op.create_unique_constraint('uq_document_chunk_ordinal', 'document_chunks', ['version_id', 'ordinal'])
    else:
        op.drop_constraint('uq_document_chunk_ordinal', 'document_chunks', type_='unique')


def upgrade():
    connection = op.get_bind()
    _repair_legacy_triggers()
    op.create_table('context_document_references',
        sa.Column('snapshot_id', sa.String(36), nullable=False),
        sa.Column('document_id', sa.Integer(), nullable=False),
        sa.Column('version_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['snapshot_id'], ['context_snapshots.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('snapshot_id', 'document_id', 'version_id'))
    op.create_index('ix_context_document_references_document_id', 'context_document_references', ['document_id'])
    op.add_column('advisor_messages', sa.Column('context_purged', sa.Boolean(), server_default='0', nullable=False))
    op.add_column('document_versions', sa.Column('lease_owner', sa.String(36), nullable=True))
    op.add_column('document_versions', sa.Column('lease_expires_at', sa.DateTime(timezone=True), nullable=True))
    chunks = sa.table('document_chunks', sa.column('id', sa.Integer), sa.column('version_id', sa.Integer),
                      sa.column('ordinal', sa.Integer))
    keep = sa.select(sa.func.min(chunks.c.id)).group_by(chunks.c.version_id, chunks.c.ordinal)
    connection.execute(chunks.delete().where(chunks.c.id.not_in(keep)))
    _chunk_constraint(True)
    _backfill_references(connection)


def downgrade():
    _chunk_constraint(False)
    op.drop_column('document_versions', 'lease_expires_at')
    op.drop_column('document_versions', 'lease_owner')
    op.drop_column('advisor_messages', 'context_purged')
    op.drop_index('ix_context_document_references_document_id', table_name='context_document_references')
    op.drop_table('context_document_references')
    # Append-only protection is also required by0002 and must survive downgrade.
