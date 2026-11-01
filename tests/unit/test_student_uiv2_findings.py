"""Original uiv1 student expressions; no network/model calls."""
import pytest
from backend.services.assistant_router import route_message
from backend.services.learner_self_report import extract_self_reports
from backend.schemas.learning_assistant import StudyContext

@pytest.mark.parametrize('message,capability',[
    ('今天只有60分钟了，帮我压缩一下，优先补最薄弱的地方。','planner'),
    ('我其实极限还可以，主要是积分换元经常做错。请根据这个新信息调整。','planner'),
    ('为什么全局数字和这个知识点的数字不一样？请列出你统计的记录依据。','data_query'),
    ('如果没有能做的题，请告诉我原因，并给我其他选择。','data_query'),
    ('我们刚才讨论的是什么？','data_query'),
])
def test_natural_followups_keep_the_actual_business_intent(message,capability):
    task={'status':'ready','committed':False,'budget_minutes':120}
    assert route_message(message,StudyContext(surface='study'),task=task).capability==capability

@pytest.mark.parametrize('message',[
    '我感觉积分换元比较差','我觉得积分换元不太行','我估计积分换元不会',
    '我现在补充一点：我自己感觉积分换元比较差，但还没有做过专门测试。请把它记录为待验证假设，而不是已证实的薄弱点。',
])
def test_natural_student_reports_are_unverified_not_mastery(message):
    rows=extract_self_reports(message)
    assert any(r['topic']=='积分换元' and r['assessment']=='needs_help' for r in rows)
    assert all(r['source']=='self_report' and r['independently_verified'] is False for r in rows)

def test_correction_keeps_both_the_positive_and_negative_statement():
    rows=extract_self_reports('我其实极限还可以，主要是积分换元经常做错。请根据这个新信息调整。')
    assert {(r['topic'],r['assessment']) for r in rows}=={('极限','can_use'),('积分换元','needs_help')}

@pytest.mark.parametrize('message',[
    '帮我找一道等比级数的题，先预览，不要加入今日卷。',
    '我想找一道等价无穷小的题。',
])
def test_read_preview_is_not_a_ninety_minute_planning_request(message):
    route=route_message(message,StudyContext(surface='study'))
    assert (route.capability,route.intent)==('data_query','find')
