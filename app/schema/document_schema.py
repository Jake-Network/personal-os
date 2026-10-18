from datetime import date, datetime
from pydantic import BaseModel, Field
from app.enums.context_category import Category


class DocumentPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    categories: list[Category] | None = Field(default=None, min_length=1, max_length=7)
    kind: str | None = Field(default=None, min_length=1, max_length=64)
    sharing_enabled: bool | None = None


class DocumentItem(BaseModel):
    id: int
    title: str
    categories: list[str]
    kind: str
    sharing_enabled: bool
    application_id: int | None
    goal_id: int | None
    as_of: date | None
    status: str
    error: str | None
    active_version_id: int | None
    latest_version_id: int | None
    filename: str | None
    created_at: datetime
    updated_at: datetime
