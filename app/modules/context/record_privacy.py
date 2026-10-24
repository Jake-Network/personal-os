"""Conservative per-record external sharing policy, independent of local UI access.

A tool's aggregate can disclose a restricted row. Until every calculator supports scoped
partial results, omit that tool entirely before fetching its records, with an explicit flag.
"""
from app.modules.crud import app_setting_handler, audit_log_handler

KEY = "privacy.local_only_records"
TABLES = frozenset({"accounts", "holdings", "other_assets", "liabilities", "cashflow_entries", "financial_transactions",
    "planned_expenses", "job_applications", "interviews", "career_criteria", "career_records",
    "calendar_events", "tasks", "goals", "workout_logs", "personal_memories", "documents",
    "decision_journal", "advisor_messages", "conversation_summaries", "playbooks", "playbook_revisions"})
TOOL_TABLES = {
    "get_accounts_summary": {"accounts", "other_assets", "liabilities", "holdings"},
    "get_cashflow_summary": {"cashflow_entries", "financial_transactions", "planned_expenses", "accounts", "holdings"},
    "get_monthly_asset_history": {"accounts", "holdings", "other_assets", "liabilities"},
    "get_portfolio_summary": {"holdings", "accounts"},
    "get_market_data": {"holdings"}, "get_relevant_news": {"holdings"},
    "get_job_applications": {"job_applications", "career_criteria"},
    "get_interview_schedule": {"interviews", "job_applications"},
    "get_calendar_events": {"calendar_events", "tasks", "interviews", "job_applications"},
    "get_tasks": {"tasks"}, "get_goals": {"goals"}, "get_health_summary": {"workout_logs"},
    # These tools individually re-check source and sharing policy before serialization.
    "get_profile": set(), "get_career_records": set(),
}


def blocked(session):
    return app_setting_handler.get_value(session, KEY) or {}


def record_allowed(session, table, record_id=None):
    denied = blocked(session).get(table, [])
    # Aggregate refs have no ID: any restricted contributing record invalidates the aggregate.
    return not denied if record_id is None else str(record_id) not in denied


def tool_blocked(session, name):
    denied = blocked(session)
    return any(denied.get(table) for table in TOOL_TABLES.get(name, TABLES))


def set_record_policy(session, table, record_id, external_allowed):
    from app.modules.database.model import Base
    if table not in TABLES:
        raise ValueError("unsupported personal record table")
    model = next((mapper.class_ for mapper in Base.registry.mappers if mapper.local_table.name == table), None)
    if model is None or session.get(model, record_id) is None:
        raise LookupError("personal record not found")
    policy = {key: list(value) for key, value in blocked(session).items()}
    values = set(policy.get(table, []))
    if external_allowed:
        values.discard(str(record_id))
    else:
        values.add(str(record_id))
    policy[table] = sorted(values)
    app_setting_handler.set_value(session, KEY, policy)
    audit_log_handler.record(session, "user", "privacy.record.update", f"{table}:{record_id}", {"external_allowed": external_allowed})
    session.commit()
    return {"table": table, "id": record_id, "external_allowed": external_allowed}


def record_exists(session, table, record_id):
    from app.modules.database.model import Base
    from sqlalchemy import select
    if table not in TABLES or record_id is None:
        return True
    model = next((mapper.class_ for mapper in Base.registry.mappers if mapper.local_table.name == table), None)
    return model is not None and session.scalar(select(model.id).where(model.id == record_id)) is not None


def aggregate_source_ids(session, refs):
    """Keep row identities for legacy aggregate-only tool refs, so deletion stays visible."""
    from app.modules.database.model import Base
    from sqlalchemy import select
    models = {mapper.local_table.name: mapper.class_ for mapper in Base.registry.mappers}
    result = []
    for table in {ref.get("table") for ref in refs if ref.get("id") is None} & TABLES:
        model = models.get(table)
        if model is not None:
            result.extend({"table": table, "id": key} for key in session.scalars(select(model.id)))
    return result


RECORD_CATEGORY = {
    **dict.fromkeys(("accounts", "other_assets", "liabilities", "cashflow_entries", "financial_transactions", "planned_expenses"), "financial"),
    "holdings": "investment", **dict.fromkeys(("career_records", "job_applications", "interviews", "career_criteria"), "career"),
    "calendar_events": "calendar", "tasks": "calendar", "goals": "goals", "workout_logs": "health",
    "personal_memories": "profile", "memory_revisions": "profile",
}


def invalidate_deleted_source(session, table, record_id):
    """Permanently taint captured evidence before its source record is deleted."""
    from sqlalchemy import select, update
    from app.modules.database.model import ContextSnapshot, AdvisorMessage, MemoryRevision
    identities = {(table, str(record_id))}
    if table == "personal_memories":
        identities.update(("memory_revisions", str(key)) for key in session.scalars(select(MemoryRevision.id).where(MemoryRevision.memory_id == record_id)))
    if table == "advisor_conversations":
        identities.update(("advisor_messages", str(key)) for key in session.scalars(select(AdvisorMessage.id).where(AdvisorMessage.conversation_id == record_id)))
    # A procedure is not personal evidence. Deleting it removes the procedure and its usage
    # records; answers that used it keep their snapshots, and the origin categories stamped on
    # each reference keep tainting them (source_policy.deleted_procedure).
    if table in {"playbooks", "playbook_revisions"}:
        return
    if table not in TABLES and table != "advisor_conversations":
        return
    from app.modules.playbooks.playbook_manager import purge_sources
    purge_sources(session, identities)
    for snapshot in session.scalars(select(ContextSnapshot)):
        hit = any((ref.get("table"), str(ref.get("id"))) in identities
                  or ref.get("table") == table and ref.get("id") is None
                  for ref in snapshot.record_references)
        if table == "documents":
            hit |= any(str(ref.get("document_id")) == str(record_id) for ref in snapshot.payload.get("document_dependencies", []))
        if hit and not snapshot.payload.get("source_purged"):
            snapshot.payload = {**snapshot.payload, "source_purged": True}
            session.execute(update(AdvisorMessage).where(AdvisorMessage.context_snapshot_id == snapshot.id).values(context_purged=True))


def stamp_references(session, refs):
    """Attach a server-read row generation to new provenance, independent of integer IDs."""
    from app.modules.database.model import Base
    models = {mapper.local_table.name: mapper.class_ for mapper in Base.registry.mappers}
    result = []
    for ref in refs:
        ref = dict(ref)
        model = models.get(ref.get("table"))
        if model is not None and ref.get("id") is not None and "source_created_at" not in ref:
            row = session.get(model, ref["id"])
            created = next((getattr(row, key, None) for key in ("created_at", "recorded_at", "generated_at") if getattr(row, key, None)), None) if row else None
            if created:
                ref["source_created_at"] = created.isoformat()
            if ref.get("table") == "playbook_revisions" and row is not None and "categories" not in ref:
                # Kept with the reference so taint survives the procedure's deletion.
                ref["categories"] = sorted(row.categories or [])
        result.append(ref)
    return result


def reference_generation_matches(session, ref):
    if not ref.get("source_created_at"):
        return True  # Existing sources are invalidated by the deletion hook.
    return stamp_references(session, [{key: value for key, value in ref.items() if key != "source_created_at"}])[0].get("source_created_at") == ref["source_created_at"]
