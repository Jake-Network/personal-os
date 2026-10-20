from sqlalchemy import event

from app.modules.advisor.answer_actions import message_items
from app.modules.database.model import AdvisorConversation, AdvisorMessage


def test_legacy_answer_page_uses_bounded_queries_with_original_questions(session):
    conversations = [AdvisorConversation(title=f"합성 대화 {i}") for i in range(2)]
    session.add_all(conversations)
    session.flush()
    answers = []
    for i in range(60):
        conversation = conversations[i % 2]
        session.add(AdvisorMessage(conversation_id=conversation.id, role="user", content=f"합성 질문 {i}"))
        session.flush()
        answer = AdvisorMessage(conversation_id=conversation.id, role="assistant", content=f"합성 답변 {i}")
        session.add(answer)
        session.flush()
        answers.append(answer)
    statements = []
    def record(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith(("SELECT", "WITH")):
            statements.append(statement)
    event.listen(session.bind, "before_cursor_execute", record)
    try:
        items = message_items(session, answers)
    finally:
        event.remove(session.bind, "before_cursor_execute", record)
    assert all(item.is_final_answer for item in items)
    assert [item.source_question for item in items] == [f"합성 질문 {i}" for i in range(60)]
    assert len(statements) <= 2, f"answer page issued {len(statements)} read queries"


def test_retry_answer_ids_and_clarifications_are_classified_in_two_queries(session):
    from sqlalchemy import select
    from app.modules.database.model.advisor_runtime import AdvisorRun, AdvisorRunEvent
    conv = AdvisorConversation(title='합성 재시도')
    session.add(conv)
    session.flush()
    messages = []
    for role, text in [('user', '원래 질문'), ('assistant', '확인 질문'),
                       ('user', '네'), ('assistant', '첫 답변'),
                       ('assistant', '재시도 확인 질문'), ('assistant', '수정 답변')]:
        row = AdvisorMessage(conversation_id=conv.id, role=role, content=text)
        session.add(row)
        session.flush()
        messages.append(row)
    ids = [row.id for row in messages]
    run = AdvisorRun(id='large-retry', conversation_id=conv.id, request_id='large-retry',
                     user_message_id=ids[0], assistant_message_id=ids[-1], status='completed',
                     input_payload={'message': '원래 질문', 'unrelated': 'x' * 100_000})
    session.add(run)
    session.flush()
    session.add_all([
        AdvisorRunEvent(run_id=run.id, seq=1, event_key='first', type='done', revision=1,
                        payload={'message_id': ids[3], 'answer': 'x' * 100_000}),
        AdvisorRunEvent(run_id=run.id, seq=2, event_key='invalid', type='done', revision=1,
                        payload={'message_id': 'not-a-message'}),
    ])
    session.flush()
    session.expunge_all()
    page = list(session.scalars(select(AdvisorMessage).where(AdvisorMessage.id.in_(ids))))
    statements = []
    def record(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith(('SELECT', 'WITH')):
            statements.append(statement)
    event.listen(session.bind, 'before_cursor_execute', record)
    try:
        items = message_items(session, page)
    finally:
        event.remove(session.bind, 'before_cursor_execute', record)
    assert [item.is_final_answer for item in items] == [False, False, False, True, False, True]
    assert [item.source_question for item in items if item.is_final_answer] == ['원래 질문', '원래 질문']
    assert len(statements) <= 2
