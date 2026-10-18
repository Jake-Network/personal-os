"""Previous-head data survives provenance backfill and chunk/job constraints."""
from datetime import UTC, datetime

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, create_engine, event, inspect, select, text
from sqlalchemy.exc import IntegrityError


def test_review_revision_backfills_provenance_and_preserves_old_snapshot_ids(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'review.db'}")
    event.listen(engine, 'connect', lambda conn, rec: conn.execute('PRAGMA foreign_keys=ON'))
    config = Config('alembic.ini')
    now = datetime.now(UTC)
    with engine.begin() as connection:
        config.attributes['connection'] = connection
        command.upgrade(config, '6581e3048ce0')
        metadata = MetaData()
        metadata.reflect(connection)
        documents, versions, chunks = (metadata.tables[name] for name in ('documents', 'document_versions', 'document_chunks'))
        connection.execute(documents.insert().values(id=1, title='old', categories=['career'], kind='resume',
            sharing_enabled=True, active_version_id=1, created_at=now, updated_at=now))
        connection.execute(versions.insert().values(id=1, document_id=1, filename='r.txt', content_hash='hash', content=b'raw',
            status='ready', embedding_model='model', embedding_dimensions=3, created_at=now, updated_at=now))
        for ident in (6, 7):
            connection.execute(chunks.insert().values(id=ident, version_id=1, ordinal=0, text='original excerpt', embedding=[1,0,0]))
        payloads = {
            'direct': {'data': {'search_documents': {'citations': [{'document_id': 1, 'version_id': 1, 'ref': 'document_chunks:7', 'text': 'original excerpt'}]}}},
            'derived': {'document_dependencies': [{'document_id': 1, 'version_id': 1}]},
            'unrelated': {'data': {}},
        }
        snapshots = metadata.tables['context_snapshots']
        for ident, payload in payloads.items():
            connection.execute(snapshots.insert().values(id=ident, generated_at=now, context_categories=['career'],
                excluded_categories=[], record_references=[], source_updated_at={}, data_quality_flags=[], payload=payload, content_hash=ident))
        command.upgrade(config, 'head')
        command.check(config)
        assert connection.execute(select(snapshots.c.id, snapshots.c.payload)).all() == list(payloads.items())
        assert connection.execute(text('SELECT snapshot_id, document_id, version_id FROM context_document_references ORDER BY snapshot_id')).all() == [('derived',1,1),('direct',1,1)]
        assert connection.execute(text('SELECT id FROM document_chunks')).scalars().all() == [6]
        result = connection.execute(chunks.insert().values(version_id=1, ordinal=1, text='new', embedding=[1,0,0]))
        assert result.inserted_primary_key[0] > 7
        with pytest.raises(IntegrityError):
            with connection.begin_nested():
                connection.execute(chunks.insert().values(version_id=1, ordinal=1, text='duplicate', embedding=[1,0,0]))
        command.downgrade(config, '6581e3048ce0')
        assert not inspect(connection).has_table('context_document_references')
        command.upgrade(config, 'head')
        command.check(config)
    engine.dispose()
