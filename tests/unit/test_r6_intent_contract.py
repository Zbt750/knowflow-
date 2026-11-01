import pytest
from backend.services.assistant_router import route_message
from backend.schemas.learning_assistant import StudyContext

PLAN_INPUTS=[
    '帮我安排 60 分钟的洛必达法则学习。',
    '安排洛必达法则 60 分钟。',
    '我只有 60 分钟，想复习洛必达法则，先给我看看安排，不要直接加入今日卷。',
    '给我一份 60 分钟的洛必达法则复习计划，先不要创建。',
]
@pytest.mark.parametrize('text',PLAN_INPUTS)
def test_r6_preview_is_plan_without_write_permission(text):
    route=route_message(text,StudyContext(surface='study'))
    assert (route.capability,route.intent,route.reason)==('planner','plan','study_activity_schedule')
    assert route.write_risk is False

def test_statistics_are_not_a_plan_request():
    route=route_message('我独立答对了几道',StudyContext(surface='study'))
    assert (route.capability,route.intent)==('data_query','learning_state')

def test_plain_recommendation_is_not_promoted_to_a_confirmable_plan():
    route=route_message('给我60分钟数学二复习建议，不创建正式计划',StudyContext(surface='study'))
    assert route.intent=='recommend' and route.write_risk is False

@pytest.mark.parametrize('message',['先讲解这个知识点，不要创建计划','讲讲二分查找'])
def test_r6_offline_provider_cannot_substitute_a_power_series_lesson(message):
    from scripts.manual_naiwa_experience import FixedProvider
    text,_=FixedProvider().complete([{'role':'user','content':message}])
    assert '预设教学样例' not in text and '以幂级数为例' not in text
    assert '固定' in text and '不' in text

@pytest.mark.parametrize('message',[
    '我改变主意了，今天只学60分钟，安排洛必达练习，不要覆盖原来的90分钟计划。',
    '安排60分钟的洛必达练习，先给我看看',
])
def test_r6_question_practice_request_preserves_the_question_draft_contract(message):
    route=route_message(message,StudyContext(surface='study'))
    assert route.capability=='planner' and route.intent=='plan'
    assert route.reason=='explicit_bank_selection'
