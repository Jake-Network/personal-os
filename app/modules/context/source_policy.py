"""Live provenance policy shared by domain tools and model transport."""
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.enums.context_category import Category
from app.modules.database.model import (
    AdvisorMessage, ContextSnapshot, ConversationSummary, DocumentVersion,
    MemoryRevision, PersonalMemory,
)
from app.modules.documents.retrieval import visible_documents


def source_allowed(session: Session, refs: list[dict], excluded=frozenset(), seen=None, memo=None, document_scope=None) -> bool:
    """Unknown, removed, purged, or now restricted dependencies fail closed recursively."""
    seen = set() if seen is None else set(seen)
    memo = {} if memo is None else memo
    if len(seen) > 200:
        return False
    for ref in refs:
        table, key = ref.get("table"), ref.get("id")
        from app.modules.context.record_privacy import record_allowed, record_exists, reference_generation_matches, RECORD_CATEGORY, TABLES
        if RECORD_CATEGORY.get(table) in {str(c) for c in excluded}:
            return False
        if deleted_procedure(session, ref):
            # Only the categories captured with the reference remain to taint what depended on it.
            if "categories" not in ref or set(ref["categories"]) & {str(c) for c in excluded}:
                return False
            continue
        if not record_allowed(session, table, key) or not record_exists(session, table, key) or not reference_generation_matches(session, ref):
            return False
        if memo.get((table, key)):
            continue
        if not isinstance(key, (int, str)) or (table, key) in seen:
            return False
        seen.add((table, key))
        if table == "advisor_messages":
            message = session.get(AdvisorMessage, key)
            if message is None or message.status != "complete" or message.context_purged:
                return False
            if message.context_snapshot_id is None:
                if excluded:
                    return False
            elif not source_allowed(session, [{"table": "context_snapshots", "id": message.context_snapshot_id}], excluded, seen, memo, document_scope):
                return False
        elif table == "context_snapshots":
            snapshot = session.get(ContextSnapshot, key)
            if snapshot is None or snapshot.payload.get("source_purged"):
                return False
            derived_ids = snapshot.payload.get("derived_snapshot_ids", [])
            if not isinstance(derived_ids, list) or any(not isinstance(value, str) for value in derived_ids):
                return False
            # Plans, summaries, and comparison results carry every snapshot that
            # informed them to the final transport boundary, including on resume.
            if not source_allowed(session, [{"table": "context_snapshots", "id": value}
                    for value in derived_ids], excluded, seen, memo, document_scope):
                return False
            categories = set(snapshot.context_categories) | set(snapshot.payload.get("history_categories", [])) | set(snapshot.payload.get("document_categories", []))
            if categories & {str(c) for c in excluded} or (excluded and snapshot.payload.get("history_provenance_unknown")):
                return False
            evidence = snapshot.payload.get("document_dependencies", []) + snapshot.payload.get("data", {}).get("search_documents", {}).get("citations", [])
            for evidence_ref in evidence:
                if document_scope and (not document_scope.get("enabled", True) or document_scope.get("document_ids") and evidence_ref["document_id"] not in document_scope["document_ids"]):
                    return False
                if not visible_documents(session, document_ids=[evidence_ref["document_id"]], excluded_categories=excluded):
                    return False
                version = session.get(DocumentVersion, evidence_ref["version_id"])
                if version is None or version.document_id != evidence_ref["document_id"]:
                    return False
            # Catalog entries were only offered, never used: checked at transport (outbound), not as history.
            evidence_refs = [r for r in snapshot.record_references if r.get("role") != "catalog"]
            if any(not deleted_procedure(session, r) and (not record_allowed(session, r.get("table"), r.get("id")) or not record_exists(session, r.get("table"), r.get("id")) or not reference_generation_matches(session, r)) for r in evidence_refs):
                return False
            dependencies = [r for r in evidence_refs if r.get("table") in {"memory_revisions", "personal_memories", "advisor_messages", "conversation_summaries", "career_records", "decision_journal", "decision_reviews", "financial_transactions", "holdings", "playbook_revisions"}]
            if not source_allowed(session, dependencies, excluded, seen, memo, document_scope):
                return False
        elif table in {"personal_memories", "memory_revisions"}:
            memory = session.get(PersonalMemory, key) if table == "personal_memories" else None
            revision = session.get(MemoryRevision, key) if table == "memory_revisions" else latest_revision(session, key)
            if table == "memory_revisions":
                memory = session.get(PersonalMemory, revision.memory_id) if revision else None
            if memory is None or memory.status != "confirmed" or not record_allowed(session, "personal_memories", memory.id):
                return False
            current = latest_revision(session, memory.id)
            if current and (not current.external_allowed or current.status != "confirmed"):
                return False
            if revision and (not revision.external_allowed or revision.status != "confirmed" or not source_allowed(session, revision.source_references, excluded, seen, memo, document_scope)):
                return False
            if memory.source_message_id and not source_allowed(session, [{"table": "advisor_messages", "id": memory.source_message_id}], excluded, seen, memo, document_scope):
                return False
        elif table in {"documents", "document_versions"}:
            if table == "document_versions":
                version = session.get(DocumentVersion, key)
                if version is None:
                    return False
                key = version.document_id
            if document_scope and (not document_scope.get("enabled", True) or document_scope.get("document_ids") and key not in document_scope["document_ids"]):
                return False
            if not visible_documents(session, document_ids=[key], excluded_categories=excluded):
                return False
        elif table == "career_records":
            from app.modules.database.model import CareerRecord
            record = session.get(CareerRecord, key)
            if record is None or record.status != "confirmed" or not record.share_with_advisor or Category.CAREER in excluded:
                return False
            dependencies = list(record.source_references or [])
            if record.source != "user" and not dependencies:
                return False
            if record.parent_id:
                dependencies.append({"table": "career_records", "id": record.parent_id})
            if record.source_message_id:
                dependencies.append({"table": "advisor_messages", "id": record.source_message_id})
            if record.source_document_version_id:
                dependencies.append({"table": "document_versions", "id": record.source_document_version_id})
            if not source_allowed(session, dependencies, excluded, seen, memo, document_scope):
                return False
        elif table == "playbook_revisions":
            from app.modules.database.model import Playbook, PlaybookRevision
            revision = session.get(PlaybookRevision, key)
            playbook = session.get(Playbook, revision.playbook_id) if revision else None
            # A procedure is sent only while approved, shareable and free of now-restricted origins.
            if (revision is None or playbook is None or revision.source_purged
                    or revision.status not in {"active", "superseded"} or not playbook.external_allowed
                    or not record_allowed(session, "playbooks", playbook.id)
                    or set(revision.categories) & {str(c) for c in excluded}
                    or not source_allowed(session, revision.source_references, excluded, seen, memo, document_scope)):
                return False
        elif table == "conversation_summaries":
            summary = session.get(ConversationSummary, key)
            if summary is None or summary.status == 'source_purged' or not source_allowed(session, summary.source_references, excluded, seen, memo, document_scope):
                return False
        elif table == "financial_transactions":
            from app.modules.database.model import FinancialTransaction
            transaction = session.get(FinancialTransaction, key)
            if transaction is None:
                return False
            dependencies = [{"table": name, "id": transaction.payload[field]}
                for field, name in (("account_id", "accounts"), ("counterparty_account_id", "accounts"), ("holding_id", "holdings"))
                if transaction.payload.get(field) is not None]
            if transaction.reverses_id:
                dependencies.append({"table": "financial_transactions", "id": transaction.reverses_id})
            if not source_allowed(session, dependencies, excluded, seen, memo, document_scope):
                return False
        elif table == "decision_reviews":
            from app.modules.database.model.review_jobs import DecisionReviewRecord
            outcome = session.get(DecisionReviewRecord, key)
            if outcome is None:
                return False
            dependencies = [{"table": "decision_journal", "id": outcome.decision_id}]
            if outcome.context_snapshot_id:
                dependencies.append({"table": "context_snapshots", "id": outcome.context_snapshot_id})
            if not source_allowed(session, dependencies, excluded, seen, memo, document_scope):
                return False
        elif table == "decision_journal":
            from app.modules.database.model import DecisionJournalEntry
            decision = session.get(DecisionJournalEntry, key)
            if decision is None:
                return False
            if decision.context_snapshot_id:
                if not source_allowed(session, [{"table": "context_snapshots", "id": decision.context_snapshot_id}], excluded, seen, memo, document_scope):
                    return False
            elif excluded:
                return False
        elif table in TABLES:
            if table == "holdings":
                from app.modules.database.model import Holding
                holding = session.get(Holding, key)
                if holding is None or (holding.account_id is not None and not source_allowed(session, [{"table": "accounts", "id": holding.account_id}], excluded, seen, memo, document_scope)):
                    return False
        else:
            return False
        memo[(table, ref.get("id"))] = True
        seen.discard((table, ref.get("id")))
    return True


def latest_revision(session, memory_id):
    return session.scalar(select(MemoryRevision).where(MemoryRevision.memory_id == memory_id).order_by(MemoryRevision.revision.desc()).limit(1))


def deleted_procedure(session, ref) -> bool:
    """A playbook revision the user deleted (or whose ID now names another row)."""
    if ref.get("table") != "playbook_revisions" or not isinstance(ref.get("id"), int):
        return False
    from app.modules.context.record_privacy import record_exists, reference_generation_matches
    return not record_exists(session, "playbook_revisions", ref["id"]) or not reference_generation_matches(session, ref)


def procedures_sendable(session, refs, excluded) -> bool:
    """Procedure text in the request being sent: deleted ones are never sent, unlike history."""
    return not any(deleted_procedure(session, ref) for ref in refs) and source_allowed(session, refs, excluded)


def require_live_request_sources(session, request, *, outbound=True):
    """Recheck after model resolution, at the final inference boundary.

    `outbound=False` validates an earlier snapshot this request derives from. Only the
    snapshot actually being sent carries its procedures and catalog entries as payload, so
    only then are they held to the stricter send policy; as history they are provenance.
    """
    if not request.source_snapshot_id:
        return
    from app.modules.context.privacy_manager import privacy_manager
    from app.modules.llm.errors import AdvisorError
    excluded = privacy_manager.get_excluded(session) | frozenset(Category(c) for c in request.excluded_categories)
    # The gateway expires its session to observe concurrent policy changes. Reload all
    # direct history snapshots in a single query, keeping strong references for validation.
    snapshots = list(session.scalars(select(ContextSnapshot).where(or_(
        ContextSnapshot.id == request.source_snapshot_id,
        ContextSnapshot.id.in_(select(AdvisorMessage.context_snapshot_id).where(
            AdvisorMessage.id.in_(request.source_message_ids)))))))
    root_snapshot = next((row for row in snapshots if row.id == request.source_snapshot_id), None)
    document_scope = root_snapshot.payload.get("document_scope") if root_snapshot else None
    if not source_allowed(session, [{"table": "context_snapshots", "id": request.source_snapshot_id}], excluded, document_scope=document_scope):
        raise AdvisorError("상담 근거의 공유 설정이나 원본이 변경되었습니다. 전송 내용을 다시 확인하세요.", provider_code="source_policy_changed")
    if outbound and root_snapshot is not None:
        # Used procedures and catalog entries this run offered (titles and summaries) are both sent.
        procedures = [ref for ref in root_snapshot.record_references if ref.get("table") == "playbook_revisions"]
        if procedures and not procedures_sendable(session, procedures, excluded):
            raise AdvisorError("상담 절차의 공유 설정이 변경되었습니다.", provider_code="source_policy_changed")
