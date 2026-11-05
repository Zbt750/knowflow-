import pytest
from backend.schemas.learning_assistant import StudyContext
from backend.services.assistant_router import route_message
from backend.services.bank_selection_intent import bank_selection_request

@pytest.mark.parametrize('message',[
 '给我从那添加一道到今日卷里难度中等的。','再加一道矩阵的秩，难度中等。',
 '帮我找一道洛必达法则的题加入今日卷。','从当前推荐范围选一道题，难度中等。',
 '帮我加入两道洛必达法则的题进来','在原推荐基础上再加一道行列式的题',
 '给我从题库拿一道差不多的题目给我放在今日学习卷',
 '从我的题库找一道差不多的题加入今日卷'])
def test_bank_operations_never_route_to_generic_qa(message):
    route=route_message(message,StudyContext())
    assert route.reason in {'explicit_bank_selection','read_only_question_preview'}
    assert route.capability in {'planner','data_query'}

def test_concept_question_keeps_qa():
    assert route_message('洛必达法则的适用条件是什么？',StudyContext()).capability=='qa'


@pytest.mark.parametrize(('message','mode','count'),[
    ('帮我加入两道洛必达法则的题进来','append',2),
 ('给我从题库拿一道差不多的题目给我放在今日学习卷','append',1),
 ('从我的题库找一道差不多的题加入今日卷','append',1),
    ('在原来的推荐基础上再加两道洛必达法则','append',2),
    ('原推荐不变，额外加一道行列式的题','append',1),
 ('在原推荐基础上再加一道行列式的题','append',1),
    ('保留原来那些知识点，再补两道极限题','append',2),
    ('只练洛必达法则，再加入两道题','replace',None),
])
def test_home_bank_scope_mode_distinguishes_append_from_explicit_replace(message,mode,count):
    request=bank_selection_request(message)
    assert request is not None
    assert request['scope_mode']==mode
    assert request['append']==(mode=='append')
    assert request['additional_count']==count


@pytest.mark.parametrize('message',[
 '给我从题库拿一道差不多的题目给我放在今日学习卷',
 '从我的题库找一道差不多的题加入今日卷'])
def test_similar_bank_question_to_today_routes_as_real_bank_append(message):
    request=bank_selection_request(message)
    route=route_message(message,StudyContext())
    assert request is not None and request['bank_source'] is True
    assert request['similar'] is True and request['scope_mode']=='append'
    assert request['count']==1 and request['additional_count']==1
    assert route.reason=='explicit_bank_selection' and route.capability=='planner'
