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


@pytest.mark.parametrize('change', ['unshare', 'delete', 'exclude', 'off', 'replace', 'purge'])
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
    elif change == 'replace':
        manager.add_version(session, resume, 'new.md', '새로운 경력'.encode())
        asyncio.run(manager.process_one(db))
        session.expire_all()
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


def test_history_with_more_sources_than_prompt_budget_is_not_replayed(session, resume, fake_provider):
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
    assert 'OLD_UNRESOLVABLE_REPLY' not in json.dumps(request.input, ensure_ascii=False)


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
