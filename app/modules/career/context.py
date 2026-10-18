"""Career evidence uses the same live source-policy checks as memories and history."""
import re

from app.enums.context_category import ALL_CATEGORIES, Category
from app.modules.context.source_policy import source_allowed
from app.modules.context.records import latest_of, quality_flag, record_ref
from app.modules.context.types import ToolContext, ToolResult
from app.modules.crud.career_record_handler import career_record_handler


def rank_records(records, query):
    terms = set(re.findall(r"[\w가-힣]{2,}", query.casefold()))
    def score(row):
        text = " ".join(str(value or "") for value in [row.title, row.company, row.description,
            row.approach, row.outcome, row.lessons, *row.skills]).casefold()
        return sum(term in text for term in terms)
    return sorted(records, key=lambda row: (score(row), row.updated_at, row.id), reverse=True)


def get_career_records(ctx: ToolContext) -> ToolResult:
    excluded = frozenset(ALL_CATEGORIES) - ctx.allowed
    rows = [row for row in career_record_handler.list(ctx.session)
            if (not ctx.external_sharing and row.status == "confirmed")
            or (ctx.external_sharing and source_allowed(ctx.session, [{"table": "career_records", "id": row.id}], excluded))]
    selected = rank_records(rows, ctx.query)[:30]
    return ToolResult(
        data={"records": [{"ref": f"career_records:{row.id}", "kind": row.kind, "title": row.title,
            "parent_ref": f"career_records:{row.parent_id}" if row.parent_id else None,
            "company": row.company, "organization": row.organization, "role": row.role,
            "started_on": row.started_on, "ended_on": row.ended_on,
            "description": row.description, "approach": row.approach, "outcome": row.outcome,
            "lessons": row.lessons, "evidence_url": row.evidence_url, "skills": row.skills,
            "progress": row.progress, "source": row.source, "recorded_at": row.recorded_at.isoformat()}
            for row in selected], "date_note": "YYYY / YYYY-MM values preserve the recorded occurrence precision"},
        refs=[record_ref("career_records", row) for row in selected],
        source_updated_at=latest_of(*(row.updated_at for row in selected)),
        flags=[quality_flag("career_records_omitted", Category.CAREER, f"{len(rows) - len(selected)} records omitted by retrieval limit")]
              if len(rows) > len(selected) else [],
    )
