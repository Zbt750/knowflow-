"""Original r5 utterances; routing safety, not model-quality assertions."""
import pytest
from backend.schemas.learning_assistant import StudyContext
from backend.services.assistant_router import route_message

@pytest.mark.parametrize('message,intent', [
    ('我说的是定积分应用，不是洛必达法则。请只保留这个范围。','scope_correction'),
    ('我说的不是洛必达，是等价无穷小，请纠正。','scope_correction'),
    ('你说我独立答对 0 次，但我刚才明明独立答对了一道。请重新核对记录。','evidence_basis'),
])
def test_r5_corrections_are_business_reads(message,intent):
    route=route_message(message,StudyContext(surface='study'))
    assert (route.capability,route.intent)==('data_query',intent)

@pytest.mark.parametrize('message',[
    '我临时只有 25 分钟了。保留最重要的复习内容，减少练习量，其他内容以后再学。先给我修改后的版本，不要马上创建新计划。',
    '我只有 15 分钟，请把原计划缩短，不要重新创建一份。',
])
def test_r5_draft_refinement_is_not_downgraded_when_client_pointer_is_absent(message):
    route=route_message(message,StudyContext(surface='study'))
    assert (route.capability,route.intent,route.reason)==('planner','plan','active_draft_refinement')

def test_explanation_with_write_prohibition_is_still_an_explanation():
    route=route_message('先讲解这个知识点，但不要创建计划。',StudyContext(surface='study'))
    assert route.capability=='qa' and route.reason=='explanation_without_selection'

def test_statistics_and_advice_keep_the_statistics_owner():
    route=route_message('根据我刚才的实际做题情况，告诉我独立答对了几道、独立答错了几道、看解析后答对了几道。请解释你根据哪些记录得出结论，并给我接下来 90 分钟的数学二复习建议。',StudyContext(surface='study'))
    assert (route.capability,route.intent)==('data_query','learning_state')

def test_subject_node_never_counts_as_matching_a_missing_specific_topic():
    from types import SimpleNamespace
    from uuid import uuid4
    from backend.services.assistant_scope_resolution import resolve_topics,document_question
    nodes=[SimpleNamespace(id=uuid4(),code='fixture.math2',name='数学二（SYNTHETIC）'),
        SimpleNamespace(id=uuid4(),code='fixture.lhopital',name='洛必达法则（SYNTHETIC）')]
    results=resolve_topics(nodes,'数学二积分和极限复习60分钟')
    assert {r['topic'] for r in results if r['status']=='unmatched'}=={'积分','极限'}
    assert document_question('这份讲义里有没有写 2021 年真题的第几题？如果没有，请直接说没有记录。')
    assert not document_question('系统题库有多少道真题？')

@pytest.mark.parametrize('message,count',[('从题库挑三道题',3),('找两道练习题',2)])
def test_bare_selection_verbs_keep_the_requested_quantity(message,count):
    from backend.services.learning_assistant_service import requested_count
    assert requested_count(message)==count
