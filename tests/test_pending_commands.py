from datetime import timedelta
from uuid import uuid4

import pytest

from app.modules.advisor.commands.pending import find_pending_commands, is_data_followup, resolution_allowed
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


def holding_pending(session):
    conversation, run, current, snapshot = pending(session)
    snapshot.context_categories = ['investment']
    query = 'QALOT $42.25 8주 더 있어. 이 보유분 저장해줘'
    session.get(AdvisorMessage, run.user_message_id).content = query
    command = {'operation': 'update', 'resource': 'holdings', 'command_index': 5,
               'selector': {'symbol': 'QALOT'}, 'values': {'delta': '8', 'avg_cost': '42.25'}}
    run.input_payload = {**run.input_payload, 'message': query}
    run.runtime_metadata = {'data_command_plan': [command], 'data_command_query': query,
                            'data_command_validation_version': 2}
    run.result = {**run.result, 'data_operations': [
        {'operation': 'create', 'resource': 'holdings', 'command_index': 0, 'status': 'saved'},
        {'operation': 'update', 'resource': 'holdings', 'command_index': 5, 'status': 'needs_input'}]}
    session.flush()
    return conversation, run, current, snapshot


def clarification_turn(session, conversation, current, snapshot, query):
    current.status, current.context_snapshot_id, current.content = 'complete', snapshot.id, query
    answer = AdvisorMessage(conversation_id=conversation.id, role='assistant', status='complete',
                            content='계좌가 다르면 별도 보유분으로 저장할 수 있습니다.', context_snapshot_id=snapshot.id)
    session.add(answer)
    session.flush()
    session.add(AdvisorRun(id=str(uuid4()), conversation_id=conversation.id, request_id=str(uuid4()),
        status='completed', user_message_id=current.id, assistant_message_id=answer.id,
        input_payload={'message': query}, runtime_metadata={}, result={}))
    latest = AdvisorMessage(conversation_id=conversation.id, role='user', status='pending', content='그러면 그렇게 해줘')
    session.add(latest)
    session.flush()
    return latest, answer


def test_then_assent_and_explicit_separate_account_save_are_followups():
    assert is_data_followup('그러면 그렇게 해줘')
    assert is_data_followup('그럼 그대로 저장해줘')
    assert is_data_followup('다른 계좌의 별도 보유분으로 저장해줘')
    assert not is_data_followup('그러면 다른 질문인데 운동 추천해줘')


def test_account_separation_discussion_is_checked_and_carried_to_the_pending_request(session):
    conversation, run, current, snapshot = holding_pending(session)
    discussion = '그러면 같은 ticker로 하나 더 저장하면 안되나? 계좌가 서로 다른거에 사놓은 거라서'
    latest, answer = clarification_turn(session, conversation, current, snapshot, discussion)
    result = find_pending_commands(session, conversation_id=conversation.id, message_id=latest.id,
                                   query=latest.content, excluded=set())
    assert result is not None
    assert result['query'].startswith(run.input_payload['message'])
    assert discussion in result['query']
    assert {current.id, answer.id, run.user_message_id, run.assistant_message_id} <= set(result['source_message_ids'])
    assert [operation['command_index'] for operation in result['operations'] if operation['status'] == 'needs_input'] == [5]


@pytest.mark.parametrize('blocked_role', ['user', 'assistant'])
def test_sharing_off_for_the_account_clarification_blocks_pending_recovery(session, blocked_role):
    from app.modules.context.record_privacy import set_record_policy
    conversation, _, current, snapshot = holding_pending(session)
    latest, answer = clarification_turn(session, conversation, current, snapshot,
        '그러면 같은 ticker로 하나 더 저장하면 안되나? 계좌가 서로 다른거에 사놓은 거라서')
    set_record_policy(session, 'advisor_messages', current.id if blocked_role == 'user' else answer.id, False)
    assert find_pending_commands(session, conversation_id=conversation.id, message_id=latest.id,
                                 query=latest.content, excluded=set()) is None


@pytest.mark.parametrize('query', [
    '새로운 질문인데 계좌가 다르면 이직 준비는 어떻게 할까?',
    '같은 ticker로 하나 더 저장하면 안되나? 내일 운동 계획은 어때?',
    '같은 ticker로 하나 더 저장하면 안되나? 친구 계좌가 다른거라서',
])
def test_unrelated_questions_do_not_extend_the_holding_pending_scope(session, query):
    conversation, _, current, snapshot = holding_pending(session)
    latest, _ = clarification_turn(session, conversation, current, snapshot, query)
    assert find_pending_commands(session, conversation_id=conversation.id, message_id=latest.id,
                                 query=latest.content, excluded=set()) is None


def test_reextract_skeleton_preserves_the_original_pending_index(session):
    conversation, run, current, _ = holding_pending(session)
    skeleton = {'operation': 'update', 'resource': 'holdings', 'command_index': 5,
                'selector': {'symbol': 'QALOT'}, 'values': {}, 'reextract': True}
    run.runtime_metadata = {**run.runtime_metadata, 'data_command_plan': [skeleton]}
    session.flush()
    result = find_pending_commands(session, conversation_id=conversation.id, message_id=current.id,
                                   query=current.content, excluded=set())
    assert result is not None and result['commands'] == [skeleton]
    assert result['operations'][-1]['command_index'] == 5


def test_pending_update_can_become_a_separate_create_only_with_current_user_authority():
    original = {'operation': 'update', 'resource': 'holdings', 'selector': {'symbol': 'QALOT'},
                'values': {'delta': '8', 'avg_cost': '42.25'}}
    candidate = {'operation': 'create', 'resource': 'holdings', 'selector': {}, 'separate_position': True,
                 'values': {'symbol': 'QALOT', 'quantity': '8', 'avg_cost': '42.25', 'currency': 'USD'}}
    clarification = '다른 계좌의 별도 보유분으로 저장해줘'
    assert resolution_allowed(original, candidate, clarification)
    assert not resolution_allowed(original, candidate, '응')
    assert not resolution_allowed(original, {**candidate, 'separate_position': False}, clarification)
    assert not resolution_allowed(original, {**candidate, 'values': {**candidate['values'], 'symbol': 'OTHER'}}, clarification)
    assert not resolution_allowed(original, {**candidate, 'values': {**candidate['values'], 'quantity': '16'}}, clarification)


def test_separate_account_authority_does_not_turn_old_numbers_into_a_current_correction():
    original = {'operation': 'update', 'resource': 'holdings', 'selector': {'symbol': 'QALOT'},
                'values': {'delta': '8', 'avg_cost': '42.25'}}
    candidate = {'operation': 'create', 'resource': 'holdings', 'selector': {}, 'separate_position': True,
                 'values': {'symbol': 'QALOT', 'quantity': '8', 'avg_cost': '42.25', 'currency': 'USD'}}
    authority = 'QALOT 평균 매입가 42.25달러 8주 저장해줘. 계좌가 서로 다른거라서'
    assert resolution_allowed(original, candidate, '그러면 그렇게 해줘', authorization_query=authority)
    changed = {**candidate, 'values': {**candidate['values'], 'avg_cost': '8'}}
    assert not resolution_allowed(original, changed, '그러면 그렇게 해줘', authorization_query=authority)


def unindexed_partial_holding_rejection(session, *, label='NYSEARCA:QALOT', plan=True):
    conversation, run, current, snapshot = holding_pending(session)
    saved = [{'operation': 'create', 'resource': 'holdings', 'command_index': index,
              'selector': {}, 'values': {'symbol': f'QASAVED{index}', 'quantity': '1'}} for index in range(5)]
    query = run.input_payload['message']
    run.runtime_metadata = {'data_command_plan': saved if plan else [], 'data_command_query': query,
                            'data_command_validation_version': 2}
    run.result = {**run.result, 'data_operations': [
        *[{'operation': 'create', 'resource': 'holdings', 'command_index': index, 'status': 'saved'} for index in range(5)],
        {'operation': 'update', 'resource': 'holdings', 'status': 'needs_input', 'target_label': label,
         'message': '이 항목의 수량·금액이 사용자 원문과 일치하지 않아 저장하지 않았습니다.'}]}
    session.flush()
    return conversation, run, current, snapshot


def test_version_two_partial_batch_recovers_only_the_unindexed_grounded_holding(session):
    from copy import deepcopy
    conversation, run, current, _ = unindexed_partial_holding_rejection(session)
    metadata, result_before = deepcopy(run.runtime_metadata), deepcopy(run.result)
    result = find_pending_commands(session, conversation_id=conversation.id, message_id=current.id,
                                   query=current.content, excluded=set())
    assert result is not None
    recovered = [command for command in result['commands'] if command.get('reextract')]
    assert recovered == [{'operation': 'update', 'resource': 'holdings', 'selector': {},
                          'values': {'symbol': 'QALOT'}, 'reextract': True, 'command_index': 5}]
    assert [operation['command_index'] for operation in result['operations'] if operation['status'] == 'saved'] == list(range(5))
    assert [operation['command_index'] for operation in result['operations'] if operation['status'] == 'needs_input'] == [5]
    assert run.runtime_metadata == metadata and run.result == result_before


@pytest.mark.parametrize('label', ['invalid ticker label', 'NYSEARCA:ABSENT', 'NYSEARCA:QALOT:OTHER'])
def test_partial_batch_rejection_without_a_valid_original_ticker_is_not_recovered(session, label):
    conversation, _, current, _ = unindexed_partial_holding_rejection(session, label=label)
    assert find_pending_commands(session, conversation_id=conversation.id, message_id=current.id,
                                 query=current.content, excluded=set()) is None


def test_version_two_empty_plan_does_not_gain_recovery_from_a_rejection_label(session):
    conversation, _, current, _ = unindexed_partial_holding_rejection(session, plan=False)
    assert find_pending_commands(session, conversation_id=conversation.id, message_id=current.id,
                                 query=current.content, excluded=set()) is None
