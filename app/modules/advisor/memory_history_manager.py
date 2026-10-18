"""Local history retrieval. Every derived item is checked against its live sources."""
import re
import hashlib
import math
from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, defer

from app.enums.context_category import ALL_CATEGORIES, Category
from app.modules.context.history_privacy_manager import history_privacy_manager
from app.modules.database.model import (AdvisorConversation, AdvisorMessage, ContextSnapshot,
    ConversationSummary, DocumentVersion, HistorySearchIndex, ConversationLink, MemoryRevision, PersonalMemory)
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
            if any(not record_allowed(session, r.get("table"), r.get("id")) or not record_exists(session, r.get("table"), r.get("id")) or not reference_generation_matches(session, r) for r in snapshot.record_references):
                return False
            dependencies = [r for r in snapshot.record_references if r.get("table") in {"memory_revisions", "personal_memories", "advisor_messages", "conversation_summaries", "career_records", "decision_journal"}]
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
        elif table == "conversation_summaries":
            summary = session.get(ConversationSummary, key)
            if summary is None or not source_allowed(session, summary.source_references, excluded, seen, memo, document_scope):
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
                if holding is None or not source_allowed(session, [{"table": "accounts", "id": holding.account_id}], excluded, seen, memo, document_scope):
                    return False
        else:
            return False
        memo[(table, ref.get("id"))] = True
        seen.discard((table, ref.get("id")))
    return True


def latest_revision(session, memory_id):
    return session.scalar(select(MemoryRevision).where(MemoryRevision.memory_id == memory_id).order_by(MemoryRevision.revision.desc()).limit(1))


def relevant_memories(session, query, allowed, at):
    excluded = frozenset(ALL_CATEGORIES) - allowed
    terms = set(re.findall(r"[\w가-힣]{2,}", query.casefold()))
    result = []
    for memory in session.scalars(select(PersonalMemory).where(PersonalMemory.status == "confirmed")):
        revisions = list(session.scalars(select(MemoryRevision).where(MemoryRevision.memory_id == memory.id,
            MemoryRevision.status == "confirmed").order_by(MemoryRevision.revision.desc())))
        # An explicit validity interval uses the user's time semantics, never guessed dates.
        revision = next((r for r in revisions if (r.valid_from <= at if r.valid_from else r.created_at <= at)), None)
        if revisions and (revision is None or revision.valid_until is not None and at >= revision.valid_until):
            continue
        ref = {"table": "memory_revisions", "id": revision.id} if revision else {"table": "personal_memories", "id": memory.id}
        if not source_allowed(session, [ref], excluded):
            continue
        item = revision or memory
        text = item.content.casefold()
        scope = getattr(item, "scope", None)
        score = sum(term in text for term in terms)
        if scope and scope.casefold() not in query.casefold():
            continue
        # Constraints always survive relevance selection. No arbitrary top-k truncation.
        if item.kind in {"constraint", "priority", "profile"} or score:
            result.append((memory, revision))
    return result


class MemoryHistoryManager:
    def revisions(self, session, memory_id):
        if session.get(PersonalMemory, memory_id) is None:
            raise LookupError("memory not found")
        return list(session.scalars(select(MemoryRevision).where(MemoryRevision.memory_id == memory_id).order_by(MemoryRevision.revision)))

    def revise(self, session, memory_id, body):
        memory = session.scalar(select(PersonalMemory).where(PersonalMemory.id == memory_id).with_for_update())
        if memory is None:
            raise LookupError("memory not found")
        if memory.status != "confirmed":
            raise ValueError("confirm the proposed memory before revising it")
        current = latest_revision(session, memory_id)
        number = current.revision if current else 0
        if number != body.expected_revision:
            raise ValueError("memory revision changed; reload before editing")
        if body.valid_from and body.valid_from.tzinfo is None or body.valid_until and body.valid_until.tzinfo is None or body.review_on and body.review_on.tzinfo is None:
            raise ValueError("memory dates require a timezone")
        if body.valid_from and body.valid_until and body.valid_until <= body.valid_from:
            raise ValueError("valid_until must be after valid_from")
        if body.source_references and not source_allowed(session, body.source_references):
            raise ValueError("source unavailable or restricted")
        # Capture pre-versioning records before changing their compatibility projection.
        if current is None:
            session.add(MemoryRevision(memory_id=memory.id, revision=0, kind=memory.kind, content=memory.content,
                status=memory.status, confirmed_at=memory.confirmed_at, created_at=memory.created_at,
                source_references=[{"table": "advisor_messages", "id": memory.source_message_id}] if memory.source_message_id else []))
        sources = list(current.source_references) if current else ([{"table": "advisor_messages", "id": memory.source_message_id}] if memory.source_message_id else [])
        for ref in body.source_references:
            if ref not in sources:
                sources.append(ref)
        from app.modules.context.record_privacy import stamp_references
        revision = MemoryRevision(memory_id=memory.id, revision=number + 1, status="confirmed",
            source_references=stamp_references(session, sources), confirmed_at=datetime.now(UTC),
            **body.model_dump(exclude={"expected_revision", "source_references"}))
        session.add(revision)
        memory.kind, memory.content = body.kind, body.content
        memory.confirmed_at = revision.confirmed_at
        session.commit()
        return revision

    def summaries(self, session, conversation_id):
        return list(session.scalars(select(ConversationSummary).where(ConversationSummary.conversation_id == conversation_id).order_by(ConversationSummary.id.desc())))

    def summarize(self, session, conversation_id, body):
        rows = list(session.scalars(select(AdvisorMessage).where(AdvisorMessage.conversation_id == conversation_id,
            AdvisorMessage.status == "complete").order_by(AdvisorMessage.id)))
        rows = [m for m in rows if (body.first_message_id is None or m.id >= body.first_message_id) and (body.last_message_id is None or m.id <= body.last_message_id)]
        if not rows:
            raise ValueError("no complete messages in requested range")
        existing = session.scalar(select(ConversationSummary).where(ConversationSummary.conversation_id == conversation_id,
            ConversationSummary.first_message_id == rows[0].id, ConversationSummary.last_message_id == rows[-1].id,
            ConversationSummary.generator == "local_extract_v1"))
        if existing:
            return existing
        # Extractive drafts preserve exact words and references; no invented decisions or outcomes.
        from app.modules.context.record_privacy import stamp_references
        summary = ConversationSummary(conversation_id=conversation_id, first_message_id=rows[0].id,
            last_message_id=rows[-1].id, content="\n".join(f"[{m.role} message:{m.id}] {m.content[:1000]}" for m in rows),
            source_references=stamp_references(session, [{"table": "advisor_messages", "id": m.id} for m in rows]))
        session.add(summary)
        session.commit()
        return summary


memory_history_manager = MemoryHistoryManager()


def _history_hash(text):
    return hashlib.sha256(text.encode()).hexdigest()


async def index_history(session, after_id=0, limit=100):
    """Explicit, bounded rebuild of derived vectors using the configured local embedder."""
    from app.config import settings
    from app.modules.documents import embedding
    rows = list(session.scalars(select(AdvisorMessage).where(AdvisorMessage.id > after_id,
        AdvisorMessage.status == "complete", AdvisorMessage.context_purged.is_(False)).order_by(AdvisorMessage.id).limit(limit)))
    if not rows:
        return {"indexed": 0, "next_after_id": after_id, "complete": True}
    vectors = await embedding.embed_texts([m.content[:8000] for m in rows])
    for message, vector in zip(rows, vectors):
        index = session.get(HistorySearchIndex, message.id)
        if index is None:
            index = HistorySearchIndex(message_id=message.id)
            session.add(index)
        index.content_hash, index.model = _history_hash(message.content), settings.embedding_model
        index.dimensions, index.vector = settings.embedding_dimensions, vector
        index.indexed_at = datetime.now(UTC)
    session.commit()
    return {"indexed": len(rows), "next_after_id": rows[-1].id, "complete": len(rows) < limit}


def relevant_history(session, query, conversation_id, excluded, options, limit=6):
    """Filter before local hybrid retrieval; index is always disposable and hash-checked."""
    from app.config import settings
    from app.modules.documents import embedding
    terms = list(dict.fromkeys(re.findall(r"[\w가-힣]{3,}", query)))[:12]
    scope = []
    if options.history_since:
        scope.append(AdvisorMessage.created_at >= options.history_since)
    if options.history_until:
        scope.append(AdvisorMessage.created_at < options.history_until)
    for kind, target in (("company", options.history_company), ("project", options.history_project), ("decision", options.history_decision)):
        if target is not None:
            scope.append(AdvisorMessage.conversation_id.in_(select(ConversationLink.conversation_id).where(
                ConversationLink.kind == kind, ConversationLink.target == str(target))))
    lexical = list(session.scalars(select(AdvisorMessage).options(defer(AdvisorMessage.content)).where(*scope,
        AdvisorMessage.conversation_id != conversation_id, AdvisorMessage.status == "complete",
        or_(*(AdvisorMessage.content.icontains(t, autoescape=True) for t in terms))).order_by(AdvisorMessage.id.desc()).limit(100))) if terms else []
    indexed_rows = list(session.execute(select(AdvisorMessage, HistorySearchIndex).options(defer(AdvisorMessage.content)).join(HistorySearchIndex,
        HistorySearchIndex.message_id == AdvisorMessage.id).where(AdvisorMessage.conversation_id != conversation_id,
        AdvisorMessage.status == "complete", *scope, HistorySearchIndex.model == settings.embedding_model,
        HistorySearchIndex.dimensions == settings.embedding_dimensions).order_by(AdvisorMessage.id.desc()).limit(500)))
    indexes = {m.id: index for m, index in indexed_rows}
    candidates = {m.id: m for m in [*lexical, *(m for m, _ in indexed_rows if m.id in indexes)]}
    safe, snapshots = [], {}
    for message in candidates.values():
        prefix = list(session.scalars(select(AdvisorMessage).options(defer(AdvisorMessage.content)).where(AdvisorMessage.conversation_id == message.conversation_id,
            AdvisorMessage.id <= message.id, AdvisorMessage.status == "complete").order_by(AdvisorMessage.id)))
        if message not in history_privacy_manager.filter(session, prefix, excluded).kept:
            continue
        if not source_allowed(session, [{"table": "advisor_messages", "id": message.id}], excluded):
            continue
        snapshot = session.get(ContextSnapshot, message.context_snapshot_id) if message.context_snapshot_id else None
        if snapshot:
            evidence = snapshot.payload.get("document_dependencies", []) + snapshot.payload.get("data", {}).get("search_documents", {}).get("citations", [])
            if evidence and (not options.document_search or any(options.document_ids and e["document_id"] not in options.document_ids for e in evidence)):
                continue
            snapshots[snapshot.id] = snapshot
        if message.id in indexes and indexes[message.id].content_hash != _history_hash(message.content):
            del indexes[message.id]
        safe.append(message)
    vector = None
    flags = []
    if any(m.id in indexes for m in safe):
        try:
            vector = embedding.embed_query(query[:4000])
        except Exception:
            flags.append({"code": "history_embedding_unavailable", "category": "system"})
    else:
        flags.append({"code": "history_embedding_index_required", "category": "system"})
    ranked = []
    for message in safe:
        lexical_score = sum(t.casefold() in message.content.casefold() for t in terms) / max(len(terms), 1)
        semantic_score = 0
        if vector and message.id in indexes:
            other = indexes[message.id].vector
            norm = math.hypot(*vector) * math.hypot(*other)
            semantic_score = sum(a * b for a, b in zip(vector, other)) / norm if norm else 0
        if lexical_score or semantic_score >= .35:
            ranked.append((lexical_score * .3 + semantic_score * .7, message))
    ranked.sort(key=lambda pair: (-pair[0], -pair[1].id))
    if len(ranked) > limit:
        flags.append({"code": "history_search_results_omitted", "category": "system", "count": len(ranked) - limit})
    if vector is None:
        flags.append({"code": "history_keyword_retrieval_only", "category": "system"})
    chosen = [m for _, m in ranked[:limit]]
    return list(reversed(chosen)), snapshots, flags



def require_live_request_sources(session, request):
    """Recheck after model resolution, at the final inference boundary."""
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


def relevant_experiences(session, query, excluded, options, limit=4):
    """Historical summaries and decisions are labeled records, never current domain facts."""
    from app.modules.context.types import ToolResult
    from app.modules.database.model import DecisionJournalEntry
    terms = list(dict.fromkeys(re.findall(r"[\w가-힣]{3,}", query)))[:12]
    if not terms:
        return ToolResult(data={"summaries": [], "decisions": []})
    scope = []
    for kind, target in (("company", options.history_company), ("project", options.history_project), ("decision", options.history_decision)):
        if target is not None:
            scope.append(select(ConversationLink.conversation_id).where(ConversationLink.kind == kind, ConversationLink.target == str(target)))
    summaries_query = select(ConversationSummary).where(or_(*(ConversationSummary.content.icontains(t, autoescape=True) for t in terms)))
    decisions_query = select(DecisionJournalEntry).where(or_(*(or_(DecisionJournalEntry.title.icontains(t, autoescape=True),
        DecisionJournalEntry.choice.icontains(t, autoescape=True), DecisionJournalEntry.rationale.icontains(t, autoescape=True)) for t in terms)))
    for conversation_ids in scope:
        summaries_query = summaries_query.where(ConversationSummary.conversation_id.in_(conversation_ids))
        decisions_query = decisions_query.where(DecisionJournalEntry.conversation_id.in_(conversation_ids))
    if options.history_since:
        summaries_query = summaries_query.where(ConversationSummary.created_at >= options.history_since)
        decisions_query = decisions_query.where(DecisionJournalEntry.decided_at >= options.history_since)
    if options.history_until:
        summaries_query = summaries_query.where(ConversationSummary.created_at < options.history_until)
        decisions_query = decisions_query.where(DecisionJournalEntry.decided_at < options.history_until)
    if options.history_decision is not None:
        decisions_query = decisions_query.where(DecisionJournalEntry.id == options.history_decision)
    document_scope = {"enabled": options.document_search, "document_ids": options.document_ids or []}
    summaries = [r for r in session.scalars(summaries_query.order_by(ConversationSummary.id.desc()).limit(100))
        if source_allowed(session, [{"table": "conversation_summaries", "id": r.id}], excluded, document_scope=document_scope)]
    decisions = [r for r in session.scalars(decisions_query.order_by(DecisionJournalEntry.decided_at.desc(), DecisionJournalEntry.id.desc()).limit(100))
        if source_allowed(session, [{"table": "decision_journal", "id": r.id}], excluded, document_scope=document_scope)]
    flags = []
    omitted = max(0, len(summaries) - limit) + max(0, len(decisions) - limit)
    if omitted:
        flags.append({"code": "past_experience_results_omitted", "category": "system", "count": omitted})
    summaries, decisions = summaries[:limit], decisions[:limit]
    return ToolResult(data={
        "historical": True,
        "summaries": [{"ref": f"conversation_summaries:{r.id}", "conversation_id": r.conversation_id,
            "status": r.status, "generator": r.generator, "content": r.content,
            "first_message_id": r.first_message_id, "last_message_id": r.last_message_id,
            "created_at": r.created_at.isoformat(), "interpretation": "local_extractive_draft_not_confirmed_facts"}
            for r in summaries],
        "decisions": [{"ref": f"decision_journal:{r.id}", "conversation_id": r.conversation_id,
            "title": r.title, "decided_at": r.decided_at.isoformat(), "choice": r.choice,
            "rationale": r.rationale, "alternatives": r.alternatives,
            "expected_outcome": r.expected_outcome, "actual_outcome": r.actual_outcome,
            "interpretation": "historical_decision_not_current_state_or_prediction"} for r in decisions]},
        refs=[{"table": "conversation_summaries", "id": r.id} for r in summaries]
            + [{"table": "decision_journal", "id": r.id} for r in decisions], flags=flags)
