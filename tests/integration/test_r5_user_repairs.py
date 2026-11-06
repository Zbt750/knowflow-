"""Fresh disposable PostgreSQL only. No browser, paid model or fabricated attempts."""
import pytest
from uuid import uuid4
from sqlalchemy import select
from tests.integration.test_student_uiv2_repairs import session_factory,clean_database,clean_tasks,conversations,setup,talk,reply,NOW,NoModel,business_rows
from backend.schemas.learning_assistant import AssistantRequest
from backend.schemas.learning_task import ConfirmTask
from backend.models.learning_task import LearningTask
from backend.models.learning import KnowledgePoint
from backend.services.learning_task_service import get_task,confirm_task
from backend.services.learning_assistant_service import planner_handoff
from backend.services.assistant_router import route_message
from backend.services.assistant_data_queries import execute_read_only_data_query
from backend.errors import AppError
from tests.integration.test_learning_assistant import setup_pre_generation

def assert_only_expected_preview_revision(before,after,task_id,minutes):
    """A preview must change; validate that row and every other table explicitly."""
    import ast
    assert set(before)==set(after)
    for table in before:
        if table!='learning_tasks':
            assert before[table]==after[table],table
            continue
        old={r['id']:r for value in before[table] for r in [ast.literal_eval(value)]}
        new={r['id']:r for value in after[table] for r in [ast.literal_eval(value)]}
        assert old.keys()==new.keys()
        for key,row in old.items():
            updated=new[key]
            if key!=str(task_id):
                assert row==updated
                continue
            assert {k:row[k] for k in ('id','session_id','created_at')}=={k:updated[k] for k in ('id','session_id','created_at')}
            assert updated['budget_minutes']==minutes and updated['status']=='ready'
            # Terminal tasks retain the completed run's correlation token for
            # audit. A new revision must have its own valid run identity.
            from uuid import UUID
            assert UUID(updated['run_token']) and updated['run_token']!=row['run_token']
            assert updated['error_code'] is None
            assert not updated['metrics'].get('commit')
            assert updated['context']['current_plan_signature']==row['context']['current_plan_signature']
            assert updated['context']['previous_draft']==row['draft']
            h=updated['context']['planner_handoff']
            assert h['available_minutes']==minutes and h['source_conversation_id']==row['session_id']
            assert h['constraints']['resolved_scope_node_ids']==row['context']['planner_handoff']['constraints']['resolved_scope_node_ids']
            assert updated['draft']['total_minutes']<=minutes
            if row['draft'].get('kind')=='activity_schedule':
                assert sum(a['minutes'] for a in updated['draft']['activities'])==minutes
            else:
                assert {(q['question_id'],q['question_version']) for q in updated['draft']['questions']} <= {(q['question_id'],q['question_version']) for q in row['draft']['questions']}

def test_r5_mixed_known_unknown_topic_never_silently_becomes_whole_subject(session_factory):
    sid,ctx,_=setup_pre_generation(session_factory)
    text='我准备考数学二，最近积分和极限学得不太扎实。今天只有 60 分钟，希望你先帮我判断应该复习什么，再安排一些练习题。先给我看看安排，不要直接加入今日卷。'
    before=business_rows(session_factory)
    h=planner_handoff(session_factory,ctx=ctx,user_id=uuid4(),message=text,route=route_message(text,ctx),now=NOW)
    assert '积分' in h.constraints['unresolved_topics']
    assert h.target_knowledge_node_ids==[]
    talk(session_factory,sid,AssistantRequest(question=text,study_context=ctx),NoModel())
    assert '积分' in reply(session_factory,sid).content
    with session_factory() as db:
        task=db.scalar(select(LearningTask).where(LearningTask.session_id==sid))
        assert task.draft is None and task.status=='needs_info'
    after=business_rows(session_factory)
    assert {k:v for k,v in before.items() if k!='learning_tasks'}=={k:v for k,v in after.items() if k!='learning_tasks'}

@pytest.mark.parametrize('minutes',[25,60,15])
def test_r5_refinement_recovers_same_session_task_and_invalidates_old_confirmation(session_factory,minutes):
    sid,ctx,_=setup(session_factory)
    talk(session_factory,sid,AssistantRequest(question='安排90分钟数学二整体复习',study_context=ctx),NoModel())
    with session_factory() as db:tid=db.scalar(select(LearningTask.id).where(LearningTask.session_id==sid))
    old=get_task(session_factory,tid);before=business_rows(session_factory)
    text=f'我临时只有 {minutes} 分钟了。保留最重要的复习内容，减少练习量，其他内容以后再学。先给我修改后的版本，不要马上创建新计划。'
    talk(session_factory,sid,AssistantRequest(question=text,study_context=ctx),NoModel())
    current=get_task(session_factory,tid)
    latest=reply(session_factory,sid)
    assert current.budget_minutes==minutes and current.draft, f'latest={latest.content!r}; metadata={latest.metadata_!r}'
    assert sum(a['minutes'] for a in current.draft['activities'])==minutes
    assert current.draft_version!=old.draft_version
    revision=business_rows(session_factory)
    assert_only_expected_preview_revision(before,revision,tid,minutes)
    with pytest.raises(AppError):confirm_task(session_factory,tid,ConfirmTask(draft_version=old.draft_version),now=NOW)
    after=business_rows(session_factory)
    assert revision==after
    assert any(event=='planner' and data['task_id']==str(tid) for event,data in talk(session_factory,sid,AssistantRequest(question=text,study_context=ctx),NoModel()))
    assert not get_task(session_factory,tid).metrics.get('commit')

@pytest.mark.parametrize('text,target',[
    ('我说的是定积分应用，不是洛必达法则。请只保留这个范围。',None),
    ('我说的不是洛必达，是等价无穷小，请纠正。','math.calculus.limit.infinitesimal'),
])
def test_r5_scope_correction_is_readonly_and_resolves_only_positive_target(session_factory,text,target):
    sid,ctx,_=setup(session_factory);before=business_rows(session_factory)
    talk(session_factory,sid,AssistantRequest(question=text,study_context=ctx),NoModel())
    saved=reply(session_factory,sid);e=saved.metadata_['read_only_data_query']
    assert saved.metadata_['model_called'] is False
    if target:
        with session_factory() as db:expected=db.scalar(select(KnowledgePoint.id).where(KnowledgePoint.code==target))
        assert e['scope_node_ids']==[str(expected)]
    else:
        assert e['query_status']=='needs_clarification' and not e['scope_node_ids']
        assert '定积分应用' in saved.content
    assert business_rows(session_factory)==before

def test_r5_unknown_integral_preview_does_not_claim_an_empty_paper_is_full(session_factory):
    sid,ctx,_=setup(session_factory)
    result=execute_read_only_data_query(session_factory,session_id=sid,ctx=ctx,message='今天只复习数学二的定积分应用。先给我讲清楚核心思路，再从已有题库找两道适合练习的题，先展示给我，不要生成新题，不要加入今日卷，也不要创建计划。',query_type='find',now=NOW)
    assert result['evidence']['query_status']=='needs_clarification'
    assert '定积分应用' in result['answer'] and '已入今日卷' not in result['answer']

def test_r5_statistics_append_a_validated_readonly_schedule(session_factory):
    sid,ctx,_=setup(session_factory);before=business_rows(session_factory)
    text='根据我刚才的实际做题情况，告诉我独立答对了几道、独立答错了几道、看解析后答对了几道。请解释你根据哪些记录得出结论，并给我接下来 90 分钟的数学二复习建议。'
    talk(session_factory,sid,AssistantRequest(question=text,study_context=ctx),NoModel())
    saved=reply(session_factory,sid);e=saved.metadata_['read_only_data_query']
    advice=e['study_advice']
    assert sum(a['minutes'] for a in advice['activities'])==90
    assert advice['objective_observations']==[] and e['attempt_count']==0
    assert '没有客观作答记录' in saved.content and '90' in saved.content
    assert business_rows(session_factory)==before

def test_r5_question_preview_is_reduced_and_revalidated_without_losing_versions(session_factory):
    from tests.integration.test_learning_loop import mark_isolated_question_trusted
    from backend.models.learning import Question
    sid,ctx,_=setup_pre_generation(session_factory)
    # The small seed has only two appendable questions here. Prepare enough
    # explicitly synthetic inventory for the existing three-question assertion.
    with session_factory.begin() as db:
        for index in range(2):
            q=Question(kp_id=ctx.knowledge_node_ids[0],question_type='single_choice',
                stem=f'SYNTHETIC r5 revision candidate {index}: choose the stated value',
                options={'A':'1','B':'0'},correct_answer='A',explanation='SYNTHETIC fixture value is 1',
                estimated_minutes=20,difficulty='basic',grading_config={'verified':True,'method':'single_choice'})
            mark_isolated_question_trusted(q,db=db)
    talk(session_factory,sid,AssistantRequest(question='先解释洛必达法则，再从题库挑三道题准备60分钟的练习方案，先预览。',study_context=ctx),NoModel())
    with session_factory() as db:tid=db.scalar(select(LearningTask.id).where(LearningTask.session_id==sid))
    original=get_task(session_factory,tid)
    assert original.draft and len(original.draft['questions'])==3,original.message
    before=business_rows(session_factory)
    talk(session_factory,sid,AssistantRequest(question='我只有 15 分钟，请把原计划缩短，不要重新创建一份。',study_context=ctx),NoModel())
    current=get_task(session_factory,tid)
    assert current.draft and 0<current.draft['total_minutes']<=15,current.message
    assert {(q['question_id'],q['question_version']) for q in current.draft['questions']} <= {(q['question_id'],q['question_version']) for q in original.draft['questions']}
    assert current.draft_version!=original.draft_version
    assert_only_expected_preview_revision(before,business_rows(session_factory),tid,15)
    with pytest.raises(AppError):confirm_task(session_factory,tid,ConfirmTask(draft_version=original.draft_version),now=NOW)

def test_r5_exact_preview_reference_is_used_in_study_not_generic_planner(session_factory):
    sid,ctx,_=setup(session_factory)
    talk(session_factory,sid,AssistantRequest(question='帮我找一道洛必达法则的题',study_context=ctx),NoModel())
    preview=reply(session_factory,sid).metadata_['read_only_data_query']['preview_questions'][0]
    before=business_rows(session_factory)
    talk(session_factory,sid,AssistantRequest(question='把刚才那道题加入今天的学习。',study_context=ctx),NoModel())
    with session_factory() as db:task=db.scalar(select(LearningTask).where(LearningTask.session_id==sid))
    assert task and task.status=='ready' and task.draft,reply(session_factory,sid).content
    assert task.context['paper_adjustment'] is True and task.draft['kind']=='paper_adjustment'
    assert task.draft['plan_id']==str(ctx.daily_plan_id) and task.draft['remove_item_ids']==[]
    assert [(q['question_id'],q['question_version_id']) for q in task.draft['replacements']]==[(preview['question_id'],preview['question_version'])]
    after=business_rows(session_factory)
    assert {k:v for k,v in before.items() if k!='learning_tasks'}=={k:v for k,v in after.items() if k!='learning_tasks'}

def test_r5_missing_preview_reference_does_not_create_a_generic_plan(session_factory):
    sid,ctx,_=setup(session_factory);before=business_rows(session_factory)
    talk(session_factory,sid,AssistantRequest(question='把刚才那道题加入今天的学习。',study_context=ctx),NoModel())
    assert '预览' in reply(session_factory,sid).content
    assert business_rows(session_factory)==before

def test_r5_actual_three_attempt_classes_drive_advice_without_writing_learning_data(session_factory):
    from backend.models.learning import Question,PracticeItem
    from backend.services.answer_submission_service import submit_answer,record_answer_reveal
    sid,ctx,correct=setup(session_factory)
    with session_factory.begin() as db:
        questions=list(db.scalars(select(Question).join(KnowledgePoint).where(KnowledgePoint.subject=='考研数学',Question.question_type=='single_choice').order_by(Question.id)))
        assert len(questions)>=3
        receipts=[]
        for index,q in enumerate(questions[:3]):
            if q.id==ctx.question_id:
                item=db.get(PracticeItem,ctx.practice_item_id)
            else:
                item=PracticeItem(plan_id=ctx.daily_plan_id,kp_id=q.kp_id,question_id=q.id,ordinal=2+index);db.add(item);db.flush()
            if index==2:record_answer_reveal(db,item_id=item.id,now=NOW)
            option=next(k for k in q.options if k!=q.correct_answer) if index==1 else q.correct_answer
            receipts.append(submit_answer(db,item_id=item.id,raw_answer=None,selected_option=option,idempotency_key=f'r5-three-{index}',now=NOW))
    before=business_rows(session_factory)
    text='告诉我独立答对了几道、独立答错了几道、看解析后答对了几道，并给我接下来90分钟的数学二复习建议。'
    talk(session_factory,sid,AssistantRequest(question=text,study_context=ctx),NoModel())
    evidence=reply(session_factory,sid).metadata_['read_only_data_query']
    assert evidence['attempt_summary']=={'independent_right':1,'independent_wrong':1,'assisted_right':1,'assisted_wrong':0,'unknown':0}
    assert set(evidence['attempt_ids'])=={str(r.attempt_id) for r in receipts}
    assert {r['attempt_id'] for r in evidence['study_advice']['objective_observations']}==set(evidence['attempt_ids'])
    assert sum(a['minutes'] for a in evidence['study_advice']['activities'])==90
    assert business_rows(session_factory)==before

def test_r5_scope_correction_withdraws_the_previous_draft_and_survives_next_query(session_factory):
    sid,ctx,_=setup(session_factory)
    talk(session_factory,sid,AssistantRequest(question='安排60分钟数学二整体复习',study_context=ctx),NoModel())
    with session_factory() as db:tid=db.scalar(select(LearningTask.id).where(LearningTask.session_id==sid))
    old=get_task(session_factory,tid)
    talk(session_factory,sid,AssistantRequest(question='我说的不是洛必达，是等价无穷小，请纠正。',study_context=ctx),NoModel())
    assert get_task(session_factory,tid).status=='cancelled'
    with pytest.raises(AppError):confirm_task(session_factory,tid,ConfirmTask(draft_version=old.draft_version),now=NOW)
    talk(session_factory,sid,AssistantRequest(question='帮我找一道这个知识点的题',study_context=ctx),NoModel())
    with session_factory() as db:expected=db.scalar(select(KnowledgePoint.id).where(KnowledgePoint.code=='math.calculus.limit.infinitesimal'))
    result=reply(session_factory,sid).metadata_['read_only_data_query']
    assert result['scope_node_ids']==[str(expected)]

def test_r5_cancelled_preview_is_not_revived_by_budget_change(session_factory):
    from backend.services.learning_task_service import cancel_task
    sid,ctx,_=setup(session_factory)
    talk(session_factory,sid,AssistantRequest(question='安排60分钟数学二整体复习',study_context=ctx),NoModel())
    with session_factory() as db:tid=db.scalar(select(LearningTask.id).where(LearningTask.session_id==sid))
    cancel_task(session_factory,tid);before=business_rows(session_factory)
    talk(session_factory,sid,AssistantRequest(question='我只有15分钟，请把原计划缩短，不要重新创建一份。',study_context=ctx.model_copy(update={'task_id':tid})),NoModel())
    assert '没有可修改' in reply(session_factory,sid).content
    assert business_rows(session_factory)==before

def test_r5_concept_explanation_with_no_plan_does_not_borrow_current_question(session_factory):
    sid,ctx,_=setup(session_factory);before=business_rows(session_factory)
    talk(session_factory,sid,AssistantRequest(question='先讲解这个知识点，但不要创建计划。',study_context=ctx),NoModel())
    saved=reply(session_factory,sid)
    assert saved.metadata_['answer_source']=='system_lesson'
    assert '洛必达法则' in saved.content and '固定' not in saved.content
    assert business_rows(session_factory)==before

def test_r5_empty_paper_sixty_to_twentyfive_keeps_same_preview_and_no_formal_rows(session_factory):
    from backend.models.chat import ChatSession
    from backend.schemas.learning_assistant import StudyContext
    with session_factory.begin() as db:
        session=ChatSession(mode='builtin',purpose='study',study_date='2026-01-01');db.add(session);db.flush();sid=session.id
    ctx=StudyContext(surface='study')
    talk(session_factory,sid,AssistantRequest(question='安排60分钟数学二整体复习，先给我预览',study_context=ctx),NoModel())
    with session_factory() as db:tid=db.scalar(select(LearningTask.id).where(LearningTask.session_id==sid))
    old=get_task(session_factory,tid)
    assert old.draft and old.budget_minutes==60
    before=business_rows(session_factory)
    text='我临时只有 25 分钟了。保留最重要的复习内容，减少练习量，其他内容以后再学。先给我修改后的版本，不要马上创建新计划。'
    talk(session_factory,sid,AssistantRequest(question=text,study_context=ctx),NoModel())
    updated=get_task(session_factory,tid)
    assert updated.draft and updated.budget_minutes==25
    assert_only_expected_preview_revision(before,business_rows(session_factory),tid,25)
    assert before['daily_plans']==before['practice_items']==[]
