"""Business evidence only, in a newly owned PostgreSQL test cluster."""
import pytest
from sqlalchemy import select
from tests.integration.test_student_uiv2_repairs import session_factory,clean_database,clean_tasks,conversations,setup,talk,reply,NOW,NoModel,business_rows
from backend.schemas.learning_assistant import AssistantRequest
from backend.models.learning_task import LearningTask
from tests.unit.test_r6_intent_contract import PLAN_INPUTS
from tests.integration.test_learning_assistant import setup_pre_generation

@pytest.mark.parametrize('text',PLAN_INPUTS)
def test_r6_plan_preview_produces_valid_timeboxed_draft_without_formal_writes(session_factory,text):
    sid,ctx,_=setup_pre_generation(session_factory);before=business_rows(session_factory)
    talk(session_factory,sid,AssistantRequest(question=text,study_context=ctx),NoModel())
    with session_factory() as db:
        task=db.scalar(select(LearningTask).where(LearningTask.session_id==sid))
        assert task.status=='ready' and task.draft,reply(session_factory,sid).content
        assert task.metrics['intent']=='plan'
        assert task.budget_minutes==60
        assert 0<sum(a['minutes'] for a in task.draft['activities'])<=60
        assert not task.metrics.get('commit')
    after=business_rows(session_factory)
    for table in before:
        if table!='learning_tasks':assert before[table]==after[table],table

def test_r6_60_minute_question_draft_can_be_trimmed_to_valid_22_minute_prefix(session_factory):
    """Replay the r6 3+4+15+5+15 schedule against exact saved versions."""
    from tests.integration.test_learning_assistant import setup as setup_assistant, NOW
    from tests.integration.test_learning_loop import mark_isolated_question_trusted
    from backend.models.learning import KnowledgePoint,Question,PracticeItem
    from backend.schemas.learning_task import CreateTask
    from backend.services.learning_task_service import create_task,run_task,get_task
    from backend.services.question_versions import question_version_reference
    # Preserve yesterday's paper as history; today's paper is not generated.
    sid,ctx,_=setup_pre_generation(session_factory)
    minutes=[3,4,15,5,15]
    refs=[]
    with session_factory.begin() as db:
        source=db.get(Question,ctx.question_id)
        node=db.get(KnowledgePoint,source.kp_id)
        for index,estimate in enumerate(minutes,1):
            q=Question(kp_id=node.id,question_type='single_choice',grading_mode=source.grading_mode,
                grading_config=dict(source.grading_config or {}),stem=f'SYNTHETIC r6 budget item {index}',
                options={'A':'1','B':'0'},correct_answer='A',explanation='SYNTHETIC fixture explanation',
                estimated_minutes=estimate,difficulty='basic',question_role='basic',skill_tags=['r6-budget'])
            mark_isolated_question_trusted(q,db=db)
            refs.append({'question_id':str(q.id),'question_version':question_version_reference(q)})
        assert all(ref['question_version'] for ref in refs)
    scope=[str(ctx.knowledge_node_ids[0])]
    previous_handoff={'target_knowledge_node_ids':scope,'available_minutes':60,
        'constraints':{'scope_version':1,'scope_explicit':True,'resolved_scope_node_ids':scope}}
    current_handoff={'target_knowledge_node_ids':scope,'available_minutes':25,
        'constraints':{'draft_refinement':True,'relax_count':True,'scope_version':1,
            'scope_explicit':True,'resolved_scope_node_ids':scope}}
    request='我临时只有25分钟了。保留最重要的复习内容，减少练习量，其他内容以后再学。先给我修改后的版本，不要马上创建新计划。'
    task=create_task(session_factory,CreateTask(goal=request,budget_minutes=25,session_id=sid,
        current_plan_id=ctx.daily_plan_id),now=NOW)
    with session_factory.begin() as db:
        row=db.get(LearningTask,task.task_id)
        row.context={**row.context,'planner_handoff':current_handoff,'previous_planner_handoff':previous_handoff,
            'previous_goal':'安排60分钟数学二复习','previous_draft':{'questions':refs,'review_nodes':[],'review_minutes':0}}
    before=business_rows(session_factory)
    result=run_task(session_factory,task.task_id,NoModel(),now=NOW)
    assert result.status=='ready',result.message
    assert result.draft and result.draft['total_minutes']==22
    assert [q['question_id'] for q in result.draft['questions']]==[r['question_id'] for r in refs[:3]]
    assert [(q['question_id'],q['question_version']) for q in result.draft['questions']]==[
        (r['question_id'],r['question_version']) for r in refs[:3]]
    assert result.draft['total_minutes']<=25 and not result.metrics.get('commit')
    assert '22 分钟' in result.message and '确认前不会' in result.message
    after=business_rows(session_factory)
    for table in before:
        if table!='learning_tasks':assert before[table]==after[table],table

def test_r6_inventory_reports_all_eligible_questions_already_in_today_paper(session_factory):
    from tests.integration.test_learning_assistant import setup as setup_assistant, NOW
    from backend.models.learning import Question,PracticeItem,DailyPlan,KnowledgePoint
    from backend.services.question_eligibility import question_eligibility
    from backend.services.answer_submission_service import submit_answer
    from backend.services.assistant_data_queries import execute_read_only_data_query
    from sqlalchemy import func
    sid,ctx,correct=setup_assistant(session_factory)
    with session_factory.begin() as db:
        plan=db.get(DailyPlan,ctx.daily_plan_id)
        node=db.get(KnowledgePoint,ctx.knowledge_node_ids[0])
        eligible=[q for q in db.query(Question).filter(Question.kp_id==node.id,Question.is_active.is_(True)).all()
            if question_eligibility(q,node).practice_eligible]
        present=set(db.scalars(select(PracticeItem.question_id).where(PracticeItem.plan_id==plan.id)))
        next_ordinal=(db.scalar(select(func.max(PracticeItem.ordinal)).where(PracticeItem.plan_id==plan.id)) or 0)+1
        for q in eligible:
            if q.id not in present:
                db.add(PracticeItem(plan_id=plan.id,question_id=q.id,kp_id=q.kp_id,
                    ordinal=next_ordinal))
                next_ordinal+=1
                present.add(q.id)
        submit_answer(db,item_id=ctx.practice_item_id,raw_answer=None,selected_option=correct,
            idempotency_key='r6-all-in-paper-once',now=NOW)
    before=business_rows(session_factory)
    result=execute_read_only_data_query(session_factory,session_id=sid,ctx=ctx,
        message='就按洛必达法则这个知识点，看看还有没有能练的题。',query_type='inventory',now=NOW)
    evidence=result['evidence']
    assert evidence['inventory_state']=='all_eligible_questions_in_today_plan'
    assert evidence['question_count']>=1
    assert evidence['available_to_append_count']==0
    assert evidence['already_in_plan_count']==evidence['question_count']
    assert evidence['previously_attempted_count']>=1
    assert not evidence.get('preview_questions')
    assert '可新增 0 道' in result['answer'] and '都已在今日卷中' in result['answer']
    assert '尚未加入今日卷' not in result['answer']
    assert business_rows(session_factory)==before

def test_r6_selecting_most_recent_preview_does_not_create_task_when_already_in_today_paper(session_factory):
    from tests.integration.test_learning_assistant import setup as setup_assistant, NOW
    from backend.models.chat import ChatMessage
    from backend.models.learning import Question
    from backend.services.question_versions import question_version_reference
    sid,ctx,_=setup_assistant(session_factory)
    with session_factory.begin() as db:
        question=db.get(Question,ctx.question_id)
        ref={'question_id':str(question.id),'question_version':question_version_reference(question),
            'kp_id':str(question.kp_id),'question_type':question.question_type}
        db.add(ChatMessage(session_id=sid,role='assistant',status='completed',content='刚才预览了一道题',
            metadata_={'answer_source':'read_only_data_query','read_only_data_query':{
                'preview_questions':[ref],'preview_generated_at':NOW.isoformat(),
                'query_state':{'scope_node_ids':[str(question.kp_id)]}}}))
    before=business_rows(session_factory)
    frames=talk(session_factory,sid,AssistantRequest(question='把刚才那道题加入今天的学习。',study_context=ctx),NoModel())
    saved=reply(session_factory,sid)
    assert '已经在当前今日卷第 1 题' in saved.content
    assert '该范围暂未取得可用的系统节点讲解' not in saved.content
    assert saved.metadata_['selection_state']['state']=='already_in_today_plan'
    assert saved.metadata_['model_called'] is False and saved.metadata_['writes'] is False
    done=[data for event,data in frames if event=='done']
    assert len(done)==1 and done[0]['status']=='completed'
    with session_factory() as db:
        assert db.query(LearningTask).filter(LearningTask.session_id==sid).count()==0
    assert business_rows(session_factory)==before


def test_already_added_preview_number_uses_bound_type_order_not_ordinal(session_factory):
    from tests.integration.test_learning_assistant import setup as setup_assistant, NOW
    from tests.integration.test_learning_loop import mark_isolated_question_trusted
    from backend.models.learning import PracticeItem, Question
    from backend.services.question_versions import question_version_reference
    from backend.services.practice_preview_reference import preview_question_state
    from uuid import UUID
    _,ctx,_=setup_assistant(session_factory)
    with session_factory.begin() as db:
        target=db.get(PracticeItem,ctx.practice_item_id)
        target.ordinal=2
        source=db.get(Question,target.question_id)
        calculation=Question(kp_id=source.kp_id,question_type='calculation',grading_mode=source.grading_mode,
            grading_config={'method':'numeric_final','verified':True},stem='SYNTHETIC mixed-order calculation',
            correct_answer='0',explanation='SYNTHETIC: final answer is zero.',estimated_minutes=5,
            difficulty='basic',question_role='basic',skill_tags=['mixed-order'])
        mark_isolated_question_trusted(calculation,db=db)
        db.add(PracticeItem(plan_id=ctx.daily_plan_id,question_id=calculation.id,kp_id=calculation.kp_id,
            question_version_id=UUID(question_version_reference(calculation)),ordinal=1))
        reference={'question_id':str(source.id),'question_version':question_version_reference(source)}
    before=business_rows(session_factory)
    result=preview_question_state(session_factory,reference,ctx,NOW)
    assert result['ordinal']==2 and result['display_number']==1
    assert '第 1 题' in result['message']
    assert result['question_version_id']==reference['question_version']
    assert business_rows(session_factory)==before

def test_r6_unknown_topic_is_needs_info_and_never_broadened(session_factory):
    sid,ctx,_=setup(session_factory);before=business_rows(session_factory)
    talk(session_factory,sid,AssistantRequest(question='给我一份60分钟的定积分应用复习计划，先不要创建',study_context=ctx),NoModel())
    with session_factory() as db:
        task=db.scalar(select(LearningTask).where(LearningTask.session_id==sid))
        assert task.status=='needs_info' and task.draft is None
        assert task.error_code=='planning_scope_unresolved'
        assert task.context['planner_handoff']['target_knowledge_node_ids']==[]
    assert '定积分应用' in reply(session_factory,sid).content
    after=business_rows(session_factory)
    for table in before:
        if table!='learning_tasks':assert before[table]==after[table],table

def test_r6_statistics_never_create_a_task(session_factory):
    sid,ctx,_=setup(session_factory);before=business_rows(session_factory)
    talk(session_factory,sid,AssistantRequest(question='我独立答对了几道',study_context=ctx),NoModel())
    assert reply(session_factory,sid).metadata_['read_only_data_query']['query_type']=='learning_state'
    assert business_rows(session_factory)==before

@pytest.mark.parametrize('with_prior',[False,True])
def test_r6_deictic_lesson_requires_reliable_same_session_antecedent(session_factory,with_prior):
    from backend.schemas.learning_assistant import StudyContext
    from tests.integration.test_learning_assistant import QAProvider
    sid,_,_=setup(session_factory);ctx=StudyContext(surface='study')
    provider=QAProvider('UNRELATED_POWER_SERIES_TEMPLATE')
    if with_prior:
        talk(session_factory,sid,AssistantRequest(question='先讲解洛必达法则，不要创建计划',study_context=ctx),provider)
        first=reply(session_factory,sid)
        assert first.metadata_['answer_source']=='system_lesson'
        assert '洛必达' in first.content
    before=business_rows(session_factory)
    talk(session_factory,sid,AssistantRequest(question='先讲解这个知识点，不要创建计划',study_context=ctx),provider)
    saved=reply(session_factory,sid)
    assert not provider.prompts
    assert 'UNRELATED_POWER_SERIES_TEMPLATE' not in saved.content
    if with_prior:assert saved.metadata_['answer_source']=='system_lesson' and '洛必达' in saved.content
    else:assert saved.metadata_['scope_resolution_status']=='needs_antecedent' and '知识点' in saved.content
    assert business_rows(session_factory)==before


def test_r6_mixed_paper_statistics_and_recheck_keep_scope_separate_from_math_advice(session_factory):
    from backend.models.learning import Question,KnowledgePoint,PracticeItem,DailyPlan
    from backend.services.answer_submission_service import submit_answer,record_answer_reveal
    from datetime import timedelta
    sid,ctx,correct=setup(session_factory)
    with session_factory.begin() as db:
        math=db.get(Question,ctx.question_id)
        othermath=db.scalar(select(Question).join(KnowledgePoint).where(KnowledgePoint.subject=='考研数学',Question.question_type=='single_choice',Question.id!=math.id))
        cs=db.scalar(select(Question).join(KnowledgePoint).where(KnowledgePoint.subject!='考研数学',Question.question_type=='single_choice'))
        if cs is None:
            from tests.integration.test_learning_loop import mark_isolated_question_trusted
            node=db.scalar(select(KnowledgePoint).where(KnowledgePoint.subject!='考研数学',KnowledgePoint.is_assessable.is_(True)))
            if node is None:
                node=KnowledgePoint(code='synthetic.r6.cs',name='SYNTHETIC 408统计样本',subject='408',is_assessable=True)
                db.add(node);db.flush()
            cs=Question(kp_id=node.id,question_type='single_choice',stem='SYNTHETIC 408: choose one',
                options={'A':'1','B':'0'},correct_answer='A',explanation='SYNTHETIC fixture value 1',
                estimated_minutes=3,difficulty='basic',grading_config={'verified':True,'method':'single_choice'})
            mark_isolated_question_trusted(cs,db=db);db.flush()
        assert othermath and cs
        expected=[]
        for i,q in enumerate([math,othermath,cs]):
            item=db.get(PracticeItem,ctx.practice_item_id) if i==0 else PracticeItem(plan_id=ctx.daily_plan_id,question_id=q.id,kp_id=q.kp_id,ordinal=i+1)
            if i:db.add(item);db.flush()
            if i==1:record_answer_reveal(db,item_id=item.id,now=NOW)
            option=next(k for k in q.options if k!=q.correct_answer) if i==0 else q.correct_answer
            submit_answer(db,item_id=item.id,raw_answer=None,selected_option=option,idempotency_key=f'r6-mixed-{i}',now=NOW)
            expected.append(str(item.id))
        # A genuine but different paper must not leak into the current-paper statistics.
        older=DailyPlan(study_date='2025-12-31',status='active');db.add(older);db.flush()
        item=PracticeItem(plan_id=older.id,question_id=math.id,kp_id=math.kp_id,ordinal=1);db.add(item);db.flush()
        submit_answer(db,item_id=item.id,raw_answer=None,selected_option=math.correct_answer,idempotency_key='r6-other-paper',now=NOW-timedelta(days=1))
    before=business_rows(session_factory)
    message='根据我刚才的实际做题情况，告诉我独立答对了几道、看解析后答对了几道。并给我接下来90分钟的数学二复习建议。'
    talk(session_factory,sid,AssistantRequest(question=message,study_context=ctx),NoModel())
    first=reply(session_factory,sid).metadata_['read_only_data_query']
    assert first['attempt_count']==3
    assert first['attempt_summary']['independent_right']==1 and first['attempt_summary']['independent_wrong']==1 and first['attempt_summary']['assisted_right']==1
    from backend.models.learning import QuestionAttempt
    from uuid import UUID
    with session_factory() as db:
        expected_attempts=set(str(k) for k in db.scalars(select(QuestionAttempt.id).where(QuestionAttempt.practice_item_id.in_([UUID(k) for k in expected]))))
    assert set(first['attempt_ids'])==expected_attempts
    assert first['query_state']['scope_kind']=='today_paper'
    assert first['query_state']['daily_plan_id']==str(ctx.daily_plan_id)
    assert first['study_advice']['total_minutes']==90
    assert all(r['knowledge_node_id']!=str(cs.kp_id) for r in first['study_advice']['objective_observations'])
    assert {r['attempt_id'] for r in first['study_advice']['objective_observations']}<expected_attempts
    talk(session_factory,sid,AssistantRequest(question='你说我独立答对的次数不对，请重新核对记录。',study_context=ctx),NoModel())
    second=reply(session_factory,sid).metadata_['read_only_data_query']
    assert second['attempt_ids']==first['attempt_ids']
    assert second['attempt_summary']==first['attempt_summary']
    assert second['query_state']==first['query_state']
    assert business_rows(session_factory)==before

@pytest.mark.parametrize('scope',['global','single','multiple'])
def test_r6_all_in_paper_explanation_uses_the_actual_query_scope(session_factory,scope):
    from backend.models.learning import Question,PracticeItem,KnowledgePoint
    from backend.schemas.learning_assistant import StudyContext
    from backend.services.assistant_data_queries import execute_read_only_data_query
    sid,ctx,_=setup(session_factory)
    with session_factory.begin() as db:
        questions=list(db.scalars(select(Question)))
        for i,q in enumerate(questions,2):
            if q.id!=ctx.question_id:
                db.add(PracticeItem(plan_id=ctx.daily_plan_id,question_id=q.id,kp_id=q.kp_id,ordinal=i))
        node_ids=list(dict.fromkeys(q.kp_id for q in questions))
    if scope=='global':ctx=StudyContext(surface='study',daily_plan_id=ctx.daily_plan_id)
    elif scope=='multiple':ctx=ctx.model_copy(update={'knowledge_node_ids':node_ids})
    before=business_rows(session_factory)
    result=execute_read_only_data_query(session_factory,session_id=sid,ctx=ctx,message='帮我找一道题看看',query_type='find',now=NOW)
    assert result['evidence']['inventory_state']=='all_eligible_questions_in_today_plan'
    assert result['evidence']['available_to_append_count']==0
    assert not result['evidence'].get('preview_questions')
    assert '这个知识点' not in result['answer']
    if scope=='global':assert '当前题库查询范围' in result['answer'] and result['evidence']['scope_node_ids']==[]
    else:
        for name in result['evidence']['scope_node_names']:assert name in result['answer']
    assert business_rows(session_factory)==before


def test_r6_unscoped_empty_paper_previews_real_versions_without_claiming_already_added(session_factory):
    from backend.models.learning import PracticeItem,QuestionVersion
    from backend.schemas.learning_assistant import StudyContext
    from backend.services.assistant_data_queries import execute_read_only_data_query
    from uuid import UUID
    # Inspect the bank in QA while today's paper is uncreated. Homepage
    # planning remains blindbox; yesterday's item stays in permanent history.
    sid,ctx,_=setup_pre_generation(session_factory,purpose='qa')
    ctx=StudyContext(surface='chat')
    before=business_rows(session_factory)
    result=execute_read_only_data_query(session_factory,session_id=sid,ctx=ctx,message='帮我找两道题预览，不要加入今日卷。',query_type='find',now=NOW)
    assert result['evidence']['inventory_state']=='eligible_questions_available'
    previews=result['evidence']['preview_questions'];assert previews
    assert '都已在今日卷' not in result['answer'] and '尚未加入今日卷' in result['answer']
    with session_factory() as db:
        for q in previews:
            version=db.get(QuestionVersion,UUID(q['question_version']))
            assert str(version.question_id)==q['question_id']
    assert business_rows(session_factory)==before


def test_r6_recheck_reads_new_persisted_attempts_in_the_original_scope(session_factory):
    from backend.services.answer_submission_service import submit_answer
    sid,ctx,correct=setup(session_factory)
    talk(session_factory,sid,AssistantRequest(question='根据我刚才的实际做题情况，告诉我独立答对几道、独立答错几道',study_context=ctx),NoModel())
    first=reply(session_factory,sid).metadata_['read_only_data_query']
    assert first['attempt_count']==0
    with session_factory.begin() as db:
        submit_answer(db,item_id=ctx.practice_item_id,raw_answer=None,selected_option=correct,idempotency_key='r6-new-recheck',now=NOW)
    before=business_rows(session_factory)
    talk(session_factory,sid,AssistantRequest(question='请重新核对记录',study_context=ctx),NoModel())
    second=reply(session_factory,sid).metadata_['read_only_data_query']
    assert second['query_state']==first['query_state']
    assert second['attempt_count']==1 and second['attempt_summary']['independent_right']==1
    assert second['attempt_ids'] and second['antecedent_message_id']
    assert business_rows(session_factory)==before
