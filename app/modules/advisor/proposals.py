"""Parsing of the proposal and memory blocks in model output, and of proposal payload values."""

import json
import re
from datetime import UTC, date, datetime

ALLOWED_ACTIONS = {"create_task", "calendar_update", "goal_update"}
MEMORY_KINDS = {"profile", "preference", "constraint", "priority"}
BLOCK_RE = re.compile(r"```(proposal|memory)\s*\n(.*?)\n```", re.DOTALL)


def extract_blocks(text: str) -> tuple[str, list[dict], list[dict]]:
    """Split model output into display text, action proposals and memory proposals."""
    proposals, memories = [], []
    for kind, raw in BLOCK_RE.findall(text):
        try:
            obj = json.loads(raw)
        except ValueError:
            continue
        if kind == "proposal" and isinstance(obj, dict) and obj.get("action") in ALLOWED_ACTIONS \
                and isinstance(obj.get("payload"), dict):
            proposals.append(obj)
        elif kind == "memory" and isinstance(obj, dict) and obj.get("kind") in MEMORY_KINDS \
                and isinstance(obj.get("content"), str) and obj["content"].strip():
            memories.append(obj)
    return BLOCK_RE.sub("", text).rstrip(), proposals, memories


def parse_date(value) -> date | None:
    return None if value in (None, "") else date.fromisoformat(str(value))


def parse_datetime(value) -> datetime | None:
    """ISO datetime; a naive value is taken as UTC."""
    if value in (None, ""):
        return None
    parsed = datetime.fromisoformat(str(value))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
