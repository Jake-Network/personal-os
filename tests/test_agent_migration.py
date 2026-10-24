"""The agent migration is additive: existing schedules and conversations keep their meaning."""
from alembic import command
from sqlalchemy import create_engine, text

from app.modules.database.migration_manager import alembic_config


def test_upgrade_preserves_schedules_and_conversations(tmp_path):
    url = f"sqlite:///{tmp_path / 'agent.db'}"
    command.upgrade(alembic_config(url), "0015_decision_source_message")
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO advisor_conversations (id,title,created_at,updated_at) "
                                "VALUES (1,'기존 상담','2026-10-01','2026-10-01')"))
        connection.execute(text("INSERT INTO job_schedules (id,name,cadence,enabled,next_run_at,created_at) "
                                "VALUES (1,'월간 회고','month',1,'2026-11-01','2026-10-01')"))
    command.upgrade(alembic_config(url), "head")
    command.check(alembic_config(url))
    with engine.begin() as connection:
        assert connection.execute(text("SELECT origin, title FROM advisor_conversations")).one() == ("user", "기존 상담")
        row = connection.execute(text("SELECT kind, cadence, enabled, options, authorization FROM job_schedules")).one()
        assert row == ("period_review", "month", 1, "{}", None)
    engine.dispose()

    from app.modules.database import Database
    from app.modules.database.model import JobSchedule
    database = Database()
    database.init(url)
    with database.session() as session:
        assert session.get(JobSchedule, 1).options == {}
    database.engine.dispose()

    command.downgrade(alembic_config(url), "0015_decision_source_message")
    engine = create_engine(url)
    with engine.begin() as connection:
        assert connection.execute(text("SELECT name FROM job_schedules")).scalar() == "월간 회고"
        tables = {row[0] for row in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
        assert not tables & {"playbooks", "playbook_revisions", "playbook_usages", "inbox_items"}
    engine.dispose()
