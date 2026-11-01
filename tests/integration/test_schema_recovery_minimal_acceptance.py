"""Bounded recovery smoke, only on the runner-owned synthetic PostgreSQL DB."""
from pathlib import Path
import os,json,uuid
from uuid import UUID
from fastapi.testclient import TestClient
from sqlalchemy import select,func
from sqlalchemy.engine import make_url
from backend.models.learning import DailyPlan,PracticeItem,PracticeRetryRequest,Question,QuestionAttempt
from tests.integration.test_learning_loop import clean_database,client,clock,session_factory,leaf_codes


def test_schema_recovery_generate_refresh_duplicate_and_standalone_retry(client,session_factory):
    target=make_url(os.environ['TEST_DATABASE_URL'])
    assert target.database=='kaoyan_test' and target.port!=5433
    assert str(target.port)==os.environ['KAOYAN_OWNED_TEST_PORT']
    # Exercise existing dev Host/Origin checks, while all settings and sessions
    # remain directed at the uniquely owned test DB. No live settings are edited.
    original=client.app.state.settings
    configured=original.model_copy(update={'app_env':'dev','database_url':original.active_database_url})
    assert make_url(str(configured.active_database_url))==target
    client.app.state.settings=configured
    client.base_url='http://127.0.0.1'
    records=[]
    def call(method,path,body=None,status=200,headers=None):
        response=client.request(method,path,json=body,headers=headers or {'Origin':'http://127.0.0.1:5173'})
        records.append({'method':method,'path':path,'body':body,'status':response.status_code,'response':response.json()})
        assert response.status_code==status,response.text
        return response.json()
    try:
        health=call('GET','/api/health')
        assert health['status']=='ok' and health['database']=='connected'
        setup=call('GET','/api/plans/today')
        assert setup['status']=='setup'
        node=leaf_codes(session_factory)['math.calculus.limit.lhopital']
        # The original rejection remains: no Host allowlist or Origin relaxation.
        call('GET','http://testserver/api/plans/today',status=403)
        call('POST','/api/plans/today/generate',{'selected_kp_ids':[str(node)]},403,{'Origin':'http://not-local.invalid'})
        with session_factory() as db:assert db.scalar(select(func.count()).select_from(DailyPlan))==0
        # The historical syllabus seed has legacy type quotas its current bank
        # cannot meet (known OBS-05). Prepare an explicitly synthetic finite set
        # through the existing guarded freeze service, only in the owned DB.
        from backend.services.graduation_question_set import freeze_graduation_question_set
        with session_factory.begin() as db:
            selected=db.scalar(select(Question).where(Question.kp_id==node,
                Question.question_type=='single_choice').order_by(Question.id))
            assert selected is not None
            freeze_graduation_question_set(db,kp_id=node,question_ids=[selected.id],
                reason='SYNTHETIC isolated schema-recovery API fixture, not real mastery evidence')
        body={'selected_kp_ids':[str(node)],'budget':'standard','confirm_legacy_set_transition_ids':[],'extend_existing':False}
        created=call('POST','/api/plans/today/generate',body,201)
        assert created['total_count']>0
        readback=call('GET','/api/plans/today')
        assert readback['plan_id']==created['plan_id'] and readback['total_count']==created['total_count']
        duplicate=call('POST','/api/plans/today/generate',body,409)
        assert duplicate['error']['code']=='plan_already_generated'
        recovered=call('GET','/api/plans/today')
        assert recovered['plan_id']==created['plan_id'] and recovered['total_count']==created['total_count']
        item=created['items'][0]
        with session_factory() as db:
            question=db.get(Question,UUID(item['question_id']))
            if question.question_type=='single_choice':
                wrong=next(key for key in question.options if key!=question.correct_answer)
                answer={'idempotency_key':'schema-smoke-answer-'+uuid.uuid4().hex,'selected_option':wrong}
            else:
                wrong='123456' if str(question.correct_answer).strip()=='0' else '0'
                answer={'idempotency_key':'schema-smoke-answer-'+uuid.uuid4().hex,'raw_answer':wrong}
        receipt=call('POST',f"/api/practice-items/{item['id']}/answer-submissions",answer)
        assert receipt['result']=='wrong'
        key='schema-smoke-retry-'+uuid.uuid4().hex
        retry=call('POST',f"/api/practice-items/{item['id']}/retries",{'idempotency_key':key})
        repeated=call('POST',f"/api/practice-items/{item['id']}/retries",{'idempotency_key':key})
        assert repeated['id']==retry['id'] and retry['retry_source_id']==item['id']
        assert retry['question_id']==item['question_id'] and retry['question_version_id']==item['question_version_id']
        restored=call('GET',f"/api/practice-items/{retry['id']}/retry")
        assert restored['id']==retry['id']
        final=call('GET','/api/plans/today')
        assert final['plan_id']==created['plan_id'] and final['total_count']==created['total_count']
        with session_factory() as db:
            assert db.scalar(select(func.count()).select_from(DailyPlan))==1
            assert db.scalar(select(func.count()).select_from(PracticeItem).where(PracticeItem.plan_id==UUID(created['plan_id'])))==created['total_count']
            assert db.scalar(select(func.count()).select_from(PracticeRetryRequest))==1
            assert db.scalar(select(func.count()).select_from(QuestionAttempt))==1
    finally:
        client.app.state.settings=original
        output=Path(os.environ['PHASE45I_CLOSE_OUTPUT'])/'schema-smoke-requests.json'
        with output.open('x',encoding='utf-8') as f:json.dump(records,f,ensure_ascii=False,indent=2)
