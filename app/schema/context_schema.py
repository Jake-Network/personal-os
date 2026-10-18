from datetime import datetime

from pydantic import BaseModel

from app.enums.context_category import Category


class PrivacySettings(BaseModel):
    excluded_categories: list[Category]


class SnapshotResponse(BaseModel):
    context_snapshot_id: str
    conversation_id: int | None
    generated_at: datetime
    context_categories: list[str]
    excluded_categories: list[str]
    record_references: list[dict]
    source_updated_at: dict
    data_quality_flags: list[dict]
    payload: dict


class SnapshotCompareResponse(BaseModel):
    context_snapshot_id: str
    snapshot_generated_at: datetime
    compared_at: datetime
    changed_sections: list[str]
    unchanged_sections: list[str]


class RecordSharingUpdate(BaseModel):
    external_allowed: bool
