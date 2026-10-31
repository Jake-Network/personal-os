"""Golden set, deterministic layer: the exact package the model would receive for each case (fake provider)."""
import json

import pytest

from advisor_golden import load, seed, sent_problems
from app.enums.context_category import Category
from app.modules.advisor.advisor_manager import advisor_manager
from app.modules.advisor.types import AskOptions
from app.modules.finance.clock import local_today
from test_advisor_product_context import ask

GOLDEN = load()


@pytest.mark.parametrize("case", GOLDEN["questions"], ids=[case["id"] for case in GOLDEN["questions"]])
def test_golden_case_payload(session, fake_provider, case):
    seed(session, GOLDEN["personas"][case["persona"]], local_today())
    conversation = advisor_manager.create_conversation(session, case["id"])
    options = AskOptions(exclude=frozenset(Category(c) for c in case["exclude"])) if case.get("exclude") else None
    package = ask(session, conversation, case["question"], fake_provider, options)
    sent = json.dumps(fake_provider.requests[-1].input, ensure_ascii=False)
    assert sent_problems(case, package, sent) == []
