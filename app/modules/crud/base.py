from collections.abc import Sequence
from typing import Any, Generic, TypeVar

from pydantic import BaseModel
from sqlalchemy import Select, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.modules.database.model import Base

ModelType = TypeVar("ModelType", bound=Base)


class BaseCRUDHandler(Generic[ModelType]):
    """ORM-only access for one model. No business rules live here."""

    def __init__(self, model: type[ModelType]):
        self.model = model

    def get(self, session: Session, id: Any) -> ModelType | None:
        return session.get(self.model, id)

    def get_multiple_with_filters(
        self,
        session: Session,
        filters: Sequence[ColumnElement[bool]] = (),
        order_by: Sequence[Any] = (),
        limit: int | None = None,
    ) -> list[ModelType]:
        stmt: Select = select(self.model).where(*filters).order_by(*order_by)
        if limit is not None:
            stmt = stmt.limit(limit)
        return list(session.scalars(stmt))

    def get_first_with_filters(
        self, session: Session, filters: Sequence[ColumnElement[bool]] = (), order_by: Sequence[Any] = ()
    ) -> ModelType | None:
        rows = self.get_multiple_with_filters(session, filters, order_by, limit=1)
        return rows[0] if rows else None

    def create(self, session: Session, obj_in: BaseModel | dict[str, Any]) -> ModelType:
        data = obj_in.model_dump() if isinstance(obj_in, BaseModel) else obj_in
        obj = self.model(**data)
        session.add(obj)
        session.flush()
        return obj

    def update(self, session: Session, obj: ModelType, obj_in: BaseModel | dict[str, Any]) -> ModelType:
        data = obj_in.model_dump(exclude_unset=True) if isinstance(obj_in, BaseModel) else obj_in
        for field, value in data.items():
            setattr(obj, field, value)
        session.flush()
        return obj

    def delete(self, session: Session, obj: ModelType) -> None:
        from app.modules.context.record_privacy import invalidate_deleted_source
        invalidate_deleted_source(session, self.model.__tablename__, getattr(obj, "id", None))
        session.delete(obj)
        session.flush()
