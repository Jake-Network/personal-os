"""Privacy over replayed conversation history (PRD §3.3, AC-19).

The Context Package is rebuilt from the DB on every turn, so category exclusions apply to it
directly. Replayed messages are different: an earlier assistant answer may quote balances from a
category the user has since excluded, and sending it again would leak that data even though the
new package omits it.

Every turn's context snapshot records the categories it drew on. A turn is *tainted* by those
categories and by every category of the turns before it, because those turns were replayed to the
model when it wrote the answer (an answer in a career-only turn can still repeat a balance it saw
two turns earlier). A message is withheld when its taint intersects the currently excluded
categories. Messages whose snapshot is unknown (deleted, or never recorded) are treated as tainted
by every category once anything is excluded. Withholding is per message but the taint only grows,
so what remains is always a clean prefix of the conversation: user/assistant pairs stay together.

Scope: this governs DB-origin context, i.e. data that reached the model through a Context Package.
Text the user typed directly (e.g. "my balance is 5M") is the user's own disclosure. It is not
classified by category; it is withheld only when its turn is tainted as above. Excluding a
category does not scan or redact free text the user typed into a turn that never used that
category.
"""

from collections.abc import Sequence

from app.enums.context_category import ALL_CATEGORIES, Category
from app.modules.context.types import HistoryDecision
from app.modules.database.model import AdvisorMessage


def decide_history(messages: Sequence[AdvisorMessage], snapshot_categories: dict[str, frozenset[Category]],
                   excluded: frozenset[Category]) -> HistoryDecision:
    """`messages` are the conversation's replayable messages in id order."""
    if not excluded:
        return HistoryDecision(list(messages), [], [])
    taint: set[Category] = set()
    kept, withheld, reasons = [], [], set()
    for m in messages:
        known = snapshot_categories.get(m.context_snapshot_id) if m.context_snapshot_id else None
        taint |= set(ALL_CATEGORIES) if known is None else known
        hit = taint & excluded
        if hit:
            withheld.append(m.id)
            reasons |= hit
        else:
            kept.append(m)
    return HistoryDecision(kept, withheld, sorted(c.value for c in reasons))
