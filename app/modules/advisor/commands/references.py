"""Protect single-record deletions from cascading into linked user records."""
from sqlalchemy import select

from app.modules.database.model import Base, LocalPosition


def has_dependents(session, obj) -> bool:
    table = obj.__table__.name
    for mapper in Base.registry.mappers:
        if mapper.class_ is LocalPosition:
            continue  # Internal holding identity, not a separate user record.
        for column in mapper.columns:
            if any(foreign.column.table.name == table for foreign in column.foreign_keys):
                if session.scalar(select(mapper.class_).where(
                        getattr(mapper.class_, column.key) == obj.id).limit(1)) is not None:
                    return True
    return False
