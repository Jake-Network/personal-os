from app.modules.database.model import AdvisorConversation, AdvisorMessage, AdvisorRecommendation
from sqlalchemy import select


def message(session, **kwargs):
    conv = AdvisorConversation(title='합성 질문')
    session.add(conv)
    session.flush()
    row = AdvisorMessage(conversation_id=conv.id, role='assistant', content='저장된 답변\n두 번째 줄', **kwargs)
    session.add(row)
    session.commit()
    return row


def test_feedback_uses_saved_answer_and_returns_latest(client, session):
    row = message(session)
    for rating in (1, -1, None):
        response = client.post('/api/advisor/recommendations', json={
            'message_id': row.id, 'summary': '조작한 요약', 'user_rating': rating})
        assert response.status_code == 201
    items = client.get(f'/api/advisor/conversations/{row.conversation_id}/recommendations').json()
    assert len(items) == 1
    assert items[0]['summary'] == '저장된 답변'
    assert items[0]['user_rating'] is None
    assert len(list(session.scalars(select(AdvisorRecommendation)))) == 3
    detail = client.get(f'/api/advisor/conversations/{row.conversation_id}').json()
    assert detail['messages'][0]['is_final_answer'] is True


def test_runtime_clarification_and_incomplete_are_not_final(client, session):
    from app.modules.database.model.advisor_runtime import AdvisorRun
    row = message(session)
    user = AdvisorMessage(conversation_id=row.conversation_id, role='user', content='질문')
    session.add(user)
    session.flush()
    question = AdvisorMessage(conversation_id=row.conversation_id, role='assistant', content='확인 질문')
    partial = AdvisorMessage(conversation_id=row.conversation_id, role='assistant', content='미완성', status='incomplete')
    session.add_all([question, partial])
    session.add(AdvisorRun(id='synthetic-run', conversation_id=row.conversation_id, request_id='request',
        user_message_id=user.id, status='waiting_input', input_payload={}))
    session.commit()
    items = client.get(f'/api/advisor/conversations/{row.conversation_id}/messages').json()
    assert [item['is_final_answer'] for item in items] == [True, False, False, False]
    for item in (question, partial, user):
        assert client.post('/api/advisor/recommendations', json={'message_id': item.id, 'user_rating': 1}).status_code == 422


def test_decision_preserves_answer_snapshot_and_rejects_missing(client, session):
    from app.modules.database.model import ContextSnapshot
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from app.config import settings
    row = message(session)
    snapshot = ContextSnapshot(id='original', conversation_id=row.conversation_id, context_categories=[],
        record_references=[], source_updated_at={}, data_quality_flags=[], payload={}, content_hash='synthetic')
    session.add(snapshot)
    session.flush()
    row.context_snapshot_id = snapshot.id
    session.commit()
    body = {'title': '결정', 'choice': '선택', 'rationale': '이유', 'source_message_id': row.id,
        'review_on': '2026-11-03T00:00:00'}
    response = client.post('/api/decisions', json=body)
    assert response.status_code == 201, response.text
    result = response.json()
    assert result['context_snapshot_id'] == 'original'
    assert result['conversation_id'] == row.conversation_id
    assert datetime.fromisoformat(result['review_on']).astimezone(ZoneInfo(settings.timezone)).hour == 9
    assert client.post('/api/decisions', json={**body, 'context_snapshot_id': 'different'}).status_code == 422
    row.context_purged = True
    row.context_snapshot_id = None
    session.commit()
    assert client.post('/api/decisions', json=body).status_code == 422


def test_feedback_stays_out_of_real_runtime_payload(seeded, fake_provider):
    import asyncio
    import json
    from app.modules.advisor.advisor_manager import advisor_manager
    from app.modules.advisor.runtime.service import conversation_runtime
    from app.modules.advisor.types import AskOptions
    from app.enums.context_category import Category
    conv = advisor_manager.create_conversation(seeded, '합성 상담')

    async def ask(text, options=None):
        return [event async for event in conversation_runtime.single_response(seeded, conv, text, options)]

    events = asyncio.run(ask('현재 재무 상태는?'))
    final = events[-1]
    assert final['type'] == 'done'
    seeded.add(AdvisorRecommendation(message_id=final['message_id'], summary='SECRET_FEEDBACK_SUMMARY',
        user_rating=-1, user_feedback='SECRET_FEEDBACK_REASON'))
    seeded.commit()
    asyncio.run(ask('현재 재무 상태를 다시 알려줘', AskOptions(exclude=frozenset({Category.CAREER}))))
    sent = json.dumps(fake_provider.requests[-1].input, ensure_ascii=False)
    assert 'SECRET_FEEDBACK' not in sent
    assert '레인보우로보틱스' not in sent


def test_feedback_does_not_follow_retry_and_cascades_on_delete(client, session):
    row = message(session)
    assert client.post('/api/advisor/recommendations', json={'message_id': row.id, 'user_rating': -1}).status_code == 201
    retry = AdvisorMessage(conversation_id=row.conversation_id, role='assistant', content='다시 작성한 답변')
    session.add(retry)
    session.commit()
    feedback = client.get(f'/api/advisor/conversations/{row.conversation_id}/recommendations').json()
    assert [item['message_id'] for item in feedback] == [row.id]
    assert client.delete(f'/api/advisor/conversations/{row.conversation_id}').status_code == 204
    session.expire_all()
    assert list(session.scalars(select(AdvisorRecommendation))) == []


def test_final_answer_keeps_original_question_after_clarification(session):
    from app.modules.advisor.answer_actions import message_items
    from app.modules.database.model.advisor_runtime import AdvisorRun
    conv = AdvisorConversation(title='원래 질문')
    session.add(conv)
    session.flush()
    initial = AdvisorMessage(conversation_id=conv.id, role='user', content='원래 질문')
    session.add(initial)
    session.flush()
    clarification = AdvisorMessage(conversation_id=conv.id, role='assistant', content='확인할까요?')
    response = AdvisorMessage(conversation_id=conv.id, role='user', content='네')
    answer = AdvisorMessage(conversation_id=conv.id, role='assistant', content='최종 답변')
    session.add_all([clarification, response, answer])
    session.flush()
    session.add(AdvisorRun(id='clarified', conversation_id=conv.id, request_id='clarified',
        user_message_id=initial.id, assistant_message_id=answer.id, status='completed',
        input_payload={'message': '원래 질문'}))
    session.commit()
    items = message_items(session, [clarification, answer])
    assert not items[0].is_final_answer
    assert items[1].is_final_answer
    assert items[1].source_question == '원래 질문'
