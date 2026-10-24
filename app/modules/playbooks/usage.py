"""What happened after a procedure was used, as counts that feed the learning loop.

A usage is the final answer whose snapshot carried the revision. Its outcome signals are the
user's rating of that answer, a correction in the user's next message, and decisions recorded
from that answer with a reviewed outcome. Only counts leave this module, never message text.
With `excluded` set (anything sent to a model), answers whose provenance is not currently
shareable are not counted; the local screen counts everything.
"""
import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.context.source_policy import source_allowed
from app.modules.database.model import (
    AdvisorMessage, AdvisorRecommendation, DecisionJournalEntry, Playbook, PlaybookRevision, PlaybookUsage,
)
from app.modules.database.model.advisor_runtime import AdvisorRun
from app.modules.database.model.review_jobs import DecisionReviewRecord

CORRECTION = re.compile(r"아니(?:야|라|요)|틀렸|잘못\s*(?:됐|되었|계산|이해)|정정|다시\s*(?:계산|생각|확인)|그게\s*아니|사실은")
RECENT_USES = 50


def _empty() -> dict:
    return {"uses": 0, "counted": 0, "positive_ratings": 0, "negative_ratings": 0, "corrected_next_turn": 0,
            "decisions_reviewed": 0}


def outcomes(session: Session, playbook_ids, excluded=None) -> dict[int, dict]:
    """{playbook_id: counts over its most recent uses, also split by revision number}."""
    ids = list(dict.fromkeys(playbook_ids))
    result = {playbook_id: {**_empty(), "by_revision": {}} for playbook_id in ids}
    if not ids:
        return result
    memo = {}
    for playbook_id in ids:
        rows = session.execute(select(PlaybookRevision.revision, AdvisorRun.assistant_message_id)
            .join(PlaybookUsage, PlaybookUsage.revision_id == PlaybookRevision.id)
            .join(AdvisorRun, AdvisorRun.id == PlaybookUsage.run_id)
            .where(PlaybookRevision.playbook_id == playbook_id, AdvisorRun.assistant_message_id.is_not(None))
            .order_by(PlaybookUsage.id.desc()).limit(RECENT_USES)).all()
        summary = result[playbook_id]
        for revision, message_id in rows:
            bucket = summary["by_revision"].setdefault(str(revision), _empty())
            for counts in (summary, bucket):
                counts["uses"] += 1
            message = session.get(AdvisorMessage, message_id)
            if message is None or (excluded is not None and not source_allowed(
                    session, [{"table": "advisor_messages", "id": message_id}], excluded, memo=memo)):
                continue
            signals = _signals(session, message, excluded, memo)
            for counts in (summary, bucket):
                counts["counted"] += 1
                for key, value in signals.items():
                    counts[key] += value
    return result


def _signals(session, message, excluded, memo) -> dict:
    rating = session.scalar(select(AdvisorRecommendation.user_rating).where(
        AdvisorRecommendation.message_id == message.id).order_by(AdvisorRecommendation.id.desc()).limit(1))
    following = session.scalar(select(AdvisorMessage).where(
        AdvisorMessage.conversation_id == message.conversation_id, AdvisorMessage.id > message.id,
        AdvisorMessage.role == "user").order_by(AdvisorMessage.id).limit(1))
    corrected = following is not None and bool(CORRECTION.search(following.content)) and (
        excluded is None or source_allowed(session, [{"table": "advisor_messages", "id": following.id}], excluded, memo=memo))
    reviewed = session.scalar(select(func.count(func.distinct(DecisionJournalEntry.id))).select_from(DecisionJournalEntry)
        .join(DecisionReviewRecord, DecisionReviewRecord.decision_id == DecisionJournalEntry.id)
        .where(DecisionJournalEntry.source_message_id == message.id)) or 0
    return {"positive_ratings": int(rating == 1), "negative_ratings": int(rating == -1),
            "corrected_next_turn": int(corrected), "decisions_reviewed": reviewed}


def for_slugs(session: Session, slugs, excluded) -> dict[str, dict]:
    """Model-facing counts keyed by slug, for the reflection's existing playbooks."""
    pairs = dict(session.execute(select(Playbook.slug, Playbook.id).where(Playbook.slug.in_(list(slugs)))).all())
    counts = outcomes(session, pairs.values(), excluded)
    return {slug: {**counts[playbook_id], "interpretation": "counts_not_statistics"}
            for slug, playbook_id in pairs.items() if counts[playbook_id]["uses"]}


def used_by_previous_answer(session: Session, conversation_id: int, before_message_id: int) -> list[str]:
    """Slugs used by the answer right before a message, e.g. the one a correction refers to."""
    previous = session.scalar(select(AdvisorRun).where(
        AdvisorRun.conversation_id == conversation_id, AdvisorRun.status == "completed",
        AdvisorRun.assistant_message_id.is_not(None), AdvisorRun.assistant_message_id < before_message_id)
        .order_by(AdvisorRun.assistant_message_id.desc()).limit(1))
    if previous is None:
        return []
    return [item.get("slug") for item in (previous.result or {}).get("playbooks", []) if item.get("slug")]
