"""Record refs, data-quality flags and value formatting shared by the context tools."""

from datetime import UTC, datetime

from app.enums.context_category import Category
from app.modules.context.types import DataQualityFlag, RecordRef

TEXT_LIMIT = 1500


def record_ref(table: str, row) -> RecordRef:
    updated = getattr(row, "updated_at", None) or getattr(row, "as_of", None)
    return {"table": table, "id": row.id, "updated_at": iso_or_none(updated)}


def iso_or_none(value) -> str | None:
    return value.isoformat() if value is not None else None


def latest_of(*values) -> datetime | None:
    present = [as_aware(v) for v in values if v is not None]
    return max(present) if present else None


def as_aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def clip_text(text: str | None, limit: int = TEXT_LIMIT) -> str | None:
    if text is None or len(text) <= limit:
        return text
    return text[:limit] + " …[truncated]"


def quality_flag(code: str, category: Category, detail: str | None = None) -> DataQualityFlag:
    return {"code": code, "category": category.value, **({"detail": detail} if detail else {})}
