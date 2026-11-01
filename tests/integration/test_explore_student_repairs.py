"""Disposable PostgreSQL regressions from ex4 student report, never UI PASS."""
from datetime import timedelta
from uuid import uuid4
import pytest
from sqlalchemy import select, text, func
from tests.integration.test_learning_loop import session_factory, clean_database, mark_isolated_question_trusted
from tests.integration.test_learning_tasks import clean_tasks, PlanningProvider
from tests.integration.test_learning_assistant import conversations, setup, talk, reply, NOW
from backend.models.learning import Question, QuestionAttempt, KnowledgePoint, DailyPlan, PracticeItem
from backend.models.learning_task import LearningTask
from backend.models.chat import ChatSession
from backend.schemas.learning_assistant import AssistantRequest
from backend.schemas.learning_task import CreateTask, ConfirmTask
from backend.services.learning_task_service import create_task, run_task, confirm_task, get_task
from backend.services.learning_assistant_service import prepare_planner, planner_handoff
from backend.services.assistant_router import route_message
from backend.services.assistant_data_queries import execute_read_only_data_query
from backend.services.learner_self_report import read_self_reports
from backend.services.answer_submission_service import submit_answer, record_answer_reveal
from backend.services.personal_generation_intent import generation_intent, generation_confirmation
from backend.errors import AppError
from scripts.naiwa_answer_handoff_provider import HandoffEvidenceProvider


class NoModel:
    def __getattr__(self, name):
        raise AssertionError('No model operation allowed: ' + name)


def business_rows(factory):
    tables=['kp_states','kp_mastery_policies','kp_graduation_question_set_versions',
        'question_attempts','learning_events','practice_items','daily_plans','questions','question_versions',
        'learning_tasks','practice_requests','personal_generation_batches']
    with factory() as db:
        return {table:sorted(str(r) for r in db.execute(text(f'SELECT to_jsonb(t) FROM {table} t')).scalars()) for table in tables}


def test_self_report_is_persisted_correctable_session_owned_and_not_mastery(session_factory):
    sid,ctx,_=setup(session_factory)
    before=business_rows(session_factory)
    frames=talk(session_factory,sid,AssistantRequest(question='我不会等价无穷小替换',study_context=ctx),NoModel())
    assert next(d for e,d in frames if e=='done')['status']=='completed'
    assert '已记录在本会话' in reply(session_factory,sid).content
    with session_factory() as db:
        reports=read_self_reports(db,sid)
        assert reports[0]['topic']=='等价无穷小替换' and reports[0]['source']=='self_report'
    talk(session_factory,sid,AssistantRequest(question='等价无穷小替换我会用',study_context=ctx),NoModel())
    with session_factory() as db:
        assert read_self_reports(db,sid)[0]['assessment']=='can_use'
    assert business_rows(session_factory)==before
    other,other_ctx,_=setup_another_session(session_factory,ctx)
    talk(session_factory,other,AssistantRequest(question='根据什么判断我的薄弱点？',study_context=other_ctx),NoModel())
    assert '本会话尚未保存' in reply(session_factory,other).content
    assert not reply(session_factory,other).metadata_['read_only_data_query']['learner_self_reports']


def setup_another_session(factory,ctx):
    with factory.begin() as db:
        session=ChatSession(mode='builtin',purpose='study',study_date='2026-01-01');db.add(session);db.flush()
        return session.id,ctx.model_copy(update={'conversation_id':session.id}),None


@pytest.mark.parametrize('question',[
    '你说我级数很差，但我还没做过级数题，你为什么这么判断？',
    '你把我的薄弱点记错了，我真正不会的是等价无穷小替换，洛必达我会用。',
    '是我的自述还是实际作答记录？根据什么？',
    '你刚才说我极限最差，但我最近极限连续答对了，真正容易错的是积分换元。请根据记录重新判断。',
])
def test_attribution_answers_evidence_not_teaching_sample(session_factory,question):
    sid,ctx,_=setup(session_factory);before=business_rows(session_factory)
    talk(session_factory,sid,AssistantRequest(question=question,study_context=ctx),NoModel())
    answer=reply(session_factory,sid)
    assert '统计范围' in answer.content and '时间窗口' in answer.content
    assert '待验证假设' in answer.content and '不能据此判断' in answer.content
    assert '逐项求导' not in answer.content
    assert business_rows(session_factory)==before


def test_positive_self_report_does_not_confirm_mastery_without_objective_attempts(session_factory):
    sid,ctx,_=setup(session_factory);before=business_rows(session_factory)
    question='我觉得自己已经掌握了洛必达法则，但还没做过题。你能确认我掌握了吗？'
    talk(session_factory,sid,AssistantRequest(question=question,study_context=ctx),NoModel())
    answer=reply(session_factory,sid)
    assert '学生自述' in answer.content and '未经独立核验' in answer.content
    assert '不能确认已掌握' in answer.content
    assert '没有读取到' not in answer.content
    assert answer.metadata_['read_only_data_query']['learner_self_reports'][0]['independently_verified'] is False
    assert business_rows(session_factory)==before


def test_global_recent_statistics_include_multiple_nodes_and_classify_assistance(session_factory):
    sid,ctx,_=setup(session_factory)
    with session_factory.begin() as db:
        questions=list(db.scalars(select(Question).where(Question.question_type=='single_choice').order_by(Question.kp_id,Question.id)))
        # Prefer different knowledge points; each receipt is a real submission.
        chosen=list({q.kp_id:q for q in questions}.values())[:3]
        assert len(chosen)>=2
        ids=[]
        for i,q in enumerate((chosen*3)[:6]):
            p=DailyPlan(study_date=f'2026-01-{i+2:02d}',status='active');db.add(p);db.flush()
            item=PracticeItem(plan_id=p.id,kp_id=q.kp_id,question_id=q.id,ordinal=1);db.add(item);db.flush()
            ids.append((item.id,q.correct_answer,next(k for k in q.options if k!=q.correct_answer),q.kp_id))
    for i,(item_id,correct,wrong,_) in enumerate(ids):
        with session_factory.begin() as db:
            if i==4:record_answer_reveal(db,item_id=item_id,now=NOW-timedelta(seconds=2))
            submit_answer(db,item_id=item_id,raw_answer=None,selected_option=correct if i in (0,4,5) else wrong,
                idempotency_key=f'explore-stats-{i}',now=NOW-timedelta(days=40) if i==5 else NOW-timedelta(seconds=1))
    before=business_rows(session_factory)
    result=execute_read_only_data_query(session_factory,session_id=sid,ctx=ctx,message='我最近做得怎么样？',query_type='learning_state',now=NOW)
    assert result['evidence']['scope_source']=='global_recent_learning'
    assert result['evidence']['attempt_summary']=={'independent_right':1,'independent_wrong':3,'assisted_right':1,'assisted_wrong':0,'unknown':0}
    assert result['evidence']['attempt_count']==5
    with session_factory() as db: node=db.get(KnowledgePoint,ids[0][3]);name=node.name
    narrow=execute_read_only_data_query(session_factory,session_id=sid,ctx=ctx,message=f'{name}最近掌握情况如何？',query_type='learning_state',now=NOW)
    assert narrow['evidence']['scope_source']=='explicit_message_scope'
    assert 0<narrow['evidence']['attempt_count']<5
    assert '最近30天' in result['answer'] and '全库' in result['answer']
    assert business_rows(session_factory)==before


def test_generation_unknown_scope_does_not_borrow_current_question_or_consume_model(session_factory):
    sid,ctx,_=setup(session_factory)
    # ex4 only had seven nodes and no equivalent-infinitesimal node. The full
    # integration seed does contain it, so reproduce ex4's inventory explicitly
    # inside this disposable database before taking the protection snapshot.
    with session_factory.begin() as db:
        for node in db.scalars(select(KnowledgePoint)):
            if node.name in '等价无穷小替换':node.is_active=False
    before=business_rows(session_factory)
    prompt='给我出两道等价无穷小替换诊断题，第一道基础、第二道稍微绕一点。'
    with session_factory() as db:
        with pytest.raises(AppError) as error:generation_intent(db,prompt,ctx,uuid4())
        assert error.value.code=='personal_generation_scope_required'
        card=generation_confirmation(db,prompt,ctx,uuid4())
        assert card['selected_kp_id'] is None and '没有找到' in card['message'] and card['nodes']
        selected=generation_intent(db,prompt,ctx,uuid4(),confirmed_kp_id=ctx.knowledge_node_ids[0])
        assert selected.targets[0].kp_id==ctx.knowledge_node_ids[0] and not selected.append_to_today
    talk(session_factory,sid,AssistantRequest(question=prompt,study_context=ctx),NoModel())
    talk(session_factory,sid,AssistantRequest(question='确定 等价无穷小替换',study_context=ctx),NoModel())
    assert '未找到知识点' in reply(session_factory,sid).content
    assert business_rows(session_factory)==before


def test_undetermined_answer_is_not_counted_as_independent_wrong_or_correct(session_factory):
    sid,ctx,_=setup(session_factory)
    with session_factory.begin() as db:
        q=Question(kp_id=ctx.knowledge_node_ids[0],question_type='fill_blank',stem='SYNTHETIC：计算1',
            correct_answer='1',explanation='SYNTHETIC fixture',estimated_minutes=3,grading_config={'method':'numeric_final','verified':True})
        mark_isolated_question_trusted(q,db=db);db.add(q);db.flush()
        item=PracticeItem(plan_id=ctx.daily_plan_id,kp_id=q.kp_id,question_id=q.id,ordinal=2);db.add(item);db.flush()
        result=submit_answer(db,item_id=item.id,raw_answer=None,selected_option=None,idempotency_key='explore-unknown-answer',now=NOW)
        assert result.result=='unknown'
    before=business_rows(session_factory)
    answer=execute_read_only_data_query(session_factory,session_id=sid,ctx=ctx,message='我最近做得怎么样？',query_type='learning_state',now=NOW)
    assert answer['evidence']['attempt_summary']['unknown']==1
    assert answer['evidence']['attempt_summary']['independent_wrong']==0
    assert business_rows(session_factory)==before


def test_self_report_is_passed_to_planner_as_unverified_separate_evidence(session_factory):
    import json
    from backend.services.learning_task_service import _finalization_messages
    sid,ctx,_=setup(session_factory)
    talk(session_factory,sid,AssistantRequest(question='我不会等价无穷小替换',study_context=ctx),NoModel())
    ctx=ctx.model_copy(update={'conversation_id':sid})
    question='给我数学二复习建议，不要创建计划'
    handoff=planner_handoff(session_factory,ctx=ctx,user_id=uuid4(),message=question,route=route_message(question,ctx),now=NOW)
    task=prepare_planner(session_factory,ctx=ctx,handoff=handoff,now=NOW)
    with session_factory() as db:reports=db.get(LearningTask,task.task_id).context['learner_self_reports']
    assert reports[0]['source']=='self_report' and reports[0]['independently_verified'] is False
    envelope=json.loads(_finalization_messages(question,90,'recommend',[],None,self_reports=reports)[1]['content'])
    assert envelope['evidence']['learner_self_reports']==reports and envelope['write_permission'] is False


def test_plan_without_artifact_is_honest_and_never_commits(session_factory):
    class MissingPlan:
        def tool_turn(self,*args,**kwargs):
            return {'message':{'content':'{"message":"已安排好了。","needs_clarification":false}'},'model':'OFFLINE'}
    created=create_task(session_factory,CreateTask(goal='我今天有90分钟，请安排数学二高数和线代复习',budget_minutes=90),now=NOW)
    before=business_rows(session_factory)
    result=run_task(session_factory,created.task_id,MissingPlan(),now=NOW)
    assert result.status=='needs_info' and result.draft is None and result.error_code=='plan_draft_missing'
    assert '90分钟' in result.message and 'validate_plan' in result.message and '保留' in result.message
    assert '已安排好了' not in result.message and '没有新题可追加' not in result.message
    after=business_rows(session_factory);assert {k:v for k,v in after.items() if k!='learning_tasks'}=={k:v for k,v in before.items() if k!='learning_tasks'}


def test_new_sixty_minute_preview_preserves_old_draft_and_confirms_exact_question_minutes(session_factory):
    sid,ctx,_=setup(session_factory)
    original=create_task(session_factory,CreateTask(goal='安排洛必达练习',budget_minutes=90,session_id=sid,current_plan_id=ctx.daily_plan_id),now=NOW)
    ready90=run_task(session_factory,original.task_id,PlanningProvider(),now=NOW)
    assert ready90.status=='ready'
    ctx=ctx.model_copy(update={'conversation_id':sid,'task_id':original.task_id})
    question='我改变主意了，今天只学60分钟，安排洛必达练习，不要覆盖原来的90分钟计划。'
    route=route_message(question,ctx)
    handoff=planner_handoff(session_factory,ctx=ctx,user_id=uuid4(),message=question,route=route,now=NOW)
    fresh=prepare_planner(session_factory,ctx=ctx,handoff=handoff,now=NOW)
    assert fresh.task_id!=original.task_id and fresh.budget_minutes==60
    assert get_task(session_factory,original.task_id).model_dump()==ready90.model_dump()
    with session_factory() as db:before_items=db.scalar(select(func.count()).select_from(PracticeItem))
    ready60=run_task(session_factory,fresh.task_id,PlanningProvider(),now=NOW)
    assert ready60.status=='ready' and ready60.draft['budget_minutes']==60
    assert ready60.draft['total_minutes']==sum(q['minutes'] for q in ready60.draft['questions'])+ready60.draft['review_minutes']
    assert f"预计{ready60.draft['total_minutes']}分钟" in ready60.message
    with session_factory() as db:assert db.scalar(select(func.count()).select_from(PracticeItem))==before_items
    committed=confirm_task(session_factory,fresh.task_id,ConfirmTask(draft_version=ready60.draft_version),now=NOW)
    assert committed.metrics['commit']['added_count']==len(ready60.draft['questions'])
    assert not get_task(session_factory,original.task_id).metrics.get('commit')
    assert confirm_task(session_factory,fresh.task_id,ConfirmTask(draft_version=ready60.draft_version),now=NOW).metrics['commit']==committed.metrics['commit']
