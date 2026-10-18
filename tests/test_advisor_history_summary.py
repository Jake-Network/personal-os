import asyncio
import json

import pytest
from sqlalchemy import select

from app.modules.advisor.advisor_manager import advisor_manager
from app.modules.advisor.runtime.context import ContextAssembler
from app.modules.advisor.types import AskOptions
from app.modules.context.record_privacy import set_record_policy
from app.modules.crud import context_snapshot_handler, message_handler
from app.modules.database.model import ConversationSummary
from app.modules.llm.errors import AdvisorError


def history(session):
    conversation = advisor_manager.create_conversation(session, 'synthetic-long-history')
    source = context_snapshot_handler.create(session, {'id': 'summary-source', 'conversation_id': conversation.id,
        'context_categories': ['career'], 'excluded_categories': [], 'record_references': [],
        'source_updated_at': {}, 'data_quality_flags': [], 'payload': {'data': {}}, 'content_hash': 'synthetic'})
    rows = [message_handler.create(session, {'conversation_id': conversation.id, 'role': role,
        'content': content, 'context_snapshot_id': source.id}) for role, content in [
            ('user', '초기 필수 조건: 합성회사에서는 주말 근무를 할 수 없습니다.'),
            ('assistant', '초기 조건을 검토하겠습니다.'), ('user', '최근 질문'), ('assistant', '최근 답변')]]
    session.commit()
    return conversation, rows


def test_long_history_fallback_is_sourced_disjoint_reused_and_explicit(session, fake_provider, monkeypatch):
    monkeypatch.setattr(advisor_manager, 'history_limit', 2)
    conversation, rows = history(session)
    assembler = ContextAssembler(session, advisor_manager, conversation, AskOptions(), 'fake-model')

    async def exercise():
        request, package = await assembler.assemble('면접 계획을 검토해 주세요')
        summary = package.payload['data']['conversation_summary']
        assert summary['first_message_id'] == rows[0].id and summary['last_message_id'] == rows[1].id
        assert any(flag['code'] == 'history_summary_extractive_fallback' for flag in package.data_quality_flags)
        assert [item['content'] for item in request.input if item['role'] in {'user', 'assistant'}] == [
            '최근 질문', '최근 답변', '면접 계획을 검토해 주세요']
        _ = [event async for event in advisor_manager.gateway.stream(session, request)]
        assert '주말 근무를 할 수 없습니다' in json.dumps(fake_provider.requests[-1].input, ensure_ascii=False)
        await assembler.assemble('면접 계획을 검토해 주세요')
    asyncio.run(exercise())
    assert len(session.scalars(select(ConversationSummary)).all()) == 1


def test_summary_source_revoked_after_assembly_never_reaches_provider(session, fake_provider, monkeypatch):
    monkeypatch.setattr(advisor_manager, 'history_limit', 2)
    conversation, rows = history(session)
    assembler = ContextAssembler(session, advisor_manager, conversation, AskOptions(), 'fake-model')

    async def exercise():
        request, _ = await assembler.assemble('면접 계획을 검토해 주세요')
        set_record_policy(session, 'advisor_messages', rows[0].id, False)
        with pytest.raises(AdvisorError) as failure:
            _ = [event async for event in advisor_manager.gateway.stream(session, request)]
        assert failure.value.provider_code == 'source_policy_changed'
        assert fake_provider.requests == []
    asyncio.run(exercise())


def test_model_summary_preserves_source_range_and_skips_extractive_fallback(session, monkeypatch):
    monkeypatch.setattr(advisor_manager, 'history_limit', 2)
    conversation, rows = history(session)
    assembler = ContextAssembler(session, advisor_manager, conversation, AskOptions(), 'fake-model')

    async def exercise():
        overflow = await assembler.history_overflow('면접 계획')
        assert assembler.saved_history_summary(overflow) is None
        summary = assembler.store_history_summary('당시 사용자 조건: 합성회사의 주말 근무 불가.', overflow)
        session.commit()
        request, package = await assembler.assemble('면접 계획')
        selected = package.payload['data']['conversation_summary']
        assert selected['generator'] == 'graph_summary_v1'
        assert selected['ref'] == f'conversation_summaries:{summary.id}'
        assert {ref['id'] for ref in summary.source_references} == {rows[0].id, rows[1].id}
        assert not any(flag['code'] == 'history_summary_extractive_fallback' for flag in package.data_quality_flags)
        assert '주말 근무 불가' in json.dumps(request.input, ensure_ascii=False)
    asyncio.run(exercise())
