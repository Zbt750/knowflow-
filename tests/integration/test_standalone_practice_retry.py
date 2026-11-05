"""Real PostgreSQL/route flow; no fabricated Attempt/Event rows."""
from uuid import UUID
from concurrent.futures import ThreadPoolExecutor
import pytest
from sqlalchemy import select, func
from tests.integration.test_learning_loop import clean_database, client, clock, session_factory
from tests.integration.test_first_answer_state import prepare_missing_state
from backend.models.learning import DailyPlan, PracticeItem, QuestionAttempt, LearningEvent, KpState

def answer(client, item, key, value):
    response=client.post(f'/api/practice-items/{item}/answer-submissions',json={'idempotency_key':key,'raw_answer':value})
    assert response.status_code==200,response.text
    return response.json()

def retry(client,item,key):
    response=client.post(f'/api/practice-items/{item}/retries',json={'idempotency_key':key})
    assert response.status_code==200,response.text
    return response.json()

def test_wrong_reveal_retry_correct_preserves_original_and_does_not_enlarge_plan(client,session_factory,clock):
    item,kp=prepare_missing_state(session_factory)
    original=answer(client,item,'retry-first-wrong','0')
    assert original['result']=='wrong' and not original['assisted']
    assert client.post(f'/api/practice-items/{item}/answer-reveal',json={}).status_code==200
    created=retry(client,item,'retry-create-once')
    assert created['id']!=item
    assert created['answer_revealed_at'] and created['retry_source_id']==item
    assert retry(client,item,'retry-create-once')['id']==created['id']
    assert retry(client,item,'retry-other-tab')['id']==created['id']
    saved=answer(client,created['id'],'retry-answer-once','1')
    assert saved['result']=='right' and saved['assisted'] and saved['assistance_level']=='solution'
    assert saved['effective_confirmation_count']==0
    assert saved['question_version_id']==created['question_version_id']==original['question_version_id']
    assert answer(client,created['id'],'retry-answer-once','1')==saved
    assert retry(client,item,'retry-other-tab')['id']==created['id']
    restored=client.get(f"/api/practice-items/{created['id']}/retry").json()
    assert restored['answer_submission']==saved and restored['completed']
    assert client.get(f'/api/practice-items/{item}/answer-submissions').json()['items']==[original]
    from backend.services.learning_task_tools import TaskTools
    from backend.services.learning_task_service import _inventory_free_advice
    from backend.schemas.learning_task import QuestionAvailabilityQuery
    tools=TaskTools(session_factory,budget_minutes=90,now=clock.now,goal='数学二整体90分钟建议，不创建计划')
    tools.nodes.add(kp)
    state_result=tools.execute('get_learning_state',{'kp_ids':[str(kp)]})
    # Explicitly exclude every already-used question in this private fixture to exercise zero stock.
    with session_factory() as db:
        from backend.models.learning import Question
        question_ids=[str(q) for q in db.scalars(select(Question.id).where(Question.kp_id==kp))]
    availability=tools.execute('get_question_availability',{'kp_ids':[str(kp)],'exclude_question_ids':question_ids})
    assert availability['available_to_append_count']==0
    advice=_inventory_free_advice([{'tool':'get_learning_state','status':'completed','result':state_result},
        {'tool':'get_question_availability','status':'completed','result':availability}],90)
    assert '独立答错1次' in advice and '辅助后答对1次' in advice
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(DailyPlan))==1
        assert db.scalar(select(func.count()).select_from(PracticeItem).where(PracticeItem.plan_id.is_not(None)))==1
        assert db.scalar(select(func.count()).select_from(QuestionAttempt))==2
        assert db.scalar(select(func.count()).select_from(LearningEvent).where(LearningEvent.event_type=='answer_submitted'))==2
        assert db.get(KpState,kp).mastered_at is None
        assert db.get(PracticeItem,UUID(created['id'])).plan_id is None

def test_retry_wrong_then_retry_again_retains_all_receipts(client,session_factory):
    item,_=prepare_missing_state(session_factory)
    answer(client,item,'retry-chain-original','0')
    client.post(f'/api/practice-items/{item}/answer-reveal',json={})
    first=retry(client,item,'retry-chain-first')
    answer(client,first['id'],'retry-chain-wrong','0')
    # Product rule changed by BUG-IND-005: no nested retry instances. A new
    # explicit request from the original wrong item remains supported.
    nested=client.post(f"/api/practice-items/{first['id']}/retries",json={'idempotency_key':'retry-chain-second'})
    assert nested.status_code==409 and nested.json()['error']['code']=='practice_retry_nested_not_allowed'
    second=retry(client,item,'retry-root-again')
    final=answer(client,second['id'],'retry-chain-correct','1')
    assert final['assisted'] and final['effective_confirmation_count']==0
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(QuestionAttempt))==3
        assert db.scalar(select(func.count()).select_from(DailyPlan))==1

def test_today_active_exposes_wrong_retry_for_review_without_counting_it_as_paper(client,session_factory):
    item,_=prepare_missing_state(session_factory)
    original=answer(client,item,'review-retry-root-wrong','0')
    assert original['result']=='wrong' and original['assisted'] is False
    assert client.post(f'/api/practice-items/{item}/answer-reveal',json={}).status_code==200
    retry_item=retry(client,item,'review-retry-create')
    receipt=answer(client,retry_item['id'],'review-retry-wrong','0')
    assert receipt['result']=='wrong' and receipt['assisted'] is True

    today=client.get('/api/plans/today')
    assert today.status_code==200,today.text
    payload=today.json()
    assert payload['total_count']==1
    assert len(payload['items'])==1 and payload['items'][0]['id']==item
    assert [row['id'] for row in payload['retry_wrong_items']]==[retry_item['id']]
    assert payload['retry_wrong_items'][0]['question_id']==payload['items'][0]['question_id']
    assert payload['retry_wrong_items'][0]['question_version_id']==payload['items'][0]['question_version_id']
    assert payload['retry_wrong_items'][0]['answer_submission']['result']=='wrong'
    assert payload['retry_wrong_items'][0]['answer_submission']['assisted'] is True
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(PracticeItem))==2
        assert db.scalar(select(func.count()).select_from(QuestionAttempt))==2
        assert db.scalar(select(func.count()).select_from(DailyPlan))==1

def test_retry_rejects_unanswered_or_correct_source_without_side_effects(client,session_factory):
    item,_=prepare_missing_state(session_factory)
    assert client.post(f'/api/practice-items/{item}/retries',json={'idempotency_key':'retry-invalid-new'}).status_code==409
    receipt=answer(client,item,'retry-source-right','1')
    assert not receipt['assisted']
    assert client.post(f'/api/practice-items/{item}/retries',json={'idempotency_key':'retry-invalid-right'}).status_code==409
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(PracticeItem))==1
        assert db.scalar(select(func.count()).select_from(QuestionAttempt))==1

def test_concurrent_retry_creation_resumes_one_pending_instance(client,session_factory):
    item,_=prepare_missing_state(session_factory)
    answer(client,item,'retry-parallel-wrong','0')
    with ThreadPoolExecutor(max_workers=2) as pool:
        rows=list(pool.map(lambda i:retry(client,item,f'retry-parallel-{i}'),range(2)))
    assert rows[0]['id']==rows[1]['id']
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(PracticeItem).where(PracticeItem.retry_source_id==UUID(item)))==1

def test_retry_rollback_leaves_no_half_instance_and_reading_preserves_full_rows(client,session_factory,clock):
    from backend.services.practice_retry_service import create_retry
    from sqlalchemy import text
    item,_=prepare_missing_state(session_factory)
    answer(client,item,'rollback-original-wrong','0')
    with pytest.raises(RuntimeError,match='injected rollback'):
        with session_factory.begin() as db:
            create_retry(db,source_id=UUID(item),key='rollback-private-key',now=clock.now)
            raise RuntimeError('injected rollback')
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(PracticeItem))==1
    created=retry(client,item,'rollback-then-retry')
    def snapshot():
        with session_factory() as db:
            return {table:db.execute(text(f'SELECT to_jsonb(t) FROM {table} t ORDER BY id')).scalars().all()
                for table in ['daily_plans','practice_items','question_attempts','learning_events']}
    before=snapshot()
    for _ in range(3):
        assert client.get(f"/api/practice-items/{created['id']}/retry").status_code==200
        assert client.get(f'/api/practice-items/{item}/retries').status_code==200
    assert snapshot()==before

def test_agent_zero_stock_runs_actual_tools_and_returns_timed_advice_without_plan_writes(client,session_factory,clock):
    import json,re
    from backend.models.learning import Question
    from backend.services.learning_task_service import create_task,run_task
    from backend.schemas.learning_task import CreateTask
    item,kp=prepare_missing_state(session_factory)
    answer(client,item,'agent-original-wrong','0')
    client.post(f'/api/practice-items/{item}/answer-reveal',json={})
    repeated=retry(client,item,'agent-assisted-retry')
    answer(client,repeated['id'],'agent-assisted-right','1')
    with session_factory.begin() as db:
        original=db.get(PracticeItem,UUID(item))
        questions=list(db.scalars(select(Question).where(Question.kp_id==kp,Question.id!=original.question_id)))
        for i,q in enumerate(questions,2):
            db.add(PracticeItem(plan_id=original.plan_id,question_id=q.id,kp_id=kp,ordinal=i))
        db.flush()
        independent=db.scalar(select(PracticeItem).where(PracticeItem.plan_id==original.plan_id,PracticeItem.id!=original.id).order_by(PracticeItem.ordinal))
        assert independent is not None
        q=db.get(Question,independent.question_id)
        independent_id=str(independent.id); correct=q.correct_answer
        answer_payload={'selected_option':correct} if q.options else {'raw_answer':correct}
    response=client.post(f'/api/practice-items/{independent_id}/answer-submissions',json={
        'idempotency_key':'agent-independent-right',**answer_payload})
    assert response.status_code==200,response.text
    assert response.json()['result']=='right' and response.json()['assisted'] is False,response.text
    class OfflineTools:
        def __init__(self): self.calls=0
        def tool_turn(self,messages,tools,*,timeout):
            self.calls+=1
            actions=([('search_knowledge',{'query':'洛必达'})] if self.calls==1 else
                [('get_learning_state',{'kp_ids':[str(kp)]}),('get_question_availability',{'kp_ids':[str(kp)]})] if self.calls==2 else [])
            if not actions:return {'model':'OFFLINE-SIMULATION','message':{'content':json.dumps({'message':'模拟Provider已读取工具','needs_clarification':False},ensure_ascii=False)}}
            return {'model':'OFFLINE-SIMULATION','message':{'tool_calls':[{'id':f'sim-{self.calls}-{i}','type':'function','function':{'name':n,'arguments':json.dumps(a)}} for i,(n,a) in enumerate(actions)]}}
    with session_factory() as db:
        before=[db.scalar(select(func.count()).select_from(model)) for model in [DailyPlan,PracticeItem,QuestionAttempt,LearningEvent]]
    created=create_task(session_factory,CreateTask(goal='根据洛必达真实作答情况给我90分钟复习建议，不创建正式计划',budget_minutes=90),
        now=clock.now,read_only=True)
    result=run_task(session_factory,created.task_id,OfflineTools(),now=clock.now)
    assert result.status=='answered',result
    assert '独立答对1次' in result.message and '独立答错1次' in result.message and '辅助后答对1次' in result.message
    assert sum(map(int,re.findall(r'\d+\. (\d+)分钟',result.message)))==90
    with session_factory() as db:
        assert [db.scalar(select(func.count()).select_from(model)) for model in [DailyPlan,PracticeItem,QuestionAttempt,LearningEvent]]==before


def test_r6_completed_wrong_retry_is_stable_across_repeated_read_only_refresh(client,session_factory):
    from tests.integration.test_explore_student_repairs import business_rows
    from tests.integration.test_standalone_practice_retry import test_today_active_exposes_wrong_retry_for_review_without_counting_it_as_paper
    test_today_active_exposes_wrong_retry_for_review_without_counting_it_as_paper(client,session_factory)
    before=business_rows(session_factory)
    one=client.get('/api/plans/today').json();two=client.get('/api/plans/today').json()
    assert one==two
    root_ids={r['id'] for r in one['items'] if r['answer_submission']['result']=='wrong'}
    retry_ids={r['id'] for r in one['retry_wrong_items'] if r['answer_submission']['result']=='wrong'}
    assert len(root_ids|retry_ids)==2 and not root_ids&retry_ids
    assert business_rows(session_factory)==before
