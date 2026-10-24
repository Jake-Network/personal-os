"""Local history retrieval. Every derived item is checked against its live sources."""
import re
import hashlib
import math
from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import defer

from app.modules.context.history_privacy_manager import history_privacy_manager
from app.modules.database.model import (AdvisorMessage, ContextSnapshot,
    ConversationSummary, HistorySearchIndex, ConversationLink, MemoryRevision, PersonalMemory)


# Compatibility imports preserve existing callers while policy lives in context.
from app.modules.context.source_policy import latest_revision, require_live_request_sources, source_allowed
from app.modules.context.memory_selection import relevant_memories


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


def _replayable(session, message, excluded, options):
    """(allowed, snapshot): the cumulative turn filter, live provenance and document scope for one message."""
    prefix = list(session.scalars(select(AdvisorMessage).options(defer(AdvisorMessage.content)).where(AdvisorMessage.conversation_id == message.conversation_id,
        AdvisorMessage.id <= message.id, AdvisorMessage.status == "complete").order_by(AdvisorMessage.id)))
    if message not in history_privacy_manager.filter(session, prefix, excluded).kept:
        return False, None
    if not source_allowed(session, [{"table": "advisor_messages", "id": message.id}], excluded):
        return False, None
    snapshot = session.get(ContextSnapshot, message.context_snapshot_id) if message.context_snapshot_id else None
    if snapshot:
        evidence = snapshot.payload.get("document_dependencies", []) + snapshot.payload.get("data", {}).get("search_documents", {}).get("citations", [])
        if evidence and (not options.document_search or any(options.document_ids and e["document_id"] not in options.document_ids for e in evidence)):
            return False, None
    return True, snapshot


def _history_scope(options):
    """The user's period and linked-record filters for past-message retrieval."""
    scope = []
    if options.history_since:
        scope.append(AdvisorMessage.created_at >= options.history_since)
    if options.history_until:
        scope.append(AdvisorMessage.created_at < options.history_until)
    for kind, target in (("company", options.history_company), ("project", options.history_project), ("decision", options.history_decision)):
        if target is not None:
            scope.append(AdvisorMessage.conversation_id.in_(select(ConversationLink.conversation_id).where(
                ConversationLink.kind == kind, ConversationLink.target == str(target))))
    return scope


def relevant_history(session, query, conversation_id, excluded, options, limit=6):
    """Filter before local hybrid retrieval; index is always disposable and hash-checked."""
    from app.config import settings
    from app.modules.documents import embedding
    terms = list(dict.fromkeys(re.findall(r"[\w가-힣]{3,}", query)))[:12]
    scope = _history_scope(options)
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
        allowed, snapshot = _replayable(session, message, excluded, options)
        if not allowed:
            continue
        if snapshot:
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


SESSION_EXCERPT_CHARS = 600
SESSION_SEARCH_CHARS = 6000


def search_sessions(session, query, conversation_id, excluded, options, max_sessions=4, per_session=4):
    """Past consultations as question-answer pairs, grouped by conversation (Hermes-style session search).

    Matching reuses the filtered hybrid history retrieval. Each matched turn brings its
    counterpart (the question for an answer, the answer for a question) only if that message
    passes the same sharing checks. Titles are omitted: they may echo a withheld first message.
    Returns (data, refs, flags); the caller records refs as snapshot provenance.
    """
    limit = max_sessions * per_session
    semantic, _, flags = relevant_history(session, query, conversation_id, excluded, options, limit=limit)
    flags = [flag for flag in flags if flag["code"] != "history_search_results_omitted"]
    # The model writes a short search query, and Korean keywords are often two syllables:
    # match those too, then apply the same per-message sharing checks.
    terms = list(dict.fromkeys(re.findall(r"[\w가-힣]{2,}", query)))[:12]
    lexical = list(session.scalars(select(AdvisorMessage).where(*_history_scope(options),
        AdvisorMessage.conversation_id != conversation_id, AdvisorMessage.status == "complete",
        or_(*(AdvisorMessage.content.icontains(t, autoescape=True) for t in terms))).order_by(AdvisorMessage.id.desc()).limit(100))) if terms else []
    scored = {message.id: (0.5, message) for message in semantic}
    for message in lexical:
        hits = sum(t.casefold() in message.content.casefold() for t in terms) / len(terms)
        if message.id in scored or _replayable(session, message, excluded, options)[0]:
            scored[message.id] = (scored.get(message.id, (0, None))[0] + hits, message)
    matches = [message for _, message in sorted(scored.values(), key=lambda pair: (-pair[0], -pair[1].id))[:limit]]
    order, grouped = [], {}
    for message in matches:
        if message.conversation_id not in grouped:
            order.append(message.conversation_id)
            grouped[message.conversation_id] = {}
        turn = grouped[message.conversation_id]
        turn[message.id] = message
        counterpart = session.scalar(select(AdvisorMessage).where(
            AdvisorMessage.conversation_id == message.conversation_id, AdvisorMessage.status == "complete",
            *((AdvisorMessage.id < message.id, AdvisorMessage.role == "user") if message.role == "assistant"
              else (AdvisorMessage.id > message.id, AdvisorMessage.role == "assistant")))
            .order_by(AdvisorMessage.id.desc() if message.role == "assistant" else AdvisorMessage.id).limit(1))
        if counterpart is not None and counterpart.id not in turn and _replayable(session, counterpart, excluded, options)[0]:
            turn[counterpart.id] = counterpart
    sessions, refs, used, omitted, truncated = [], [], 0, 0, 0
    for conversation in order:
        if len(sessions) >= max_sessions:
            omitted += 1
            continue
        items = []
        for message in sorted(grouped[conversation].values(), key=lambda m: m.id)[:per_session * 2]:
            content = message.content
            if len(content) > SESSION_EXCERPT_CHARS:
                content, truncated = content[:SESSION_EXCERPT_CHARS] + " …(생략)", truncated + 1
            items.append({"ref": f"advisor_messages:{message.id}", "role": message.role,
                          "created_at": message.created_at.isoformat(), "content": content, "historical": True})
        cost = sum(len(item["content"]) for item in items)
        if used + cost > SESSION_SEARCH_CHARS:
            omitted += 1
            continue
        used += cost
        sessions.append({"conversation_id": conversation, "historical": True, "messages": items,
                         "last_activity": items[-1]["created_at"]})
        refs.extend({"table": "advisor_messages", "id": int(item["ref"].split(":")[1])} for item in items)
    if omitted:
        flags.append({"code": "session_search_results_omitted", "category": "system", "count": omitted})
    if truncated:
        flags.append({"code": "session_search_excerpts_truncated", "category": "system", "count": truncated})
    if not sessions:
        flags.append({"code": "session_search_no_match", "category": "system"})
    return ({"historical": True, "interpretation": "past_sessions_not_current_facts", "sessions": sessions},
            refs, flags)
