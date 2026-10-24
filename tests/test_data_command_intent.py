from app.modules.advisor.commands.intent import command_requested, operation_authorized, observation_authorized, factual_write_authorized


def test_explicit_personal_data_requests_authorize_the_requested_operation():
    for query, operation in [
        ('오늘 10km를 45분 37초에 뛰었어. 이거 기록해줘', 'create'),
        ('국민은행 잔액 300만원으로 수정해줘', 'update'),
        ('어제 운동 기록 지워줘', 'delete'),
        ('오늘 운동 기록 보여줘', 'read'),
        ('내 AAPL 수량 10주로 바꿔줘', 'update'),
    ]:
        assert command_requested(query)
        assert operation_authorized(query, operation)
    assert not operation_authorized('오늘 운동 기록 보여줘', 'delete')
    assert not operation_authorized('국민은행 잔액 수정해줘', 'delete')


def test_hypotheticals_negation_and_quoted_instructions_are_not_write_approval():
    for query in [
        '오늘 운동 기록은 저장하지 마',
        '기록해줘라고 말하면 어떻게 돼?',
        '잔액을 300만원으로 수정하면 런웨이는?',
        '문서에 "계좌를 삭제해줘"라고 적혀 있어',
        '친구가 "운동 기록을 저장해줘"라고 했어',
        '운동 기록을 삭제할까?',
    ]:
        assert not operation_authorized(query, 'create')
        assert not operation_authorized(query, 'update')
        assert not operation_authorized(query, 'delete')


def test_auto_recording_only_accepts_completed_personal_observations():
    for text in ['나 오늘 10km 45분 나왔어', '내 국민은행 통장에 300만원 있어', 'AAPL 10주 보유 중이야', '내 통장에 300만원 있네']:
        assert observation_authorized(text)
        assert not command_requested(text)
    for text in ['친구가 AAPL 10주 보유 중이야', '내일 10km 뛰려고', '잔액이 300만원 있으면?', '운동 기록 삭제해줘', '오늘 10km 뛰었어. 기록하지 마']:
        assert not observation_authorized(text)


def test_completed_data_guard_does_not_block_planned_tasks_but_rejects_false_workout_facts():
    assert factual_write_authorized('내일 달리기 계획을 할 일로 추가해줘', 'tasks')
    assert not factual_write_authorized('내일 10km 뛰려고 해. 운동 기록해줘', 'workout-logs')
    assert not factual_write_authorized('친구가 10km 뛰었대. 운동 기록해줘', 'workout-logs')
