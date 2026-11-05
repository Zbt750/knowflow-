"""Real HTTP routes and assistant SSE over the runner-owned PostgreSQL database."""
from uuid import UUID
import pytest
from sqlalchemy import select, func
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tests.integration.test_student_uiv2_repairs import session_factory, clean_database, clean_tasks, conversations, setup, talk, reply, NOW, NoModel
from backend.models.learning import PracticeItem, Question, QuestionAttempt, LearningEvent, KpState
from backend.schemas.learning_assistant import AssistantRequest
from backend.services.question_versions import question_version_reference
from backend.api.routes.learning_tasks import router
from backend.api.deps import get_time_provider
from backend.errors import register_error_handlers


def test_live_migration_and_identity(session_factory, record_property):
    from sqlalchemy import text, inspect
    with session_factory() as db:
        identity=db.execute(text('SELECT current_database(),current_user,inet_server_port()')).one()
        assert identity[0].endswith('_test') and identity[1]=='kaoyan_app' and identity[2]!=5433
        revision=db.scalar(text('SELECT version_num FROM alembic_version'))
        assert revision=='f59e33bc52d8'
        fk=next(f for f in inspect(db.connection()).get_foreign_keys('question_attempts') if f['constrained_columns']==['practice_item_id'])
        assert fk['options']['ondelete']=='RESTRICT'
        record_property('database_identity',str(tuple(identity)))
        record_property('migration_after',revision)
        record_property('attempt_foreign_key',str(fk['options']))


def client(factory):
    app=FastAPI();app.state.session_factory=factory
    app.include_router(router,prefix='/api');register_error_handlers(app)
    app.dependency_overrides[get_time_provider]=lambda:lambda:NOW
    return TestClient(app)


def history(factory):
    with factory() as db:
        return tuple(db.scalar(select(func.count()).select_from(model)) for model in
            (QuestionAttempt,KpState))


def test_real_http_replace_and_replay_keep_original_item(session_factory):
    sid,ctx,_=setup(session_factory)
    with session_factory() as db:
        q=db.scalar(select(Question).where(Question.kp_id==ctx.knowledge_node_ids[0],Question.id!=ctx.question_id,
            Question.question_type=='single_choice').order_by(Question.id))
        reference={'question_id':str(q.id),'question_version_id':question_version_reference(q)}
    before=history(session_factory)
    c=client(session_factory)
    response=c.post('/api/paper-adjustments',json={'session_id':str(sid),'plan_id':str(ctx.daily_plan_id),
        'remove_item_ids':[str(ctx.practice_item_id)],'replacements':[reference],'budget_minutes':60})
    assert response.status_code==201,response.text
    proposal=response.json();url=f"/api/paper-adjustments/{proposal['task_id']}/confirm"
    body={'session_id':str(sid),'draft_version':proposal['draft_version']}
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses=list(pool.map(lambda _:client(session_factory).post(url,json=body),range(2)))
    committed=responses[0];assert committed.status_code==200,committed.text
    assert responses[1].status_code==200 and responses[1].json()==committed.json()
    assert c.post(url,json=body).json()==committed.json()
    with session_factory() as db:
        assert db.get(PracticeItem,ctx.practice_item_id).removed_at is not None
        active=list(db.scalars(select(PracticeItem).where(PracticeItem.plan_id==ctx.daily_plan_id,PracticeItem.removed_at.is_(None))))
        assert len(active)==1 and str(active[0].question_id)==reference['question_id']
        assert str(active[0].question_version_id)==reference['question_version_id']
    assert history(session_factory)==before


def test_real_http_invalidated_replacement_rolls_back_removal(session_factory):
    sid,ctx,_=setup(session_factory);c=client(session_factory)
    with session_factory() as db:
        q=db.scalar(select(Question).where(Question.kp_id==ctx.knowledge_node_ids[0],Question.id!=ctx.question_id,
            Question.question_type=='single_choice').order_by(Question.id));qid=q.id;version=question_version_reference(q)
    proposal=c.post('/api/paper-adjustments',json={'session_id':str(sid),'plan_id':str(ctx.daily_plan_id),
        'remove_item_ids':[str(ctx.practice_item_id)],'replacements':[{'question_id':str(qid),'question_version_id':version}],
        'budget_minutes':60}).json()
    with session_factory.begin() as db:db.get(Question,qid).is_active=False
    failed=c.post(f"/api/paper-adjustments/{proposal['task_id']}/confirm",json={'session_id':str(sid),'draft_version':proposal['draft_version']})
    assert failed.status_code==409,failed.text
    with session_factory() as db:
        assert db.get(PracticeItem,ctx.practice_item_id).removed_at is None
        assert db.scalar(select(func.count()).select_from(PracticeItem).where(PracticeItem.plan_id==ctx.daily_plan_id))==1


def test_actual_assistant_preview_then_explicit_confirmation(session_factory):
    sid,ctx,_=setup(session_factory)
    talk(session_factory,sid,AssistantRequest(question='减少一道洛必达法则题目。',study_context=ctx),NoModel())
    preview=reply(session_factory,sid)
    assert preview.metadata_['paper_adjustment']['proposal']
    with session_factory() as db:assert db.get(PracticeItem,ctx.practice_item_id).removed_at is None
    talk(session_factory,sid,AssistantRequest(question='确认调整',study_context=ctx),NoModel())
    done=reply(session_factory,sid)
    assert done.metadata_['paper_adjustment']['receipt']['total_count']==0
    with session_factory() as db:assert db.get(PracticeItem,ctx.practice_item_id).removed_at is not None


@pytest.mark.parametrize('completed',[True,False])
def test_answer_history_and_database_foreign_key_survive_rejected_removal(session_factory,completed):
    from backend.services.answer_submission_service import submit_answer
    from sqlalchemy import delete
    from sqlalchemy.exc import IntegrityError
    import pytest
    sid,ctx,correct=setup(session_factory)
    with session_factory.begin() as db:
        submission=submit_answer(db,item_id=ctx.practice_item_id,raw_answer=None,
            selected_option=correct,idempotency_key='r36-real-answer-history',now=NOW)
        if not completed:
            db.get(PracticeItem,ctx.practice_item_id).completed_at=None
    with session_factory() as db:
        saved=db.get(QuestionAttempt,submission.attempt_id)
        evidence=saved.grading_evidence
        events=[(e.id,e.event_type,e.payload) for e in db.scalars(select(LearningEvent).order_by(LearningEvent.id))]
    failed=client(session_factory).post('/api/paper-adjustments',json={'session_id':str(sid),
        'plan_id':str(ctx.daily_plan_id),'remove_item_ids':[str(ctx.practice_item_id)],'budget_minutes':60})
    assert failed.status_code==409,failed.text
    with pytest.raises(IntegrityError):
        with session_factory.begin() as db:db.execute(delete(PracticeItem).where(PracticeItem.id==ctx.practice_item_id))
    with session_factory() as db:
        assert db.get(QuestionAttempt,submission.attempt_id).grading_evidence==evidence
        assert db.get(PracticeItem,ctx.practice_item_id).removed_at is None
        assert [(e.id,e.event_type,e.payload) for e in db.scalars(select(LearningEvent).order_by(LearningEvent.id))]==events


def test_actual_408_inventory_shortage_never_changes_math_paper(session_factory):
    sid,ctx,_=setup(session_factory)
    talk(session_factory,sid,AssistantRequest(question='把今天数学题全部换成408，安排6个知识点，60分钟左右。',study_context=ctx),NoModel())
    response=reply(session_factory,sid)
    assert response.metadata_['paper_adjustment']['proposal'] is None
    assert '正式准入库存' in response.content
    with session_factory() as db:assert db.get(PracticeItem,ctx.practice_item_id).removed_at is None


def test_actual_multi_turn_correction_and_difficulty_clarification(session_factory):
    sid,ctx,_=setup(session_factory)
    with session_factory.begin() as db:
        current=list(db.scalars(select(PracticeItem).where(PracticeItem.plan_id==ctx.daily_plan_id)))
        existing={item.question_id for item in current}
        candidates=list(db.scalars(select(Question).where(Question.kp_id==ctx.knowledge_node_ids[0],
            Question.is_active.is_(True)).order_by(Question.id)))
        added=0
        for question in (q for q in candidates if q.id not in existing):
            db.add(PracticeItem(plan_id=ctx.daily_plan_id,question_id=question.id,
                question_version_id=question.current_version_id,kp_id=question.kp_id,
                ordinal=len(current)+added+1))
            added+=1
            existing.add(question.id)
            if len(current)+added>=3:break
    talk(session_factory,sid,AssistantRequest(question='减少两道洛必达法则题目。',study_context=ctx),NoModel())
    two=reply(session_factory,sid).metadata_['paper_adjustment']['proposal']
    assert two and len(two['draft']['remove_item_ids'])==2
    talk(session_factory,sid,AssistantRequest(question='改成减少一道。',study_context=ctx),NoModel())
    one=reply(session_factory,sid).metadata_['paper_adjustment']['proposal']
    assert one and len(one['draft']['remove_item_ids'])==1
    talk(session_factory,sid,AssistantRequest(question='减少一道比较简单的题。',study_context=ctx),NoModel())
    assert '没有可核验' in reply(session_factory,sid).content
    with session_factory() as db:assert db.get(PracticeItem,ctx.practice_item_id).removed_at is None
    talk(session_factory,sid,AssistantRequest(question='删除第1题',study_context=ctx),NoModel())
    assert reply(session_factory,sid).metadata_['paper_adjustment']['proposal']
    talk(session_factory,sid,AssistantRequest(question='先不要删除第1题',study_context=ctx),NoModel())
    assert '待确认调整方案' in reply(session_factory,sid).content and '正式卷保持原状态' in reply(session_factory,sid).content
    talk(session_factory,sid,AssistantRequest(question='确认调整',study_context=ctx),NoModel())
    assert '没有可确认' in reply(session_factory,sid).content
    with session_factory() as db:assert db.get(PracticeItem,ctx.practice_item_id).removed_at is None
