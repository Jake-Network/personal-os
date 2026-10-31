"""Collapsing FX history keeps the rate current valuation would have used."""
from alembic import command
from sqlalchemy import create_engine, text

from app.modules.database.migration_manager import alembic_config


def test_upgrade_keeps_the_current_rate_per_pair(postgres_url):
    config = alembic_config(postgres_url)
    command.upgrade(config, "0018_merge_advisor_records")
    engine = create_engine(postgres_url)
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO fx_rates (id, base, quote, rate, as_of) VALUES "
            "(1, 'USD', 'KRW', 1300, now() - interval '2 days'), "
            "(2, 'USD', 'KRW', 1400, now() - interval '1 hour'), "
            "(3, 'USD', 'KRW', 1500, now() + interval '1 day'), "
            "(4, 'JPY', 'KRW', 9.1, now() - interval '3 days')"
        ))
    command.upgrade(config, "head")
    command.check(config)
    with engine.begin() as connection:
        rows = connection.execute(text("SELECT id, base, rate FROM fx_rates ORDER BY id")).all()
        assert [(i, b, str(r)) for i, b, r in rows] == [(2, "USD", "1400.00000000"), (4, "JPY", "9.10000000")]
    command.downgrade(config, "0018_merge_advisor_records")
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO fx_rates (base, quote, rate, as_of) VALUES ('USD', 'KRW', 1410, now())"))
    engine.dispose()
