"""F-01..04 through the existing services/SSE in a newly owned PostgreSQL DB."""
from uuid import UUID,uuid4
import pytest
from sqlalchemy import select,func
from tests.integration.test_student_uiv2_repairs import (
    session_factory,clean_database,clean_tasks,conversations,setup,talk,reply,NOW,NoModel,business_rows)
from tests.integration.test_learning_loop import mark_isolated_question_trusted
from backend.models.learning import KnowledgePoint,Question,PracticeItem,DailyPlan
from backend.models.learning_task import LearningTask
from backend.schemas.learning_assistant import AssistantRequest,PlannerHandoff
from backend.schemas.learning_task import CreateTask,ConfirmTask
from backend.services.learning_task_service import create_task,run_task,get_task,confirm_task
from backend.services.question_versions import question_version_reference
from backend.services.question_availability import _descendant_ids
from scripts.naiwa_answer_handoff_provider import HandoffEvidenceProvider


def question_revision(factory, *, root_scope=True, budget=25, estimates=(4,5), change=None):
    sid,ctx,_=setup(factory)
    refs=[]
    with factory.begin() as db:
        source=db.get(Question,ctx.question_id)
        node=db.get(KnowledgePoint,source.kp_id)
        root=node
        while root.parent_id:root=db.get(KnowledgePoint,root.parent_id)
        scope_root=root if root_scope else node
        resolved=sorted(_descendant_ids(db,{scope_root.id}),key=str)
        for index,minutes in enumerate(estimates):
            q=Question(kp_id=node.id,question_type='single_choice',grading_mode=source.grading_mode,
                grading_config=dict(source.grading_config or {}),stem=f'SYNTHETIC final F01 {index}',
                options={'A':'1','B':'0'},correct_answer='A',explanation='SYNTHETIC final answer 1.',
                estimated_minutes=minutes,difficulty='basic',question_role='basic',skill_tags=['F01'])
            mark_isolated_question_trusted(q,db=db)
            refs.append({'question_id':str(q.id),'question_version':question_version_reference(q),'kp_id':str(node.id)})
        if change=='version':db.get(Question,UUID(refs[0]['question_id'])).stem+=' changed'
        elif change=='in_paper':
            db.add(PracticeItem(plan_id=ctx.daily_plan_id,question_id=UUID(refs[0]['question_id']),kp_id=node.id,
                question_version_id=UUID(refs[0]['question_version']),ordinal=2))
        elif change=='ineligible':db.get(Question,UUID(refs[0]['question_id'])).is_active=False
        handoff=PlannerHandoff(source_conversation_id=sid,source_message_id=uuid4(),request_type='plan',
            user_problem='学习范围：'+scope_root.code+'\n我今天有60分钟复习数学二',generated_at=NOW,
            target_knowledge_node_ids=[scope_root.id],available_minutes=60,
            constraints={'scope_version':1,'scope_explicit':True,'resolved_scope_node_ids':list(map(str,resolved))}).model_dump(mode='json')
    request='我临时只有25分钟了。保留最重要的复习内容，减少练习量，先给我修改后的版本，不要马上创建新计划。'
    task=create_task(factory,CreateTask(goal=request,budget_minutes=budget,session_id=sid,current_plan_id=ctx.daily_plan_id),now=NOW)
    with factory.begin() as db:
        row=db.get(LearningTask,task.task_id)
        row.context={**row.context,'previous_goal':handoff['user_problem'],
            'previous_planner_handoff':handoff,'planner_handoff':{**handoff,'available_minutes':budget,
                'constraints':{**handoff['constraints'],'draft_refinement':True,'relax_count':True}},
            'previous_draft':{'questions':refs,'total_minutes':sum(estimates),'review_nodes':[],'review_minutes':0}}
    before=business_rows(factory)
    result=run_task(factory,task.task_id,NoModel(),now=NOW)
    after=business_rows(factory)
    assert {k:v for k,v in before.items() if k!='learning_tasks'}=={k:v for k,v in after.items() if k!='learning_tasks'}
    with factory() as db:assert db.scalar(select(func.count()).select_from(LearningTask).where(LearningTask.session_id==sid))==1
    return result,refs


@pytest.mark.parametrize('root_scope',[True,False])
def test_f01_nine_minute_question_draft_remains_valid_at_25_minutes(session_factory,root_scope):
    result,refs=question_revision(session_factory,root_scope=root_scope)
    assert result.status=='ready' and result.draft['total_minutes']==9,result.message
    assert [(q['question_id'],q['question_version']) for q in result.draft['questions']]==[(q['question_id'],q['question_version']) for q in refs]
    assert get_task(session_factory,result.task_id).draft==result.draft
    assert not result.metrics.get('commit')


@pytest.mark.parametrize('change,reason',[('version','question_version_changed'),('in_paper','already_in_today_plan'),('ineligible','question_not_practice_eligible')])
def test_f01_only_actually_rejected_candidate_is_removed(session_factory,change,reason):
    result,refs=question_revision(session_factory,change=change)
    assert result.status=='ready',result.message
    assert [q['question_id'] for q in result.draft['questions']]==[refs[1]['question_id']]
    step=next(s for s in result.trace if s['tool']=='revalidate_saved_candidates')
    assert len(step['result']['rejected_candidates'])==1
    assert reason in step['result']['rejected_candidates'][0]['reasons']


@pytest.mark.parametrize('estimates,total', [((4,5),4),((6,7),None)])
def test_f01_smaller_legal_budget_and_genuinely_impossible_budget(session_factory,estimates,total):
    result,_=question_revision(session_factory,budget=5,estimates=estimates)
    if total is None:
        assert result.status=='needs_info' and result.draft is None
        assert '预算' in result.message and '版本变化' not in result.message and '已进入今日卷' not in result.message
    else:assert result.status=='ready' and result.draft['total_minutes']==total


@pytest.mark.parametrize('message',[
    '给我看一道洛必达法则的练习题，先不要加入今日卷。',
    '给我看一道洛必达法则的练习题。',
    '帮我找一道洛必达法则的练习题。',
])
def test_f02_f03_f04_real_preview_confirm_and_repeat_are_one_operation(session_factory,message):
    sid,ctx,_=setup(session_factory)
    before=business_rows(session_factory)
    frames=talk(session_factory,sid,AssistantRequest(question=message,study_context=ctx),NoModel())
    preview=reply(session_factory,sid)
    assert preview.metadata_['capability_route']['capability']=='data_query'
    refs=preview.metadata_['read_only_data_query']['preview_questions']
    assert len(refs)==1 and '尚未加入今日卷' in preview.content
    assert '只读学习证据回读' not in preview.content
    assert business_rows(session_factory)==before
    talk(session_factory,sid,AssistantRequest(question='把刚才那道题加入今天的学习。',study_context=ctx),HandoffEvidenceProvider())
    proposed=reply(session_factory,sid)
    assert '只读学习证据回读' not in proposed.content and proposed.status=='completed'
    assert not proposed.metadata_.get('assistant_error_details')
    tid=UUID(proposed.metadata_['planner_task_id'])
    task=get_task(session_factory,tid)
    assert task.status=='ready' and len(task.draft['questions'])==1,task.message
    chosen=task.draft['questions'][0]
    assert (chosen['question_id'],chosen['question_version'])==(refs[0]['question_id'],refs[0]['question_version'])
    after_preview=business_rows(session_factory)
    assert before['practice_items']==after_preview['practice_items'] and before['daily_plans']==after_preview['daily_plans']
    committed=confirm_task(session_factory,tid,ConfirmTask(draft_version=task.draft_version),now=NOW)
    assert committed.metrics['commit']['added_count']==1
    after_commit=business_rows(session_factory)
    for _ in range(2):
        talk(session_factory,sid,AssistantRequest(question='把刚才那道题加入今天的学习。',
            study_context=ctx.model_copy(update={'task_id':tid})),NoModel())
        notice=reply(session_factory,sid)
        state=notice.metadata_['selection_state']
        assert state['state']=='already_in_today_plan'
        assert state['question_id']==chosen['question_id'] and state['question_version_id']==chosen['question_version']
        assert '当前今日卷第' in notice.content and '尚未作答' in notice.content
        assert business_rows(session_factory)==after_commit


def test_f03_missing_antecedent_still_asks_without_writing(session_factory):
    sid,ctx,_=setup(session_factory);before=business_rows(session_factory)
    talk(session_factory,sid,AssistantRequest(question='把刚才那道题加入今天的学习。',study_context=ctx),NoModel())
    assert '没有可确定' in reply(session_factory,sid).content
    assert business_rows(session_factory)==before
