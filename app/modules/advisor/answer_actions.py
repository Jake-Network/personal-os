"""Eligibility and provenance for actions on saved consultation answers."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.database.model import AdvisorMessage, AdvisorRecommendation
from app.modules.database.model.advisor_runtime import AdvisorRun, AdvisorRunEvent
from app.schema.advisor_schema import MessageItem


def final_answer_ids(session: Session, messages: list[AdvisorMessage]) -> set[int]:
    if not messages:
        return set()
    conversations = {message.conversation_id for message in messages}
    runs = list(session.scalars(select(AdvisorRun).where(AdvisorRun.conversation_id.in_(conversations))))
    final_ids = {run.assistant_message_id for run in runs if run.assistant_message_id is not None}
    # A retry must not move an earlier answer's actions to its new revision.
    if runs:
        for payload in session.scalars(select(AdvisorRunEvent.payload).where(
                AdvisorRunEvent.run_id.in_([run.id for run in runs]), AdvisorRunEvent.type == 'done')):
            if payload.get('message_id'):
                final_ids.add(payload['message_id'])
    def belongs_to_run(message):
        for run in runs:
            if run.conversation_id != message.conversation_id or run.user_message_id is None:
                continue
            # A completed run owns the interval ending at its saved final answer;
            # an unfinished run owns through the next run's initial question.
            next_start = min((other.user_message_id for other in runs
                if other.conversation_id == run.conversation_id and other.user_message_id is not None
                and other.user_message_id > run.user_message_id), default=float('inf'))
            end = run.assistant_message_id if run.assistant_message_id is not None else next_start - 1
            if run.user_message_id <= message.id <= end:
                return True
        return False

    return {m.id for m in messages if m.role == 'assistant' and m.status == 'complete'
            and bool(m.content.strip()) and (m.id in final_ids or not belongs_to_run(m))}


def message_items(session: Session, messages: list[AdvisorMessage]) -> list[MessageItem]:
    eligible = final_answer_ids(session, messages)
    conversation_ids = {message.conversation_id for message in messages}
    runs = list(session.scalars(select(AdvisorRun).where(AdvisorRun.conversation_id.in_(conversation_ids)))) if messages else []
    questions = {run.assistant_message_id: (run.input_payload or {}).get('message') for run in runs}
    # Done events retain the original run question for earlier answer revisions.
    if runs:
        run_questions = {run.id: (run.input_payload or {}).get('message') for run in runs}
        for event in session.scalars(select(AdvisorRunEvent).where(
                AdvisorRunEvent.run_id.in_(run_questions), AdvisorRunEvent.type == 'done')):
            questions[event.payload.get('message_id')] = run_questions[event.run_id]
    items = []
    for message in messages:
        question = questions.get(message.id)
        if message.id in eligible and not question:
            question = session.scalar(select(AdvisorMessage.content).where(
                AdvisorMessage.conversation_id == message.conversation_id,
                AdvisorMessage.role == 'user', AdvisorMessage.id < message.id)
                .order_by(AdvisorMessage.id.desc()).limit(1))
        items.append(MessageItem.model_validate(message).model_copy(update={
            'is_final_answer': message.id in eligible, 'source_question': question if message.id in eligible else None}))
    return items


def latest_feedback(session: Session, conversation_id: int) -> list[AdvisorRecommendation]:
    rows = session.scalars(select(AdvisorRecommendation).join(AdvisorMessage).where(
        AdvisorMessage.conversation_id == conversation_id).order_by(AdvisorRecommendation.id.desc()))
    latest = {}
    for row in rows:
        latest.setdefault(row.message_id, row)
    return list(latest.values())
