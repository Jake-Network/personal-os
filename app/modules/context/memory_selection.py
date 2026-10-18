"""Confirmed-memory selection shared by context tools and the memory store."""
import re

from sqlalchemy import select

from app.enums.context_category import ALL_CATEGORIES
from app.modules.context.source_policy import source_allowed
from app.modules.database.model import MemoryRevision, PersonalMemory


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
