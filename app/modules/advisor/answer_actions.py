"""Eligibility and provenance for actions on saved consultation answers."""
from sqlalchemy import String, and_, cast, exists, func, literal, or_, select, union_all
from sqlalchemy.orm import Session, aliased

from app.modules.database.model import AdvisorMessage, AdvisorRecommendation
from app.modules.database.model.advisor_runtime import AdvisorRun, AdvisorRunEvent
from app.schema.advisor_schema import MessageItem


def _answer_metadata(session: Session, messages: list[AdvisorMessage], *, questions: bool,
                     operation_results: dict | None = None) -> dict[int, str | None]:
    candidates = {m.id: m for m in messages
                  if m.role == 'assistant' and m.status == 'complete' and m.content.strip()}
    if not candidates:
        return {}
    ids = list(candidates)
    question = AdvisorRun.input_payload['message'].as_string() if questions else literal(None)
    receipt = AdvisorRun.result['data_operations'] if operation_results is not None else literal(None)
    current_answers = select(cast(AdvisorRun.assistant_message_id, String), question, receipt).join(
        AdvisorMessage, and_(AdvisorMessage.id == AdvisorRun.assistant_message_id,
                             AdvisorMessage.conversation_id == AdvisorRun.conversation_id)
    ).where(AdvisorMessage.id.in_(ids))
    # Project just the event's answer ID, never its complete answer/result payload.
    event_message = cast(AdvisorRunEvent.payload['message_id'].as_string(), String)
    prior_receipt = AdvisorRunEvent.payload['data_operations'] if operation_results is not None else literal(None)
    previous_answers = select(event_message, question, prior_receipt).select_from(AdvisorRunEvent).join(
        AdvisorRun, AdvisorRun.id == AdvisorRunEvent.run_id
    ).join(AdvisorMessage, and_(cast(AdvisorMessage.id, String) == event_message,
                               AdvisorMessage.conversation_id == AdvisorRun.conversation_id)
    ).where(AdvisorRunEvent.type == 'done', AdvisorMessage.id.in_(ids))
    metadata = {}
    for message_id, original_question, operations in session.execute(union_all(current_answers, previous_answers)):
        key = int(message_id)
        metadata[key] = original_question or metadata.get(key)
        if operation_results is not None and isinstance(operations, list):
            operation_results[key] = operations

    unknown = set(ids) - metadata.keys()
    fallback = {key for key, value in metadata.items() if questions and not value}
    remaining = unknown | fallback
    if not remaining:
        return metadata

    statement = select(AdvisorMessage.id).where(AdvisorMessage.id.in_(remaining))
    if unknown:
        conversations = {candidates[key].conversation_id for key in unknown}
        # Calculate each distinct next start once. Runs sharing an initial user
        # message have the same boundary, including earlier retry revisions.
        starts = select(AdvisorRun.conversation_id, AdvisorRun.user_message_id).where(
            AdvisorRun.conversation_id.in_(conversations), AdvisorRun.user_message_id.is_not(None)
        ).distinct().subquery()
        next_starts = select(starts.c.conversation_id, starts.c.user_message_id,
            func.lead(starts.c.user_message_id).over(
                partition_by=starts.c.conversation_id, order_by=starts.c.user_message_id
            ).label('next_start')).subquery()
        ranges = select(AdvisorRun.conversation_id, AdvisorRun.user_message_id.label('start'),
            func.coalesce(AdvisorRun.assistant_message_id, next_starts.c.next_start - 1).label('end')
        ).join(next_starts, and_(next_starts.c.conversation_id == AdvisorRun.conversation_id,
                                next_starts.c.user_message_id == AdvisorRun.user_message_id)).subquery()
        owned = exists(select(1).select_from(ranges).where(
            ranges.c.conversation_id == AdvisorMessage.conversation_id,
            ranges.c.start <= AdvisorMessage.id,
            or_(ranges.c.end.is_(None), AdvisorMessage.id <= ranges.c.end)))
        statement = statement.where(or_(AdvisorMessage.id.in_(fallback), ~owned))

    if questions:
        prior_user = aliased(AdvisorMessage)
        original_question = select(prior_user.content).where(
            prior_user.conversation_id == AdvisorMessage.conversation_id,
            prior_user.role == 'user', prior_user.id < AdvisorMessage.id
        ).order_by(prior_user.id.desc()).limit(1).correlate(AdvisorMessage).scalar_subquery()
    else:
        original_question = literal(None)
    # Legacy question lookups are one batched query, independent of page length.
    for message_id, original_question in session.execute(statement.add_columns(original_question)):
        metadata[message_id] = original_question
    return metadata


def final_answer_ids(session: Session, messages: list[AdvisorMessage]) -> set[int]:
    return set(_answer_metadata(session, messages, questions=False))


def message_items(session: Session, messages: list[AdvisorMessage]) -> list[MessageItem]:
    operations = {}
    metadata = _answer_metadata(session, messages, questions=True, operation_results=operations)
    from app.modules.advisor.commands.undo import undone_receipts
    undone = undone_receipts(session, {op['receipt_id'] for ops in operations.values() for op in ops
                                       if isinstance(op, dict) and isinstance(op.get('receipt_id'), int)})
    if undone:
        operations = {key: [{**op, 'undone': True} if isinstance(op, dict) and op.get('receipt_id') in undone else op
                            for op in ops] for key, ops in operations.items()}
    return [MessageItem.model_validate(message).model_copy(update={
        'is_final_answer': message.id in metadata, 'source_question': metadata.get(message.id),
        'data_operations': operations.get(message.id, []),
    }) for message in messages]


def latest_feedback(session: Session, conversation_id: int) -> list[AdvisorRecommendation]:
    rows = session.scalars(select(AdvisorRecommendation).join(AdvisorMessage).where(
        AdvisorMessage.conversation_id == conversation_id).order_by(AdvisorRecommendation.id.desc()))
    latest = {}
    for row in rows:
        latest.setdefault(row.message_id, row)
    return list(latest.values())
