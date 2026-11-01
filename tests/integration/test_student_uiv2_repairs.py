"""New disposable PostgreSQL only; never claim browser UI/model quality."""
from sqlalchemy import select
from tests.integration.test_learning_loop import session_factory,clean_database
from tests.integration.test_learning_tasks import clean_tasks
from tests.integration.test_learning_assistant import conversations,setup,talk,reply,NOW
from tests.integration.test_explore_student_repairs import business_rows
from backend.schemas.learning_assistant import AssistantRequest
from backend.models.learning_task import LearningTask
from backend.schemas.learning_task import ConfirmTask
from backend.services.learning_task_service import confirm_task,get_task
from backend.services.assistant_data_queries import execute_read_only_data_query
from backend.services.assistant_router import route_message
from backend.services.learner_self_report import read_self_reports
from backend.models.learning import Question,PracticeItem,KnowledgePoint
from backend.errors import AppError
from datetime import timedelta
import pytest

class NoModel:
    def tool_turn(self,*args,**kwargs):
        return {'message':{'content':'{"message":"没有可追加新题。","needs_clarification":false}'},'model':'OFFLINE-REGRESSION'}

def test_explicit_hint_stays_on_original_assistance_contract(session_factory):
    from tests.integration.test_learning_assistant import QAProvider
    sid,ctx,_=setup(session_factory);provider=QAProvider()
    frames=talk(session_factory,sid,AssistantRequest(question='一点提示',study_context=ctx,qa_action='hint_1'),provider)
    assert provider.prompts,reply(session_factory,sid).metadata_.get('assistant_error_details',frames)

def test_existing_paper_can_produce_an_executable_timeboxed_activity_preview(session_factory):
    # Positive mixed-topic fixture: the small default syllabus omits integrals.
    # Import the actual taxonomy before expecting a plan for that topic.
    from backend.services.exam_reference_service import sync_exam_reference_index
    with session_factory.begin() as db:
        sync_exam_reference_index(db)
    sid,ctx,_=setup(session_factory);before=business_rows(session_factory)
    text='我数学二还有30天考试，每天能学2小时，极限和积分都不太熟。你先帮我安排今天的复习。'
    talk(session_factory,sid,AssistantRequest(question=text,study_context=ctx),NoModel())
    with session_factory() as db:
        task=db.scalar(select(LearningTask).where(LearningTask.session_id==sid).order_by(LearningTask.created_at.desc()))
        assert task and task.draft and task.draft['kind']=='activity_schedule'
        assert sum(a['minutes'] for a in task.draft['activities'])==120
        assert any(a.get('practice_items') for a in task.draft['activities'])
        assert not task.metrics.get('commit')
    after=business_rows(session_factory)
    assert {k:v for k,v in before.items() if k!='learning_tasks'}=={k:v for k,v in after.items() if k!='learning_tasks'}

def test_unspecified_budget_requests_information_without_inventing_ninety_minutes(session_factory):
    sid,ctx,_=setup(session_factory);before=business_rows(session_factory)
    talk(session_factory,sid,AssistantRequest(question='你先帮我安排今天的数学二复习',study_context=ctx),NoModel())
    assert '可用' in reply(session_factory,sid).content and '分钟' in reply(session_factory,sid).content
    assert '90分钟学习计划' not in reply(session_factory,sid).content
    assert business_rows(session_factory)==before

def test_schedule_refinement_confirmation_and_replay_never_append_a_paper(session_factory):
    sid,ctx,_=setup(session_factory)
    talk(session_factory,sid,AssistantRequest(question='安排90分钟数学二整体复习',study_context=ctx),NoModel())
    with session_factory() as db:
        first=db.scalar(select(LearningTask).where(LearningTask.session_id==sid));tid=first.id
    context=ctx.model_copy(update={'task_id':tid})
    before=business_rows(session_factory)
    talk(session_factory,sid,AssistantRequest(question='今天只有60分钟了，帮我压缩一下，优先补最薄弱的地方。',study_context=context),NoModel())
    view=get_task(session_factory,tid)
    assert view.budget_minutes==60 and sum(a['minutes'] for a in view.draft['activities'])==60
    assert view.draft['objective_observations']==[]
    assert not view.metrics.get('commit')
    after=business_rows(session_factory)
    assert {k:v for k,v in before.items() if k!='learning_tasks'}=={k:v for k,v in after.items() if k!='learning_tasks'}
    body=ConfirmTask(draft_version=view.draft_version)
    done=confirm_task(session_factory,tid,body,now=NOW)
    assert done.metrics['commit']['kind']=='activity_schedule' and done.metrics['commit']['added_count']==0
    stable=business_rows(session_factory)
    assert confirm_task(session_factory,tid,body,now=NOW).metrics['commit']==done.metrics['commit']
    assert business_rows(session_factory)==stable
    assert after['practice_items']==stable['practice_items'] and after['daily_plans']==stable['daily_plans']
    assert get_task(session_factory,tid).draft==done.draft

def test_activity_preview_cannot_be_confirmed_on_another_day(session_factory):
    sid,ctx,_=setup(session_factory)
    talk(session_factory,sid,AssistantRequest(question='安排60分钟数学二复习',study_context=ctx),NoModel())
    with session_factory() as db: tid=db.scalar(select(LearningTask.id).where(LearningTask.session_id==sid))
    view=get_task(session_factory,tid);before=business_rows(session_factory)
    with pytest.raises(AppError):confirm_task(session_factory,tid,ConfirmTask(draft_version=view.draft_version),now=NOW+timedelta(days=1))
    assert business_rows(session_factory)==before

def test_schedule_withdrawal_and_invalid_source_do_not_commit(session_factory):
    from backend.services.learning_task_service import cancel_task
    sid,ctx,_=setup(session_factory)
    talk(session_factory,sid,AssistantRequest(question='安排60分钟数学二复习',study_context=ctx),NoModel())
    with session_factory() as db: tid=db.scalar(select(LearningTask.id).where(LearningTask.session_id==sid))
    view=get_task(session_factory,tid)
    with session_factory.begin() as db:
        db.get(KnowledgePoint,ctx.knowledge_node_ids[0]).is_active=False
    before=business_rows(session_factory)
    with pytest.raises(AppError):confirm_task(session_factory,tid,ConfirmTask(draft_version=view.draft_version),now=NOW)
    assert business_rows(session_factory)==before
    cancel_task(session_factory,tid)
    with pytest.raises(AppError):confirm_task(session_factory,tid,ConfirmTask(draft_version=view.draft_version),now=NOW)
    assert not get_task(session_factory,tid).metrics.get('commit')

def test_no_budget_cannot_inherit_a_legacy_default(session_factory):
    from backend.services.learning_task_service import create_task
    from backend.schemas.learning_task import CreateTask
    sid,ctx,_=setup(session_factory)
    old=create_task(session_factory,CreateTask(goal='旧任务',budget_minutes=90,session_id=sid,current_plan_id=ctx.daily_plan_id),now=NOW)
    before=business_rows(session_factory)
    talk(session_factory,sid,AssistantRequest(question='帮我安排今天的数学二复习',study_context=ctx.model_copy(update={'task_id':old.task_id})),NoModel())
    assert '实际可用多少分钟' in reply(session_factory,sid).content
    assert business_rows(session_factory)==before

def test_natural_self_correction_and_history_are_session_owned(session_factory):
    sid,ctx,_=setup(session_factory);before=business_rows(session_factory)
    talk(session_factory,sid,AssistantRequest(question='我感觉积分换元比较差',study_context=ctx),NoModel())
    with session_factory() as db: assert read_self_reports(db,sid)[0]['topic']=='积分换元'
    talk(session_factory,sid,AssistantRequest(question='我们刚才讨论的是什么？',study_context=ctx),NoModel())
    assert '积分换元' in reply(session_factory,sid).content
    from tests.integration.test_explore_student_repairs import setup_another_session
    other,otherctx,_=setup_another_session(session_factory,ctx)
    result=execute_read_only_data_query(session_factory,session_id=other,ctx=otherctx,message='我们刚才讨论的是什么？',query_type='conversation_topic',now=NOW)
    assert '积分换元' not in result['answer']
    assert business_rows(session_factory)==before

def test_composite_global_and_node_statistics_are_separate_real_subsets(session_factory):
    from tests.integration.test_explore_student_repairs import test_global_recent_statistics_include_multiple_nodes_and_classify_assistance
    test_global_recent_statistics_include_multiple_nodes_and_classify_assistance(session_factory)
    from backend.models.chat import ChatSession
    with session_factory() as db:
        sid=db.scalar(select(ChatSession.id));node=db.scalar(select(KnowledgePoint).where(KnowledgePoint.code=='math.calculus.limit.lhopital'))
    from backend.schemas.learning_assistant import StudyContext
    ctx=StudyContext(surface='study',knowledge_node_ids=[node.id])
    before=business_rows(session_factory)
    result=execute_read_only_data_query(session_factory,session_id=sid,ctx=ctx,
        message='请统计我最近的学习情况，先看全局，再单独看洛必达法则。分别告诉我独立答对、独立答错、看解析后答对的数量，并说明时间范围和数据来源。',query_type='learning_state',now=NOW)
    all_scope,node_scope=result['evidence']['scope_results']
    assert all_scope['attempt_summary']['independent_wrong']==3
    assert set(node_scope['attempt_ids'])<=set(all_scope['attempt_ids'])
    assert node_scope['scope_node_ids']==[str(node.id)]
    assert all_scope['time_window']==node_scope['time_window']
    assert len(all_scope['records'])==5 and '全局近期统计' in result['answer']
    result_full_library=execute_read_only_data_query(session_factory,session_id=sid,ctx=ctx,
        message='我全库的正确率，和洛必达这个知识点的正确率分别是多少？',
        query_type='learning_state',now=NOW)
    global_scope,node_scope=result_full_library['evidence']['scope_results']
    assert global_scope['scope_node_ids']==[]
    assert node_scope['scope_node_ids']==[str(node.id)]
    assert '全局近期统计' in result_full_library['answer'] and '指定知识点统计' in result_full_library['answer']
    assert '独立答对' in result_full_library['answer'] and '统计范围：' in result_full_library['answer']
    global_text, node_text = result_full_library['answer'].split('## 指定知识点统计')
    for text, scope in ((global_text, global_scope), (node_text, node_scope)):
        counts = scope['attempt_summary']
        graded = sum(counts[key] for key in ('independent_right', 'independent_wrong', 'assisted_right', 'assisted_wrong'))
        right = counts['independent_right'] + counts['assisted_right']
        independent = counts['independent_right'] + counts['independent_wrong']
        assert f'客观已判定正确率：{right}/{graded}' in text
        assert f'独立作答正确率：{counts["independent_right"]}/{independent}' in text
    assert business_rows(session_factory)==before

@pytest.mark.parametrize('available', [False,True])
def test_inventory_discloses_existing_node_not_eligible_or_no_online(session_factory,available):
    sid,ctx,_=setup(session_factory)
    with session_factory.begin() as db:
        for q in db.scalars(select(Question).where(Question.kp_id==ctx.knowledge_node_ids[0])):
            if available:q.options={}  # Online, but invalid choice data must remain ineligible.
            else:q.is_active=False
    before=business_rows(session_factory)
    result=execute_read_only_data_query(session_factory,session_id=sid,ctx=ctx,message='帮我找一道洛必达法则的题',query_type='find',now=NOW)
    assert result['evidence']['inventory_state']==('no_eligible_questions' if available else 'no_online_questions')
    assert '没有找到匹配的知识点' not in result['answer']
    assert business_rows(session_factory)==before


def test_add_recent_wrong_without_attempt_context_is_read_only_clarification(session_factory):
    from tests.integration.test_learning_assistant import setup,talk,reply
    from backend.schemas.learning_assistant import AssistantRequest,StudyContext
    sid,_,_=setup(session_factory)
    context=StudyContext(surface='study',conversation_id=sid)
    before=business_rows(session_factory)
    frames=talk(session_factory,sid,AssistantRequest(
        question='把刚才那道错题加入今天的学习。',study_context=context),NoModel())
    stored=reply(session_factory,sid)
    assert '无法从当前话题定位' in stored.content
    assert stored.metadata_['read_only_data_query']['query_type']=='recent_wrong_item'
    assert stored.metadata_['writes'] is False and stored.metadata_['model_called'] is False
    assert any(event=='done' and data.get('status')=='completed' for event,data in frames)
    after=business_rows(session_factory)
    for table in ('practice_items','daily_plans','question_attempts','learning_events','learning_tasks'):
        assert after[table]==before[table]


def test_recent_wrong_reference_pins_attempt_version_before_planner_preview(session_factory):
    from tests.integration.test_learning_assistant import setup,NOW
    from backend.schemas.learning_assistant import StudyContext
    from backend.services.answer_submission_service import submit_answer
    from backend.services.assistant_data_queries import resolve_question_reference
    from backend.services.assistant_router import route_message
    sid,ctx,correct=setup(session_factory)
    with session_factory.begin() as db:
        question=db.get(Question,ctx.question_id)
        wrong=next(key for key in question.options if key!=correct)
        receipt=submit_answer(db,item_id=ctx.practice_item_id,raw_answer=None,
            selected_option=wrong,idempotency_key='recent-wrong-reference',now=NOW)
        attempt_id=receipt.attempt_id
        version_id=receipt.question_version_id
    bound=ctx.model_copy(update={'attempt_id':attempt_id})
    question,source,status=resolve_question_reference(session_factory,session_id=sid,ctx=bound,
        message='把刚才那道错题加入今天的学习。')
    assert status=='resolved_recent_wrong_attempt'
    assert source['attempt_id']==str(attempt_id)
    assert source['question_id']==str(ctx.question_id)
    assert source['question_version_id']==str(version_id)
    assert question.version_id==version_id
    route=route_message('把刚才那道错题加入今天的学习。',bound)
    assert (route.capability,route.intent,route.reason)==('planner','plan','add_recent_wrong_item')


def test_integral_question_plan_scope_overrides_current_lhopital_page(session_factory):
    from uuid import uuid4
    from backend.services.learning_assistant_service import planner_handoff
    sid,ctx,_=setup(session_factory)
    ctx=ctx.model_copy(update={'conversation_id':sid})
    question='我今天只有60分钟，先帮我复习数学二积分，再安排几道练习题。'
    route=route_message(question,ctx)
    assert (route.capability,route.intent,route.reason)==('planner','plan','learning_task_request')

    # The shared learning-loop fixture intentionally seeds only the compact
    # syllabus. Without the exam-reference index, the requested integral
    # chapter is absent and the planner must fail closed rather than broaden
    # to the current L'Hôpital node or the whole subject.
    missing_index=planner_handoff(session_factory,ctx=ctx,user_id=uuid4(),message=question,route=route,now=NOW)
    assert missing_index.constraints['scope_origin']=='unresolved_explicit_topic'
    assert missing_index.target_knowledge_node_ids==[]

    # Add the repository's real, source-linked exam taxonomy in this isolated
    # test database so the positive branch checks the actual canonical node.
    from backend.services.exam_reference_service import sync_exam_reference_index
    with session_factory.begin() as db:
        sync_exam_reference_index(db)
    handoff=planner_handoff(session_factory,ctx=ctx,user_id=uuid4(),message=question,route=route,now=NOW)
    assert handoff.available_minutes==60 and handoff.constraints['time_explicit'] is True
    assert handoff.constraints['scope_origin']=='explicit_user_scope'
    with session_factory() as db:
        targets=list(db.scalars(select(KnowledgePoint).where(KnowledgePoint.id.in_(handoff.target_knowledge_node_ids))))
    codes={row.code for row in targets}
    assert any(code.startswith('math.calculus.exam.integral') for code in codes)
    assert str(ctx.knowledge_node_ids[0]) not in {str(row.id) for row in targets}


def test_same_session_find_another_excludes_previously_previewed_question(session_factory):
    sid,ctx,_=setup(session_factory)
    first_frames=talk(session_factory,sid,AssistantRequest(
        question='帮我找一道洛必达法则的题',study_context=ctx),NoModel())
    first=reply(session_factory,sid)
    first_refs=(first.metadata_ or {}).get('read_only_data_query',{}).get('preview_questions',[])
    assert first_refs,first.content
    first_id=first_refs[0]['question_id']
    assert any(event=='done' and data.get('status')=='completed' for event,data in first_frames)

    second_frames=talk(session_factory,sid,AssistantRequest(
        question='再来一道极限的题',study_context=ctx),NoModel())
    second=reply(session_factory,sid)
    second_refs=(second.metadata_ or {}).get('read_only_data_query',{}).get('preview_questions',[])
    assert first_id not in {ref['question_id'] for ref in second_refs}
    assert any(event=='done' and data.get('status')=='completed' for event,data in second_frames)
    assert second.metadata_['read_only_data_query']['writes'] is False
