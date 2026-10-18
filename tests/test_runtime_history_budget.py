import asyncio
import json
from dataclasses import replace

import pytest

from app.config import settings
from app import config
from app.modules.advisor import requests as request_module
from app.modules.advisor.advisor_manager import advisor_manager
from app.modules.advisor.runtime.context import ContextAssembler, bounded_history_excerpt
from app.modules.advisor.types import AskOptions
from app.modules.context.record_privacy import set_record_policy
from app.modules.crud import context_snapshot_handler, message_handler
from app.modules.llm.errors import AdvisorError


@pytest.mark.parametrize('budget', [0, 80, 500, 1500, 4000])
def test_excerpt_has_total_serialized_bound_and_discloses_missing_messages(budget):
    messages = [{'id': index, 'role': 'user', 'content': f'조건 {index}: ' + '\n"\\조건' * 200}
                for index in range(1, 101)]
    content = bounded_history_excerpt(messages, budget)
    assert len(json.dumps(content, ensure_ascii=False)) - 2 <= budget
    if content:
        assert '생략' in content
    if budget == 4000:
        assert '[user message:1]' in content
        assert '[user message:100]' in content
        assert '[user message:50]' not in content


@pytest.mark.parametrize('context_limit', [3500, 8500])
def test_long_history_fits_context_and_request_budgets_without_losing_source_checks(session, monkeypatch, context_limit):
    monkeypatch.setattr(advisor_manager, 'history_limit', 2)
    budgets = replace(settings, context_char_limit=context_limit, request_char_limit=18000)
    monkeypatch.setattr(config, 'settings', budgets)
    monkeypatch.setattr(request_module, 'settings', budgets)
    conversation = advisor_manager.create_conversation(session, 'bounded-history')
    source = context_snapshot_handler.create(session, {'id': 'bounded-source', 'conversation_id': conversation.id,
        'context_categories': ['career'], 'excluded_categories': [], 'record_references': [],
        'source_updated_at': {}, 'data_quality_flags': [], 'payload': {'data': {}}, 'content_hash': 'synthetic'})
    rows = [message_handler.create(session, {'conversation_id': conversation.id, 'role': 'user',
        'content': f'합성 조건 {index}: ' + '긴 대화 내용입니다. ' * 70, 'context_snapshot_id': source.id})
        for index in range(80)]
    session.commit()
    assembler = ContextAssembler(session, advisor_manager, conversation, AskOptions(), 'fake-model')

    async def exercise():
        request, package = await assembler.assemble('현재 커리어 고민', structured_output=True)
        content = package.payload['data']['conversation_summary']['content']
        assert len(json.dumps(content, ensure_ascii=False)) - 2 <= 4000
        assert '생략' in content
        assert len(package.text) <= budgets.context_char_limit
        assert len(json.dumps({'instructions': request.instructions, 'input': request.input},
                              ensure_ascii=False)) <= budgets.request_char_limit
        # Cached extracts are re-budgeted when the surrounding request grows.
        tighter = replace(budgets, request_char_limit=len(json.dumps(
            {'instructions': request.instructions, 'input': request.input}, ensure_ascii=False)) + 1000)
        monkeypatch.setattr(config, 'settings', tighter)
        monkeypatch.setattr(request_module, 'settings', tighter)
        larger_request, smaller_package = await assembler.assemble('현재 커리어 고민',
            instruction='추가 지시 ' * max(1, len(content) // 6), structured_output=True)
        assert len(smaller_package.payload['data']['conversation_summary']['content']) < len(content)
        assert len(json.dumps({'instructions': larger_request.instructions, 'input': larger_request.input},
                              ensure_ascii=False)) <= tighter.request_char_limit
        assert f'[user message:{rows[30].id}]' not in content
        set_record_policy(session, 'advisor_messages', rows[30].id, False)
        # Omitted messages remain part of conservative summary provenance.
        with pytest.raises(AdvisorError) as failure:
            assembler.validate_sources([package.snapshot_id])
        assert failure.value.provider_code == 'source_policy_changed'

    asyncio.run(exercise())
