"""Use the same server-side database settings as FastAPI."""
from alembic import context
from sqlalchemy import create_engine

from app.config import settings
from app.modules.database.model import Base

config = context.config
url = config.attributes.get("database_url") or settings.resolved_database_url

def run():
    if context.is_offline_mode():
        context.configure(url=url, target_metadata=Base.metadata, literal_binds=True)
        with context.begin_transaction():
            context.run_migrations()
    else:
        with create_engine(url).connect() as connection:
            context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
            with context.begin_transaction():
                context.run_migrations()

run()
