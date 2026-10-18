import asyncio
import json

import pytest

from app.enums.context_category import Category
from app.modules.advisor.advisor_manager import advisor_manager
from app.modules.advisor.runtime.context import ContextAssembler
from app.modules.advisor.types import AskOptions
from app.modules.context.privacy_manager import privacy_manager
from app.modules.context.source_policy import source_allowed
from app.modules.database.model import ContextSnapshot
from app.modules.llm.errors import AdvisorError


def test_gateway_rechecks_derived_sources_after_context_assembly(seeded, fake_provider):
    conversation = advisor_manager.create_conversation(seeded, "합성 상담")
    assembler = ContextAssembler(seeded, advisor_manager, conversation, AskOptions(), "fake-model")

    async def exercise():
        _, first = await assembler.assemble("현재 내 순자산은?")
        request, second = await assembler.assemble("다음 면접은 언제야?",
            derived={"intermediate": "급여통장 12000000원"}, sources=[first.snapshot_id])
        # The new request's direct category is career/calendar. Its financial
        # dependency comes only from an earlier planning/research stage.
        assert first.snapshot_id in second.payload["derived_snapshot_ids"]
        assert "12000000" in json.dumps(request.input, ensure_ascii=False)
        privacy_manager.set_excluded(seeded, [Category.FINANCIAL])
        with pytest.raises(AdvisorError) as failure:
            _ = [event async for event in advisor_manager.gateway.stream(seeded, request)]
        assert failure.value.provider_code == "source_policy_changed"
        assert fake_provider.requests == []

    asyncio.run(exercise())


def test_derived_checkpoint_sources_fail_closed_when_purged_or_deleted(session):
    original = ContextSnapshot(id="original", context_categories=[], excluded_categories=[],
        record_references=[], source_updated_at={}, data_quality_flags=[], payload={}, content_hash="synthetic")
    derived = ContextSnapshot(id="derived", context_categories=[], excluded_categories=[],
        record_references=[], source_updated_at={}, data_quality_flags=[], payload={"derived_snapshot_ids": ["original"]},
        content_hash="synthetic")
    session.add_all([original, derived])
    session.commit()
    ref = [{"table": "context_snapshots", "id": derived.id}]
    assert source_allowed(session, ref)
    original.payload = {"source_purged": True}
    session.commit()
    assert not source_allowed(session, ref)
    session.delete(original)
    session.commit()
    assert not source_allowed(session, ref)


def test_derived_checkpoint_dependency_cycle_is_rejected(session):
    row = ContextSnapshot(id="cycle", context_categories=[], excluded_categories=[],
        record_references=[], source_updated_at={}, data_quality_flags=[], payload={"derived_snapshot_ids": ["cycle"]},
        content_hash="synthetic")
    session.add(row)
    session.commit()
    assert not source_allowed(session, [{"table": "context_snapshots", "id": row.id}])
