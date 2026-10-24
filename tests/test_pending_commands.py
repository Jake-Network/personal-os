from datetime import timedelta
from uuid import uuid4

import pytest

from app.modules.advisor.pending_commands import find_pending_commands, is_data_followup, resolution_allowed
from app.modules.database.model import AdvisorConversation, AdvisorMessage, ContextSnapshot
from app.modules.database.model.advisor_runtime import AdvisorRun
from app.modules.database.model.base import utcnow


def pending(session, *, legacy=False, created_at=None):
    conversation = AdvisorConversation(title='합성 저장 확인')
    session.add(conversation)
    session.flush()
    snapshot = ContextSnapshot(id=str(uuid4()), conversation_id=conversation.id,
        context_categories=['financial'], excluded_categories=[], record_references=[], source_updated_at={},
        data_quality_flags=[], payload={'data': {}}, content_hash='synthetic')
    session.add(snapshot)
    session.flush()
    user = AdvisorMessage(conversation_id=conversation.id, role='user', status='complete',
        content='합성 통장에 300만원 있어. 저장해줘', context_snapshot_id=snapshot.id)
    answer = AdvisorMessage(conversation_id=conversation.id, role='assistant', status='complete',
        content='원화로 기록할까요?', context_snapshot_id=snapshot.id)
    session.add_all([user, answer])
    session.flush()
    command = {'operation':'create','resource':'accounts','selector':{},'values':{'name':'합성 통장','balance':'3000000'}}
    operations = [{'operation':'create','resource':'accounts','status':'needs_input','command_index':0}]
    run = AdvisorRun(id=str(uuid4()), conversation_id=conversation.id, request_id=str(uuid4()), status='completed',
        user_message_id=user.id, assistant_message_id=answer.id, input_payload={'message':user.content},
        runtime_metadata={} if legacy else {'data_command_plan':[command], 'data_command_query':user.content},
        result={'data_operations':operations,'context_snapshot_id':snapshot.id}, created_at=created_at or utcnow())
    session.add(run)
    session.flush()
    current = AdvisorMessage(conversation_id=conversation.id, role='user', status='pending', content='응 이렇게 해줘')
    session.add(current)
    session.flush()
    return conversation, run, current, snapshot


def test_short_confirmation_and_parameter_completion_are_followups():
    for value in ['응 이렇게 해줘','그래','확인','그대로 저장해줘','원화야','USD야','국민은행 계좌야',
                  '응 원화로 해줘', '네 USD로 해주세요']:
        assert is_data_followup(value)
    for value in ['아니','취소','안 할래','내일 일정은 어때?','다른 질문인데 운동 조언해줘','새 통장 하나 만들어줘']:
        assert not is_data_followup(value)


def test_pending_commands_retain_original_authority_and_sources(session):
    conversation, run, current, _ = pending(session)
    result = find_pending_commands(session, conversation_id=conversation.id, message_id=current.id,
        query=current.content, excluded=set())
    assert result is not None
    assert result['commands'][0]['values']['balance'] == '3000000'
    assert result['query'] == run.input_payload['message']
    assert result['source_message_ids'] == [run.user_message_id, run.assistant_message_id]
    assert result['legacy'] is False


def test_recording_permission_survives_more_than_one_clarification(session):
    conversation, run, current, _ = pending(session)
    run.runtime_metadata = {**run.runtime_metadata, 'data_command_recording_allowed':True}
    session.flush()
    result = find_pending_commands(session, conversation_id=conversation.id, message_id=current.id,
        query=current.content, excluded=set())
    assert result['allow_data_recording'] is True
    run.input_payload = {**run.input_payload, 'allow_data_recording':True}
    run.runtime_metadata = {**run.runtime_metadata, 'data_command_recording_allowed':False}
    session.flush()
    assert find_pending_commands(session, conversation_id=conversation.id, message_id=current.id,
        query=current.content, excluded=set())['allow_data_recording'] is False


def test_pending_source_sharing_and_deletion_are_rechecked(session):
    conversation, _, current, snapshot = pending(session)
    assert find_pending_commands(session, conversation_id=conversation.id, message_id=current.id,
        query=current.content, excluded={'financial'}) is None
    snapshot.payload = {'source_purged':True}
    session.flush()
    assert find_pending_commands(session, conversation_id=conversation.id, message_id=current.id,
        query=current.content, excluded=set()) is None


def test_pending_source_message_local_only_policy_blocks_replay(session):
    from app.modules.context.record_privacy import set_record_policy
    conversation, run, current, _ = pending(session)
    set_record_policy(session, 'advisor_messages', run.user_message_id, False)
    assert find_pending_commands(session, conversation_id=conversation.id, message_id=current.id,
        query=current.content, excluded=set()) is None


def test_legacy_pending_request_uses_checked_original_messages(session):
    conversation, run, current, _ = pending(session, legacy=True)
    result = find_pending_commands(session, conversation_id=conversation.id, message_id=current.id,
        query=current.content, excluded=set())
    assert result is not None and result['legacy'] is True
    assert result['commands'] == []
    assert result['clarification'] == '원화로 기록할까요?'
    assert result['source_message_ids'] == [run.user_message_id, run.assistant_message_id]


def test_rejected_model_commands_cannot_become_legacy_authority_after_assent(session):
    conversation, run, current, _ = pending(session)
    run.runtime_metadata = {'data_command_plan': [], 'data_command_query': run.input_payload['message']}
    run.result = {'data_operations':[{'operation':'create','resource':'accounts','status':'needs_input'}]}
    session.flush()
    assert find_pending_commands(session, conversation_id=conversation.id, message_id=current.id,
        query=current.content, excluded=set()) is None


def test_pending_requires_a_valid_stable_command_index(session):
    conversation, run, current, _ = pending(session)
    for index in [None, 1, True]:
        operation = {'operation':'create','resource':'accounts','status':'needs_input'}
        if index is not None:
            operation['command_index'] = index
        run.result = {'data_operations':[operation]}
        session.flush()
        assert find_pending_commands(session, conversation_id=conversation.id, message_id=current.id,
            query=current.content, excluded=set()) is None


def test_pending_request_expires_and_does_not_cross_a_new_topic(session):
    conversation, run, current, _ = pending(session, created_at=utcnow()-timedelta(days=2))
    assert find_pending_commands(session, conversation_id=conversation.id, message_id=current.id,
        query=current.content, excluded=set()) is None
    run.created_at = utcnow()
    current.status='complete'
    session.add(AdvisorRun(id=str(uuid4()),conversation_id=conversation.id,request_id=str(uuid4()),
        status='completed',user_message_id=current.id,input_payload={'message':'오늘 날씨가 궁금해'},result={}))
    session.flush()
    last = AdvisorMessage(conversation_id=conversation.id,role='user',status='pending',content='응')
    session.add(last)
    session.flush()
    assert find_pending_commands(session, conversation_id=conversation.id, message_id=last.id,
        query=last.content, excluded=set()) is None


def test_old_unhandled_assent_turns_do_not_hide_the_pending_request(session):
    conversation, run, current, _ = pending(session)
    current.status = 'complete'
    session.add(AdvisorRun(id=str(uuid4()), conversation_id=conversation.id, request_id=str(uuid4()),
        status='completed', user_message_id=current.id, input_payload={'message':'응 이렇게 해줘'}, result={}))
    session.flush()
    followup = AdvisorMessage(conversation_id=conversation.id,role='user',status='pending',content='그래')
    session.add(followup)
    session.flush()
    found = find_pending_commands(session,conversation_id=conversation.id,message_id=followup.id,
        query=followup.content,excluded=set())
    assert found is not None and found['query'] == run.input_payload['message']


def test_completed_data_command_ends_the_previous_pending_scope(session):
    conversation, _, current, _ = pending(session)
    current.status = 'complete'
    session.add(AdvisorRun(id=str(uuid4()), conversation_id=conversation.id, request_id=str(uuid4()),
        status='completed', user_message_id=current.id, input_payload={'message':'응 이렇게 해줘'},
        result={'data_operations':[{'operation':'create','resource':'accounts','status':'saved'}]}))
    session.flush()
    followup = AdvisorMessage(conversation_id=conversation.id,role='user',status='pending',content='그래')
    session.add(followup)
    session.flush()
    assert find_pending_commands(session,conversation_id=conversation.id,message_id=followup.id,
        query=followup.content,excluded=set()) is None


def test_resolution_cannot_expand_resource_operation_or_original_identity():
    original={'operation':'create','resource':'holdings','values':{'symbol':'AAPL','currency':'USD'}}
    assert resolution_allowed(original,{'operation':'create','resource':'holdings','values':{'symbol':'NASDAQ:AAPL','currency':'USD'}})
    assert resolution_allowed(original,{'operation':'update','resource':'holdings','selector':{'symbol':'AAPL'},'values':{'quantity':'10','currency':'USD'}})
    assert not resolution_allowed(original,{'operation':'delete','resource':'holdings','selector':{'symbol':'AAPL'}})
    assert not resolution_allowed(original,{'operation':'create','resource':'tasks','values':{'title':'새 작업'}})
    assert not resolution_allowed(original,{'operation':'create','resource':'holdings','values':{'symbol':'MSFT','currency':'USD'}})
    assert not resolution_allowed({'operation':'create','resource':'holdings','values':{'symbol':'NASDAQ:ABC'}},
        {'operation':'create','resource':'holdings','values':{'symbol':'NYSE:ABC'}})


def test_bare_assent_cannot_swap_or_remove_original_numbers_or_currency():
    original = {'operation':'create','resource':'holdings','values':{
        'symbol':'AAPL','quantity':'10','avg_cost':'200','currency':'USD'}}
    for values in [
        {'symbol':'AAPL','quantity':'200','avg_cost':'10','currency':'USD'},
        {'symbol':'AAPL','quantity':'10','avg_cost':'200','currency':'KRW'},
        {'symbol':'AAPL','quantity':'10','currency':'USD'},
    ]:
        assert not resolution_allowed(original, {'operation':'create','resource':'holdings','values':values})
    assert resolution_allowed(original, {'operation':'create','resource':'holdings','values':{
        'ticker':'NASDAQ:AAPL','quantity':10,'avg_cost':'200.00','currency':'USD'}})
    assert not resolution_allowed(original, {'operation':'create','resource':'holdings','values':{
        'ticker':'NASDAQ:MSFT','quantity':10,'avg_cost':'200','currency':'USD'}})


def test_clarification_can_correct_a_named_field_with_its_own_new_value():
    original = {'operation':'create','resource':'holdings','values':{
        'symbol':'AAPL','quantity':'10','avg_cost':'200','currency':'USD'}}
    candidate = {'operation':'create','resource':'holdings','values':{
        'symbol':'AAPL','quantity':'12','avg_cost':'200','currency':'USD'}}
    assert resolution_allowed(original, candidate, clarification='수량은 12주가 맞아')
    assert not resolution_allowed(original, candidate, clarification='평균 매입가는 12달러야')
    changed_currency = {**candidate, 'values':{**candidate['values'],'quantity':'10','currency':'KRW'}}
    assert resolution_allowed(original, changed_currency, clarification='통화는 원화야')
    assert not resolution_allowed(original, changed_currency, clarification='응 이렇게 해줘')


def test_same_quantity_can_move_to_delta_without_changing_its_number():
    original = {'operation':'create','resource':'holdings','values':{
        'ticker':'AAPL','quantity':10,'avg_cost':'200','currency':'USD'}}
    candidate = {'operation':'update','resource':'holdings','selector':{'symbol':'NASDAQ:AAPL'},
        'values':{'delta':'10.00','avg_cost':200,'currency':'USD'}}
    assert resolution_allowed(original,candidate)
    assert not resolution_allowed(original,{**candidate,'values':{**candidate['values'],'delta':'200'}})


def test_unchanged_free_form_goal_progress_can_be_preserved_during_clarification():
    original = {'operation':'create','resource':'goals','values':{
        'title':'합성 목표','current_value':'준비 중','target_value':'10km 완주'}}
    assert resolution_allowed(original, {**original,'values':{**original['values'],'status':'active'}})


def test_confirmation_can_include_a_separate_explicit_quote_refresh():
    assert is_data_followup('응 해줘 그리고 최신 현재가 시세 갱신해줘')
    assert is_data_followup('그대로 저장해줘. 그리고 시세도 갱신해줘')
    assert not is_data_followup('최신 현재가 시세 갱신해줘')
    assert not is_data_followup('응 그리고 새 통장 하나 만들어줘')
    assert not is_data_followup('응 해줘 그리고 운동 계획 추천해줘')


def rejected_empty_plan(session, *, version=None):
    conversation, run, current, snapshot = pending(session)
    run.runtime_metadata = {'data_command_plan': [], 'data_command_query': run.input_payload['message']}
    if version is not None:
        run.runtime_metadata = {**run.runtime_metadata, 'data_command_validation_version': version}
    run.result = {'data_operations': [{'operation': 'create', 'resource': 'accounts',
        'status': 'needs_input', 'message': '요청한 변경 내용과 원문의 수치를 확인해 주세요.'}],
        'context_snapshot_id': snapshot.id}
    session.flush()
    return conversation, run, current, snapshot


def test_pre_version_empty_rejection_reextracts_only_the_explicit_checked_original(session):
    conversation, run, current, _ = rejected_empty_plan(session)
    result = find_pending_commands(session, conversation_id=conversation.id, message_id=current.id,
        query=current.content, excluded=set())
    assert result is not None and result['legacy'] is True
    assert result['commands'] == []
    assert result['query'] == run.input_payload['message']
    assert result['operations'][0]['command_index'] == 0
    assert result['source_message_ids'] == [run.user_message_id, run.assistant_message_id]


def test_current_validation_empty_plan_is_not_recovered_after_assent(session):
    conversation, _, current, _ = rejected_empty_plan(session, version=2)
    assert find_pending_commands(session, conversation_id=conversation.id, message_id=current.id,
        query=current.content, excluded=set()) is None


def test_old_empty_rejection_without_user_operation_authority_is_not_recovered(session):
    conversation, run, current, _ = rejected_empty_plan(session)
    run.runtime_metadata = {**run.runtime_metadata, 'data_command_query': '합성 통장 잔액이 궁금해'}
    session.flush()
    assert find_pending_commands(session, conversation_id=conversation.id, message_id=current.id,
        query=current.content, excluded=set()) is None


def test_old_empty_rejection_with_saved_sibling_cannot_reextract_the_saved_item(session):
    conversation, run, current, _ = rejected_empty_plan(session)
    run.result = {**run.result, 'data_operations': [*run.result['data_operations'],
        {'operation': 'create', 'resource': 'workout-logs', 'status': 'saved'}]}
    session.flush()
    assert find_pending_commands(session, conversation_id=conversation.id, message_id=current.id,
        query=current.content, excluded=set()) is None


@pytest.mark.parametrize(('failed_query', 'recovered'), [
    ('응 해줘 그리고 최신 현재가 시세 갱신해줘', True),
    ('원화야 그리고 최신 현재가 시세 갱신해줘', False),
    ('다른 질문인데 최신 현재가 시세 갱신해줘', False),
])
def test_failed_pre_version_compound_confirmation_does_not_hide_original_request(session, failed_query, recovered):
    conversation, run, current, snapshot = rejected_empty_plan(session)
    current.status = 'complete'
    current.context_snapshot_id = snapshot.id
    current.content = failed_query
    answer = AdvisorMessage(conversation_id=conversation.id, role='assistant', status='complete',
        content='작업을 저장하지 못했습니다.', context_snapshot_id=snapshot.id)
    session.add(answer)
    session.flush()
    session.add(AdvisorRun(id=str(uuid4()), conversation_id=conversation.id, request_id=str(uuid4()),
        status='completed', user_message_id=current.id, assistant_message_id=answer.id,
        input_payload={'message': current.content}, runtime_metadata={'data_command_plan': [
            {'operation': 'update', 'resource': 'market-data', 'values': {}, 'selector': {}}]},
        result={'data_operations': [
            {'operation': 'update', 'resource': 'market-data', 'status': 'failed',
             'message': '지원하지 않는 데이터 작업입니다.'},
            *run.result['data_operations']], 'context_snapshot_id': snapshot.id}))
    session.flush()
    latest = AdvisorMessage(conversation_id=conversation.id, role='user', status='pending', content='응 이렇게 해줘')
    session.add(latest)
    session.flush()
    result = find_pending_commands(session, conversation_id=conversation.id, message_id=latest.id,
        query=latest.content, excluded=set())
    if not recovered:
        assert result is None
        return
    assert result is not None
    assert result['query'] == run.input_payload['message']
    assert result['commands'] == []
    assert len(result['operations']) == 1
    assert result['operations'][0]['resource'] == 'accounts'
