"""Upgrade an existing PostgreSQL schema without rewriting personal data."""
import os
import uuid

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


def test_postgresql_document_upgrade_preserves_existing_rows():
    url = os.environ.get('TEST_DATABASE_URL', '')
    if not url.startswith('postgresql'):
        pytest.skip('Requires a disposable PostgreSQL database')
    schema = 'rag_upgrade_' + uuid.uuid4().hex
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            connection.execute(text(f'SET search_path TO "{schema}", public'))
            connection.commit()
            config = Config('alembic.ini')
            config.attributes.update(connection=connection, version_table_schema=schema)
            command.upgrade(config, '0004_portfolio_identity')
            connection.execute(text("INSERT INTO app_settings (key, value, updated_at) VALUES ('preserved', '{}', '2026-10-18')"))
            connection.commit()
            command.upgrade(config, 'head')
            command.check(config)
            assert connection.scalar(text("SELECT value FROM app_settings WHERE key='preserved'")) == {}
            command.downgrade(config, '0004_portfolio_identity')
            assert not inspect(connection).has_table('documents', schema=schema)
            command.upgrade(config, 'head')
            command.check(config)
            connection.commit()
    finally:
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        engine.dispose()
