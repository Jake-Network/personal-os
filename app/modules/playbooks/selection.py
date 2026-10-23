"""Which approved playbooks a consultation may see (progressive disclosure).

Level 0 is a catalog of titles and summaries for planning; level 1 is the full body of at
most two selected revisions, placed in the Context Package so the snapshot records which
version informed an answer. Selection is deterministic: explicit choice first, then
trigger matches. Sharing policy is checked per revision on every request.
"""
import re
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.context.source_policy import source_allowed
from app.modules.database.model import Playbook, PlaybookRevision

MAX_SELECTED = 2
SLASH = re.compile(r"^\s*/([a-z0-9가-힣][a-z0-9가-힣-]{1,39})(?=\s|$)")


def explicit_slug(message: str) -> str | None:
    """`/slug question` invokes a playbook, like a Hermes `/<skill-name>` command."""
    match = SLASH.match(message or "")
    return match.group(1) if match else None


def _eligible(session: Session, excluded) -> list[tuple[Playbook, PlaybookRevision]]:
    rows = session.execute(select(Playbook, PlaybookRevision).join(
        PlaybookRevision, PlaybookRevision.playbook_id == Playbook.id).where(
            Playbook.status == "active", PlaybookRevision.status == "active")
        .order_by(Playbook.slug)).all()
    return [(playbook, revision) for playbook, revision in rows
            if source_allowed(session, [{"table": "playbook_revisions", "id": revision.id}], excluded)]


def catalog(session: Session, excluded) -> list[dict]:
    return [{"slug": playbook.slug, "title": revision.title, "summary": revision.summary,
             "triggers": revision.triggers} for playbook, revision in _eligible(session, excluded)]


def catalog_context(session: Session, excluded, query: str, *, exclude_slugs=(), max_chars=4000):
    """Bound discovery metadata and retain the exact revisions offered to the model."""
    rows = [(p, r) for p, r in _eligible(session, excluded) if p.slug not in exclude_slugs]
    text = query.casefold()
    rows.sort(key=lambda pair: (-sum(term.casefold() in text for term in
        [pair[0].slug, *pair[1].triggers] if len(term) >= 2), pair[0].slug))
    items = {}
    for playbook, revision in rows:
        entry = {"slug": playbook.slug, "title": revision.title, "summary": revision.summary,
                 "triggers": revision.triggers}
        candidate = {**items, f"playbook_revisions:{revision.id}": entry}
        if len(items) < 12 and len(json.dumps(candidate, ensure_ascii=False)) <= max_chars:
            items = candidate
    omitted = len(rows) - len(items)
    flags = ([{"code": "playbook_catalog_omitted", "category": "system", "count": omitted}]
             if omitted else [])
    return {"procedural_not_facts": True, "items": items}, flags


def select_playbooks(session: Session, query: str, excluded, explicit_ids=(), explicit_slugs=()):
    """Return (revisions, flags). Explicitly requested but unavailable playbooks are disclosed."""
    eligible = _eligible(session, excluded)
    by_id = {playbook.id: (playbook, revision) for playbook, revision in eligible}
    by_slug = {playbook.slug: (playbook, revision) for playbook, revision in eligible}
    chosen, flags = [], []
    wanted_slugs = [slug for slug in dict.fromkeys(explicit_slugs) if slug]
    for slug in wanted_slugs:
        if slug in by_slug:
            chosen.append(by_slug[slug][1])
        elif session.scalar(select(Playbook.id).where(Playbook.slug == slug)) is not None:
            flags.append({"code": "playbook_unavailable", "category": "system", "detail": slug})
    for playbook_id in dict.fromkeys(explicit_ids):
        if playbook_id in by_id:
            chosen.append(by_id[playbook_id][1])
        else:
            flags.append({"code": "playbook_unavailable", "category": "system", "detail": str(playbook_id)})
    if not chosen and not explicit_ids and not wanted_slugs:
        text = (query or "").casefold()
        scored = []
        for playbook, revision in eligible:
            terms = [playbook.slug, *revision.triggers]
            score = sum(term.casefold() in text for term in terms if len(term) >= 2)
            if score:
                scored.append((-score, playbook.slug, revision))
        chosen = [revision for _, _, revision in sorted(scored)]
    unique = list({revision.id: revision for revision in chosen}.values())
    if len(unique) > MAX_SELECTED:
        flags.append({"code": "playbooks_limited", "category": "system",
                      "detail": f"{len(unique) - MAX_SELECTED}개는 한 번에 보낼 수 있는 한도로 제외"})
    return unique[:MAX_SELECTED], flags


def package_section(session: Session, revisions: list[PlaybookRevision]) -> dict:
    """A dict of entries, not a row list, so budgeting drops it whole instead of truncating steps."""
    slugs = dict(session.execute(select(Playbook.id, Playbook.slug).where(
        Playbook.id.in_([revision.playbook_id for revision in revisions]))).all())
    return {"procedural_not_facts": True,
            "items": {f"playbook_revisions:{revision.id}": {
                "playbook_id": revision.playbook_id, "slug": slugs.get(revision.playbook_id), "revision": revision.revision,
                "title": revision.title, "steps": revision.body} for revision in revisions}}


def record_usage(session: Session, run_id: str | None, snapshot_id: str | None) -> list[dict]:
    """Record which revisions the final answer's snapshot carried; the caller commits."""
    from app.modules.database.model import ContextSnapshot, PlaybookUsage
    snapshot = session.get(ContextSnapshot, snapshot_id) if snapshot_id else None
    items = (snapshot.payload.get("data", {}).get("playbooks", {}).get("items", {}) if snapshot else {})
    used = []
    for ref, item in items.items():
        revision_id = int(ref.removeprefix("playbook_revisions:"))
        revision = session.get(PlaybookRevision, revision_id)
        if revision is None:
            continue
        session.add(PlaybookUsage(revision_id=revision_id, run_id=run_id, context_snapshot_id=snapshot_id))
        used.append({"revision_id": revision_id, "playbook_id": revision.playbook_id, "slug": item.get("slug"),
                     "title": revision.title, "revision": revision.revision})
    return used
