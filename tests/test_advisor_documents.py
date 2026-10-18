"""End-to-end context contracts: retrieval, inherited provenance, and fail-closed history."""
import asyncio
import json
from dataclasses import replace

import pytest

from app.config import settings
from app.enums.context_category import Category
from app.modules.advisor.advisor_manager import advisor_manager
from app.modules.context.privacy_manager import privacy_manager
from app.modules.crud.advisor_handler import context_snapshot_handler
from app.modules.database import db
from app.modules.database.model import Document
from app.modules.documents import document_manager as manager, embedding, retrieval
from app.schema.advisor_schema import AskOptions


def ask(session, conv, query, options=None):
    async def collect():
        return [event async for event in advisor_manager.ask(session, conv, query, options)]
    return asyncio.run(collect())


def context(request):
    return json.loads(next(i['content'] for i in request.input if i['role'] == 'developer').split('\n', 1)[1])


@pytest.fixture
def resume(session, monkeypatch):
    for module in (embedding, retrieval, manager):
        monkeypatch.setattr(module, 'settings', replace(settings, embedding_dimensions=3))
    async def embed(texts):
        return [[1., 0., 0.] for _ in texts]
    monkeypatch.setattr(embedding, 'embed_texts', embed)
    monkeypatch.setattr(embedding, 'embed_query', lambda text: [1., 0., 0.])
    document = Document(title='경력기술서', categories=['career'], kind='resume')
    session.add(document)
    session.flush()
    manager.add_version(session, document, 'resume.md', '비밀프로젝트 Python 대규모 처리 경험'.encode())
    asyncio.run(manager.process_one(db))
    session.expire_all()
    return document


def test_resume_question_auto_retrieves_and_snapshot_contains_sources(session, resume, fake_provider):
    conversation = advisor_manager.create_conversation(session, '취업 상담')
    events = ask(session, conversation, '내 이력서를 요약해줘')
    package = context(fake_provider.requests[-1])
    citation = package['data']['search_documents']['citations'][0]
    assert citation['document_id'] == resume.id
    assert citation['ref'].startswith('document_chunks:')
    assert events[0]['document_citations'] == [citation]
    assert package['document_dependencies'] == [{'document_id': resume.id, 'version_id': resume.active_version_id}]


@pytest.mark.parametrize('change', ['unshare', 'delete', 'exclude', 'off', 'purge'])
def test_indirect_history_does_not_leak_after_document_scope_changes(session, resume, fake_provider, monkeypatch, change):
    conversation = advisor_manager.create_conversation(session, '취업 상담')
    fake_provider.reply = '비밀프로젝트 경험이 있습니다.'
    ask(session, conversation, '내 이력서 요약')
    # A follow-up can repeat old facts even when retrieval itself finds no new source.
    monkeypatch.setattr(retrieval.embedding, 'embed_query', lambda text: [-1., 0., 0.])
    ask(session, conversation, '커리어 평가를 더 해줘')
    second = context(fake_provider.requests[-1])
    assert second['document_dependencies']
    assert second['data']['search_documents']['citations']
    options = None
    if change == 'unshare':
        resume.sharing_enabled = False
        session.commit()
    elif change in ('delete', 'purge'):
        manager.delete_document(session, resume.id, purge_evidence=change == 'purge')
    elif change == 'exclude':
        privacy_manager.set_excluded(session, [Category.CAREER])
    elif change == 'off':
        options = AskOptions(document_search=False)
    fake_provider.reply = '새 답변'
    ask(session, conversation, '커리어 평가', options)
    request = fake_provider.requests[-1]
    assert '비밀프로젝트' not in json.dumps(request.input, ensure_ascii=False)


def test_pins_inherit_clear_and_privacy_wins(session, resume, fake_provider):
    conversation = advisor_manager.create_conversation(session, '문서 상담')
    ask(session, conversation, '이 자료 요약', AskOptions(document_ids=(resume.id,)))
    assert context(fake_provider.requests[-1])['document_scope']['document_ids'] == [resume.id]
    ask(session, conversation, '더 설명해줘')
    assert context(fake_provider.requests[-1])['document_scope']['document_ids'] == [resume.id]
    ask(session, conversation, '더 설명해줘', AskOptions(document_ids=()))
    assert context(fake_provider.requests[-1])['document_scope']['document_ids'] == []
    privacy_manager.set_excluded(session, [Category.CAREER])
    ask(session, conversation, '이 자료 요약', AskOptions(document_ids=(resume.id,)))
    assert '비밀프로젝트' not in json.dumps(fake_provider.requests[-1].input, ensure_ascii=False)


def test_preview_has_no_persistence_or_llm_request(session, resume, fake_provider):
    from sqlalchemy import select, func
    from app.modules.database.model import ContextSnapshot
    before = session.scalar(select(func.count()).select_from(ContextSnapshot))
    preview = advisor_manager.preview(session, '내 이력서 요약', None, AskOptions())
    assert preview['document_citations']
    assert not fake_provider.requests
    assert session.scalar(select(func.count()).select_from(ContextSnapshot)) == before


def test_history_with_more_sources_than_prompt_budget_keeps_context_without_dangling_refs(session, resume, fake_provider):
    from app.modules.database.model import ContextSnapshot, AdvisorMessage, DocumentChunk, utcnow
    from sqlalchemy import select
    conversation = advisor_manager.create_conversation(session, '긴 문서 상담')
    prototype = session.scalar(select(DocumentChunk))
    citations = []
    for ordinal in range(12):
        chunk = DocumentChunk(version_id=resume.active_version_id, ordinal=ordinal + 20,
                              text=f'Python 근거 {ordinal}', embedding=[1., 0., 0.])
        session.add(chunk)
        session.flush()
        citation = retrieval.citation(chunk, manager.latest_version(session, resume.id), resume)
        citations.append(citation)
    snapshot = ContextSnapshot(id='many-sources', conversation_id=conversation.id, generated_at=utcnow(),
        context_categories=['career', 'goals', 'profile'], excluded_categories=[], record_references=[],
        source_updated_at={}, data_quality_flags=[], content_hash='test',
        payload={'data': {'search_documents': {'citations': citations}},
                 'document_dependencies': [{'document_id': resume.id, 'version_id': resume.active_version_id}]})
    session.add(snapshot)
    session.flush()
    session.add(AdvisorMessage(conversation_id=conversation.id, role='assistant', status='complete',
        content='OLD_UNRESOLVABLE_REPLY ' + ' '.join('[' + c['ref'] + ']' for c in citations),
        context_snapshot_id=snapshot.id))
    session.commit()
    ask(session, conversation, '내 이력서 요약')
    request = fake_provider.requests[-1]
    assert len(context(request)['data']['search_documents']['citations']) <= 10
    assert 'OLD_UNRESOLVABLE_REPLY' in json.dumps(request.input, ensure_ascii=False)
    available_refs = {c['ref'] for c in context(request)['data']['search_documents']['citations']}
    import re
    replay = next(item['content'] for item in request.input if item['role'] == 'assistant')
    assert '[과거 문서 근거 생략]' in replay
    assert set(re.findall(r'\[(document_chunks:\d+)\]', replay)) <= available_refs
    assert any(flag['code'] == 'history_document_evidence_omitted' and flag['count'] > 0
               for flag in context(request)['data_quality_flags'])
    original = session.scalar(select(AdvisorMessage).where(
        AdvisorMessage.content.startswith('OLD_UNRESOLVABLE_REPLY')))
    assert all('[' + citation['ref'] + ']' in original.content for citation in citations)


def test_snapshot_comparison_does_not_mistake_trimmed_or_inherited_excerpts_for_changes(session, resume, fake_provider, monkeypatch):
    from app.modules.context.context_builder_manager import context_builder_manager
    from app.modules.database.model import DocumentChunk
    from sqlalchemy import select
    chunk = session.scalar(select(DocumentChunk))
    chunk.text = 'Python 경험 ' * 2000
    session.commit()
    conversation = advisor_manager.create_conversation(session, '비교')
    ask(session, conversation, '내 이력서 요약')
    snapshot = context_snapshot_handler.get_latest_for_conversation(session, conversation.id)
    changed, unchanged = context_builder_manager.compare_with_current(session, snapshot)
    assert 'search_documents' not in changed
    assert 'search_documents' in unchanged
    monkeypatch.setattr(embedding, 'embed_query', lambda text: [-1., 0., 0.])
    ask(session, conversation, '커리어 평가')
    snapshot = context_snapshot_handler.get_latest_for_conversation(session, conversation.id)
    assert 'search_documents' not in context_builder_manager.compare_with_current(session, snapshot)[0]
    resume.title = '새 제목'
    session.commit()
    assert 'search_documents' in context_builder_manager.compare_with_current(session, snapshot)[0]
    monkeypatch.setattr(embedding, 'embed_query', lambda text: [1., 0., 0.])
    ask(session, conversation, '내 이력서 요약')
    assert context(fake_provider.requests[-1])['data']['search_documents']['citations'][0]['title'] == '새 제목'


def test_openapi_operations_are_unique_and_preserve_existing_ai_client_names():
    from app.main import app
    spec = app.openapi()
    operations = [operation['operationId'] for path in spec['paths'].values()
                  for operation in path.values() if isinstance(operation, dict) and 'operationId' in operation]
    assert len(operations) == len(set(operations))
    assert spec['paths']['/api/settings/ai-provider']['get']['operationId'] == 'get_status'
    assert spec['paths']['/api/documents']['post']['operationId'] == 'upload_document'


def test_topic_change_keeps_offer_and_legacy_history(session, fake_provider):
    from app.modules.database.model import AdvisorMessage
    conversation = advisor_manager.create_conversation(session, '상담')
    session.add(AdvisorMessage(conversation_id=conversation.id, role='user', status='complete', content='LEGACY_OFFER_A'))
    session.commit()
    fake_provider.reply = 'OFFER_CONTEXT_A'
    ask(session, conversation, '회사 오퍼 비교')
    ask(session, conversation, '생활비 예산은?')
    inputs = json.dumps(fake_provider.requests[-1].input, ensure_ascii=False)
    assert 'OFFER_CONTEXT_A' in inputs
    assert 'LEGACY_OFFER_A' in inputs


@pytest.mark.parametrize('mode', ['override', 'exclude'])
def test_pinned_multitag_document_cannot_enable_health(session, resume, fake_provider, mode):
    resume.categories = ['career', 'health']
    session.commit()
    conversation = advisor_manager.create_conversation(session, '상담')
    options = AskOptions(document_ids=(resume.id,), categories=frozenset({Category.CAREER})) if mode == 'override' else AskOptions(document_ids=(resume.id,), exclude=frozenset({Category.HEALTH}))
    ask(session, conversation, '이 자료', options)
    package = context(fake_provider.requests[-1])
    assert 'health' not in package['categories']
    assert '비밀프로젝트' not in json.dumps(fake_provider.requests[-1].input, ensure_ascii=False)


def test_replacing_resume_preserves_offer_context_with_historical_citations(session, resume, fake_provider):
    conversation = advisor_manager.create_conversation(session, '오퍼 상담')
    first_version = resume.active_version_id
    fake_provider.reply = 'OFFER_A_CONTEXT [document_chunks:1]'
    ask(session, conversation, '내 이력서와 오퍼 비교')
    manager.add_version(session, resume, 'v2.md', '최신 경력 새 프로젝트'.encode())
    asyncio.run(manager.process_one(db))
    session.expire_all()
    fake_provider.reply = '다음 답변'
    ask(session, conversation, '생활비 예산을 계산해줘')
    request = fake_provider.requests[-1]
    assert any('OFFER_A_CONTEXT' in item['content'] for item in request.input if item['role'] == 'assistant')
    citations = context(request)['data']['search_documents']['citations']
    assert any(c['version_id'] == first_version and c['historical'] for c in citations)
    assert resume.active_version_id != first_version


def test_explicit_exclusion_blocks_cross_topic_transitive_history(session, fake_provider):
    conversation = advisor_manager.create_conversation(session, '상담')
    fake_provider.reply = 'PRIVATE_CAREER_FACT'
    ask(session, conversation, '회사 오퍼 비교')
    fake_provider.reply = 'TRANSITIVE_CAREER_IN_BUDGET'
    ask(session, conversation, '생활비 예산')
    fake_provider.reply = '공유 제한 답변'
    ask(session, conversation, '생활비 예산', AskOptions(exclude=frozenset({Category.CAREER})))
    inputs = json.dumps(fake_provider.requests[-1].input, ensure_ascii=False)
    assert 'PRIVATE_CAREER_FACT' not in inputs
    assert 'TRANSITIVE_CAREER_IN_BUDGET' not in inputs


def test_history_snapshots_are_loaded_in_one_batch(session, fake_provider):
    from sqlalchemy import event
    from app.modules.database.model import AdvisorMessage, ContextSnapshot, utcnow
    conversation = advisor_manager.create_conversation(session, '상담')
    for i in range(20):
        snapshot = ContextSnapshot(id=f'batched-{i}', conversation_id=conversation.id, generated_at=utcnow(),
            context_categories=['career'], excluded_categories=[], record_references=[], source_updated_at={},
            data_quality_flags=[], content_hash=str(i), payload={'data': {}})
        session.add(snapshot)
        session.flush()
        session.add(AdvisorMessage(conversation_id=conversation.id, role='user', status='complete',
                                   content=f'OFFER_{i}', context_snapshot_id=snapshot.id))
    session.commit()
    queries = []
    def capture(conn, cursor, statement, params, context, executemany):
        if statement.lstrip().upper().startswith('SELECT') and 'context_snapshots' in statement:
            queries.append(statement)
    event.listen(session.get_bind(), 'before_cursor_execute', capture)
    try:
        ask(session, conversation, '생활비 예산')
    finally:
        event.remove(session.get_bind(), 'before_cursor_execute', capture)
    assert len(queries) <= 5
    assert sum(item['role'] == 'user' for item in fake_provider.requests[-1].input) == 21


def test_explicit_category_allowlist_limits_history_but_auto_route_does_not(session, fake_provider):
    conversation = advisor_manager.create_conversation(session, '상담')
    fake_provider.reply = 'PRIVATE_HEALTH_CONTEXT'
    ask(session, conversation, '운동 계획')
    fake_provider.reply = '재무 답변'
    ask(session, conversation, '생활비 예산', AskOptions(categories=frozenset({Category.FINANCIAL})))
    assert 'PRIVATE_HEALTH_CONTEXT' not in json.dumps(fake_provider.requests[-1].input, ensure_ascii=False)


def test_multichunk_revision_replacement_keeps_offer_when_citations_exceed_budget(session, resume, fake_provider):
    import re
    from app.modules.database.model import DocumentChunk
    def add_comparison_chunks():
        for ordinal in range(1, 11):
            session.add(DocumentChunk(version_id=resume.active_version_id, ordinal=ordinal,
                                      text='Python 프로젝트 근거', embedding=[1., 0., 0.]))
        session.commit()
    conversation = advisor_manager.create_conversation(session, '오퍼 상담')
    options = AskOptions(document_ids=(resume.id,))
    add_comparison_chunks()
    preview = advisor_manager.preview(session, '내 이력서 오퍼 비교', conversation, options)
    old_refs = [citation['ref'] for citation in preview['document_citations']]
    assert len(old_refs) == 6
    fake_provider.reply = 'OFFER_CONTEXT_MUST_REMAIN ' + ' '.join('[' + ref + ']' for ref in old_refs)
    ask(session, conversation, '내 이력서 오퍼 비교', options)
    manager.add_version(session, resume, 'v2.md', 'Python 최신 프로젝트'.encode())
    asyncio.run(manager.process_one(db))
    session.expire_all()
    add_comparison_chunks()
    fake_provider.reply = '새 답변'
    ask(session, conversation, '내 이력서 오퍼 비교', options)
    request = fake_provider.requests[-1]
    package = context(request)
    citations = package['data']['search_documents']['citations']
    assert len(citations) == 10
    assert len([c for c in citations if c['version_id'] == resume.active_version_id]) == 6
    history = next(item['content'] for item in request.input if item['role'] == 'assistant')
    assert 'OFFER_CONTEXT_MUST_REMAIN' in history
    assert '[과거 문서 근거 생략]' in history
    assert set(re.findall(r'\[(document_chunks:\d+)\]', history)) <= {c['ref'] for c in citations}
    assert any(f['code'] == 'history_document_evidence_omitted' and f['count'] == 2
               for f in package['data_quality_flags'])


@pytest.mark.parametrize('restriction', ['exclude', 'document_search_off', 'pins', 'allowlist'])
def test_legacy_unknown_provenance_propagates_and_blocks_repeated_private_facts(session, resume, fake_provider, monkeypatch, restriction):
    from app.modules.database.model import AdvisorMessage
    conversation = advisor_manager.create_conversation(session, '상담')
    secret = 'LEGACY_HEALTH_PRIVATE_FACT'
    session.add(AdvisorMessage(conversation_id=conversation.id, role='assistant', status='complete', content=secret))
    session.commit()
    fake_provider.reply = secret + ' career echo'
    ask(session, conversation, '회사 오퍼 비교')
    assert secret in json.dumps(fake_provider.requests[-1].input, ensure_ascii=False)
    assert context(fake_provider.requests[-1])['history_provenance_unknown'] is True
    # The legacy row has already aged out: only descendants carry the unknown provenance.
    monkeypatch.setattr(advisor_manager, 'history_limit', 2)
    fake_provider.reply = secret + ' budget echo'
    ask(session, conversation, '생활비 예산')
    assert context(fake_provider.requests[-1])['history_provenance_unknown'] is True
    options = {
        'exclude': AskOptions(exclude=frozenset({Category.HEALTH})),
        'document_search_off': AskOptions(document_search=False),
        'pins': AskOptions(document_ids=(resume.id,)),
        'allowlist': AskOptions(categories=frozenset({Category.CAREER, Category.FINANCIAL})),
    }[restriction]
    fake_provider.reply = '공유 가능한 답변'
    ask(session, conversation, '회사 오퍼 예산', options)
    assert secret not in json.dumps(fake_provider.requests[-1].input, ensure_ascii=False)
    assert not context(fake_provider.requests[-1]).get('history_provenance_unknown')
