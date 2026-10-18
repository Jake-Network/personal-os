"""Read-only guard against running indexes under changed collation libraries."""
from sqlalchemy import create_engine, text


def collation_mismatches(connection):
    if connection.dialect.name != 'postgresql':
        return []
    database = connection.execute(text('''SELECT datname AS name, datcollversion AS stored,
        pg_database_collation_actual_version(oid) AS actual
        FROM pg_database WHERE datname = current_database()''')).mappings().all()
    explicit = connection.execute(text('''SELECT c.oid::regcollation::text AS name,
        c.collversion AS stored, pg_collation_actual_version(c.oid) AS actual
        FROM pg_collation c WHERE c.collversion IS NOT NULL AND EXISTS (
            SELECT 1 FROM pg_depend d WHERE d.refclassid = 'pg_collation'::regclass
            AND d.refobjid = c.oid)''')).mappings().all()
    return [dict(row) for row in [*database, *explicit] if row['stored'] != row['actual']]


def check_collations(connection):
    mismatches = collation_mismatches(connection)
    if mismatches:
        names = ', '.join(row['name'] for row in mismatches)
        raise RuntimeError(f'Database collation provider/version changed: {names}. '
                           'Keep the original OS/libc family or restore into a fresh database. '
                           'Rebuild affected indexes before refreshing collation versions; '
                           'see docs/documents.md. No automatic REINDEX or version refresh was performed.')


def main():
    from app.config import settings
    engine = create_engine(settings.resolved_database_url)
    try:
        with engine.connect() as connection:
            check_collations(connection)
        print('Collation versions match (or SQLite: not applicable).')
    finally:
        engine.dispose()


if __name__ == '__main__':
    main()
