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
from backend.errors import AppError


def question_revision(factory, *, root_scope=True, budget=25, estimates=(4,5), change=None):
    sid,ctx,_=setup(factory)
    before=business_rows(factory)
    topic='数学二整体' if root_scope else '当前洛必达法则知识点'
    detail=f'；候选变化={change}' if change else ''
    goal=f'我临时只有{budget}分钟了，请按{topic}调整题量并先给我修改版本，不要马上创建新计划{detail}'
    with pytest.raises(AppError) as caught:
        create_task(factory,CreateTask(goal=goal,budget_minutes=budget,
            session_id=sid,current_plan_id=ctx.daily_plan_id),now=NOW)
    assert caught.value.code=='plan_already_generated'
    assert business_rows(factory)==before
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(LearningTask).where(
            LearningTask.session_id==sid))==0
    return caught.value


@pytest.mark.parametrize('root_scope',[True,False])
def test_f01_nine_minute_question_draft_remains_valid_at_25_minutes(session_factory,root_scope):
    error=question_revision(session_factory,root_scope=root_scope)
    assert error.code=='plan_already_generated'


@pytest.mark.parametrize('change,reason',[('version','question_version_changed'),('in_paper','already_in_today_plan'),('ineligible','question_not_practice_eligible')])
def test_f01_only_actually_rejected_candidate_is_removed(session_factory,change,reason):
    error=question_revision(session_factory,change=change)
    assert error.code=='plan_already_generated'


@pytest.mark.parametrize('estimates,total', [((4,5),4),((6,7),None)])
def test_f01_smaller_legal_budget_and_genuinely_impossible_budget(session_factory,estimates,total):
    error=question_revision(session_factory,budget=5,estimates=estimates)
    assert error.code=='plan_already_generated'


@pytest.mark.parametrize('message',[
    '给我看一道洛必达法则的练习题，先不要加入今日卷。',
    '给我看一道洛必达法则的练习题。',
    '帮我找一道洛必达法则的练习题。',
])
def test_f02_f03_f04_real_preview_confirm_and_repeat_are_one_operation(session_factory,message):
    sid,ctx,_=setup(session_factory)
    before=business_rows(session_factory)
    talk(session_factory,sid,AssistantRequest(question=message,study_context=ctx),NoModel())
    preview=reply(session_factory,sid)
    assert preview.metadata_['capability_route']['capability']=='data_query'
    refs=preview.metadata_['read_only_data_query']['preview_questions']
    assert len(refs)==1 and '尚未加入今日卷' in preview.content
    assert '只读学习证据回读' not in preview.content
    assert business_rows(session_factory)==before
    talk(session_factory,sid,AssistantRequest(question='把刚才那道题加入今天的学习。',study_context=ctx),HandoffEvidenceProvider())
    proposed=reply(session_factory,sid)
    assert proposed.status=='completed'
    after_preview=business_rows(session_factory)
    assert before['practice_items']==after_preview['practice_items'] and before['daily_plans']==after_preview['daily_plans']
    if proposed.metadata_.get('selection_state'):
        state=proposed.metadata_['selection_state']
        assert state['state']=='already_in_today_plan'
        assert state['question_id']==refs[0]['question_id']
        assert '当前今日卷第' in proposed.content
        return
    adjustment=proposed.metadata_['paper_adjustment']
    proposal=adjustment['proposal']
    assert proposal and len(proposal['draft']['replacements'])==1
    chosen=proposal['draft']['replacements'][0]
    assert (chosen['question_id'],chosen['question_version_id'])==(refs[0]['question_id'],refs[0]['question_version'])
    assert '待确认方案' in proposed.content and '尚未改变' in proposed.content
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(LearningTask).where(
            LearningTask.id==UUID(proposal['task_id'])))==1
        assert db.scalar(select(func.count()).select_from(PracticeItem))==len(before['practice_items'])
    talk(session_factory,sid,AssistantRequest(question='确认调整',study_context=ctx),NoModel())
    receipt=reply(session_factory,sid).metadata_['paper_adjustment']['receipt']
    assert receipt['added_count']==1
    after_commit=business_rows(session_factory)
    assert len(after_commit['practice_items'])==len(before['practice_items'])+1
    for _ in range(2):
        talk(session_factory,sid,AssistantRequest(question='把刚才那道题加入今天的学习。',study_context=ctx),NoModel())
        notice=reply(session_factory,sid)
        assert '当前今日卷第' in notice.content
        assert notice.metadata_['selection_state']['state']=='already_in_today_plan'
        assert business_rows(session_factory)==after_commit


def test_f03_missing_antecedent_still_asks_without_writing(session_factory):
    sid,ctx,_=setup(session_factory);before=business_rows(session_factory)
    talk(session_factory,sid,AssistantRequest(question='把刚才那道题加入今天的学习。',study_context=ctx),NoModel())
    assert '没有可确定' in reply(session_factory,sid).content
    assert business_rows(session_factory)==before


@pytest.mark.parametrize('stamp',['expired','invalid'])
def test_recovered_older_bank_preview_cannot_bypass_expiry(session_factory,stamp):
    from datetime import timedelta
    from backend.models.chat import ChatMessage
    from backend.services.practice_preview_reference import latest_preview
    sid,ctx,_=setup(session_factory)
    with session_factory.begin() as db:
        question=db.get(Question,ctx.question_id)
        db.add(ChatMessage(session_id=sid,role='assistant',status='completed',content='题库预览',
            metadata_={'read_only_data_query':{'preview_generated_at':
                (NOW-timedelta(minutes=31)).isoformat() if stamp=='expired' else 'bad-timestamp',
                'preview_questions':[{'question_id':str(question.id),'question_version':question_version_reference(question),
                    'kp_id':str(question.kp_id)}]}}))
        db.flush()
        db.add(ChatMessage(session_id=sid,role='assistant',status='completed',content='其他回复'))
    before=business_rows(session_factory)
    reference,notice=latest_preview(session_factory,sid,'把刚才那道题加入今日学习',NOW)
    assert reference is None and ('过期' in notice or '有效期' in notice)
    assert business_rows(session_factory)==before
