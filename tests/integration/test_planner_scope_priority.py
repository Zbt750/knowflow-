from datetime import timedelta
from uuid import UUID,uuid4
import pytest
from sqlalchemy import select
from tests.integration.test_learning_assistant import session_factory,clean_database,conversations,setup,NOW
from tests.integration.test_learning_tasks import clean_tasks
from backend.models.learning import KnowledgePoint,Question,QuestionAttempt,PracticeItem
from backend.models.learning_task import LearningTask
from backend.schemas.learning_task import QuestionAvailabilityQuery
from backend.services.learning_assistant_service import planner_handoff,prepare_planner
from backend.services.assistant_router import CapabilityRoute
from backend.services.learning_task_tools import TaskTools

def handoff(factory,ctx,text):
    return planner_handoff(factory,ctx=ctx,user_id=uuid4(),message=text,
        route=CapabilityRoute('planner','recommend',1,'test'),now=NOW)

def prepared(factory):
    sid,ctx,_=setup(factory)
    return sid,ctx.model_copy(update={'conversation_id':sid,'subject':'考研数学'})

@pytest.mark.parametrize('text,origin',[
    ('根据最近错题和薄弱点，给我90分钟数学二整体复习建议，不创建计划','explicit_subject_scope'),
    ('给我数学二复习建议，结合最近错题和薄弱点','explicit_subject_scope'),
    ('只复习洛必达法则30分钟，不创建计划','explicit_user_scope'),
    ('数学二整体复习安排里，这次只复习洛必达法则','explicit_user_scope'),
    ('数学二整体复习，不要只限制在当前题目','explicit_subject_scope'),
    ('给我数学二复习建议，不要只围绕当前这道题','explicit_subject_scope'),
    ('数学二整体复习安排里，这次只复习当前这道题','explicit_current_question'),
    ('围绕当前题目给我复习建议','explicit_current_question'),
    ('先给我一些复习建议','current_study_context'),
    ('给我数学二一元函数微分学这一章节的复习建议','explicit_user_scope')])
def test_scope_precedence_and_tools(session_factory,text,origin):
    sid,ctx=prepared(session_factory)
    h=handoff(session_factory,ctx,text)
    assert h.constraints['scope_origin']==origin
    ids={UUID(i) for i in h.constraints['resolved_scope_node_ids']}
    with session_factory() as db:
        selected=list(db.scalars(select(KnowledgePoint).where(KnowledgePoint.id.in_(ids))))
        assert all(n.subject=='考研数学' for n in selected)
    if origin=='explicit_subject_scope':
        assert ctx.knowledge_node_ids[0] in ids and len(ids)>1
    elif origin in {'explicit_user_scope','explicit_current_question','current_study_context'}:
        if '一元函数微分学' not in text:assert ids==set(ctx.knowledge_node_ids)
    tools=TaskTools(session_factory,budget_minutes=90,now=NOW,goal=text,handoff=h.model_dump(mode='json'))
    result=tools.execute('get_question_availability',{})
    assert set(result['scope_node_ids']).issubset({str(i) for i in ids})
    with session_factory() as db:
        other=db.scalar(select(KnowledgePoint.id).where(KnowledgePoint.subject=='408',KnowledgePoint.is_assessable.is_(True)))
    with pytest.raises(ValueError):tools.execute('get_question_availability',{'kp_ids':[str(other)]})

def test_math2_recommendation_scope_is_persisted_and_matches_tool_evidence(session_factory):
    sid,ctx=prepared(session_factory)
    text='根据最近错题和薄弱点，给我90分钟数学二整体复习建议，不要只围绕当前洛必达题，也不要创建计划'
    h=handoff(session_factory,ctx,text)
    expected_scope=set(h.constraints['resolved_scope_node_ids'])
    assert h.constraints['scope_origin']=='explicit_subject_scope'
    assert len(expected_scope)>1
    task=prepare_planner(session_factory,ctx=ctx,handoff=h,now=NOW)
    with session_factory() as db:
        row=db.get(LearningTask,task.task_id)
        persisted=(row.context or {})['planner_handoff']
        assert persisted['constraints']['resolved_scope_node_ids']==h.constraints['resolved_scope_node_ids']
        assert persisted['target_knowledge_node_ids']==[str(k) for k in h.target_knowledge_node_ids]
        target_codes=list(db.scalars(select(KnowledgePoint.code).where(
            KnowledgePoint.id.in_(h.target_knowledge_node_ids))))
        goal=row.goal
    assert goal.startswith('学习范围：')
    assert target_codes and all(code in goal.splitlines()[0] for code in target_codes)
    assert {str(node_id) for node_id in h.target_knowledge_node_ids}.issubset(expected_scope)

    tools=TaskTools(session_factory,budget_minutes=90,now=NOW,goal=text,handoff=persisted)
    inventory=tools.execute('get_question_availability',{})
    assert set(inventory['scope_node_ids']).issubset(expected_scope)
    eligible=next((node for node in inventory['eligible_nodes'] if node['practice_eligible_count']>0),None)
    assert eligible is not None, 'integration fixture must contain at least one eligible math2 question'
    kp_id=eligible['kp_id']
    state=tools.execute('get_learning_state',{'kp_ids':[kp_id]})
    assert {item['kp_id'] for item in state['states']}=={kp_id}
    candidates=tools.execute('find_questions',{'kp_ids':[kp_id]})
    assert candidates['questions']
    assert all(item['kp_id']==kp_id and item['kp_id'] in expected_scope for item in candidates['questions'])
    with session_factory() as db:
        assert db.get(LearningTask,task.task_id).context['planner_handoff']['constraints']['scope_origin']=='explicit_subject_scope'

def test_same_session_range_survives_refresh_but_explicit_page_override_wins(session_factory):
    sid,ctx=prepared(session_factory)
    h=handoff(session_factory,ctx,'数学二整体复习90分钟，只给建议')
    t=prepare_planner(session_factory,ctx=ctx,handoff=h,now=NOW)
    continuation=handoff(session_factory,ctx,'时间改成30分钟，继续给建议')
    assert continuation.constraints['scope_origin']=='same_session_explicit_scope'
    assert continuation.constraints['resolved_scope_node_ids']==h.constraints['resolved_scope_node_ids']
    leaf=handoff(session_factory,ctx,'改成只复习洛必达法则')
    assert leaf.constraints['resolved_scope_node_ids']==[str(ctx.knowledge_node_ids[0])]
    prepare_planner(session_factory,ctx=ctx,handoff=leaf,now=NOW)
    switched=handoff(session_factory,ctx,'切回数学二整体复习')
    assert switched.constraints['scope_origin']=='explicit_subject_scope'
    # Another conversation must not inherit the first conversation's range.
    foreign=ctx.model_copy(update={'conversation_id':uuid4(),'task_id':t.task_id})
    isolated=handoff(session_factory,foreign,'给我复习建议')
    assert isolated.constraints['scope_origin']=='current_study_context'
    # Stale tasks do not become remembered scope.
    with session_factory.begin() as db:
        for row in db.scalars(select(LearningTask).where(LearningTask.session_id==sid)):
            row.context={**row.context,'current_plan':{'study_date':'2025-12-31'}}
    assert handoff(session_factory,ctx,'给我复习建议').constraints['scope_origin']=='current_study_context'

def test_recent_wrong_scope_uses_multiple_recorded_nodes_not_current_leaf(session_factory):
    sid,ctx=prepared(session_factory)
    with session_factory.begin() as db:
        questions=list(db.scalars(select(Question).join(KnowledgePoint).where(KnowledgePoint.subject=='考研数学')))
        picked={q.kp_id:q for q in questions}
        assert len(picked)>1
        for index,q in enumerate(list(picked.values())[:2]):
            item=PracticeItem(plan_id=ctx.daily_plan_id,question_id=q.id,kp_id=q.kp_id,ordinal=10+index)
            db.add(item);db.flush()
            db.add(QuestionAttempt(practice_item_id=item.id,question_id=q.id,kp_id=q.kp_id,
                objective_result='wrong',submitted_at=NOW,idempotency_key=str(uuid4()),result_state='LEARNING',reason_code='test'))
    h=handoff(session_factory,ctx,'按最近错题涉及的多个知识点，给我数学二复习建议')
    assert h.constraints['scope_origin']=='explicit_recent_wrong_scope'
    assert len(h.constraints['resolved_scope_node_ids'])>=2

def test_empty_wrong_scope_does_not_expand_to_whole_bank(session_factory):
    sid,ctx=prepared(session_factory)
    h=handoff(session_factory,ctx,'只复习最近错题涉及的数学二知识点')
    assert h.constraints['resolved_scope_node_ids']==[]
    tools=TaskTools(session_factory,budget_minutes=30,now=NOW,goal=h.user_problem,handoff=h.model_dump(mode='json'))
    assert tools.execute('get_question_availability',{})['practice_eligible_count']==0

@pytest.mark.parametrize('message',[
    '根据最近错题和薄弱点，给我90分钟数学二整体复习建议，不创建计划',
    '改成只复习洛必达法则30分钟，只给建议，不创建计划',
    '围绕当前题目给我复习建议', '时间减少到30分钟，继续给我建议，不创建计划'])
def test_natural_advice_enters_planner_not_generic_qa(session_factory,message):
    from backend.services.assistant_router import route_message
    _,ctx=prepared(session_factory)
    route=route_message(message,ctx)
    assert route.capability=='planner' and route.intent=='recommend'

def test_stream_data_query_cannot_overwrite_explicit_planner_route(session_factory):
    import json
    from tests.integration.test_learning_assistant import talk
    from backend.schemas.learning_assistant import AssistantRequest
    sid,ctx=prepared(session_factory)
    class Model:
        model='fixed-routing-only-no-network'
        def tool_turn(self,messages,tools,*,timeout):
            return {'message':{'content':json.dumps({'message':'隔离路由测试，没有写入计划。','needs_clarification':True})}}
    frames=talk(session_factory,sid,AssistantRequest(question='根据最近错题和薄弱点，给我90分钟数学二整体复习建议，不创建计划',study_context=ctx),Model())
    assert next(data for event,data in frames if event=='route')['capability']=='planner'
    assert any(event=='planner' for event,_ in frames)
