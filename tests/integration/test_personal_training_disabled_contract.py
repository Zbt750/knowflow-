"""Real public disabled contract; retained lifecycle tests are not re-enabled."""
from uuid import uuid4
from fastapi.testclient import TestClient
from sqlalchemy import text
from tests.integration.test_personal_training_lifecycle import training_bank,_app
from tests.integration.test_generation_confirmation_recovery import generation_fixture


def test_disabled_training_entrypoints_preserve_existing_business_rows(training_bank):
    factory,kp_id,owner_id=training_bank
    tables=['personal_trainings','personal_training_items','personal_training_attempts',
        'personal_generation_batches','daily_plans','practice_items','question_attempts',
        'learning_events','kp_states','questions','question_versions']
    def snapshot():
        with factory() as db:
            return {table:sorted(str(row) for row in db.scalars(text(f'SELECT to_jsonb(t) FROM {table} t')))
                for table in tables}
    training_id=uuid4();item_id=uuid4();base=f'/api/practice-trainings/{training_id}'
    owner={'owner_session_id':str(owner_id)}
    action={**owner,'request_key':'TEST_FIXTURE-disabled-action-01','expected_version':1}
    requests=[
        ('get','/api/practice-trainings',None),
        ('post','/api/practice-trainings',{**owner,'request_key':'TEST_FIXTURE-disabled-create-01',
            'knowledge_point_ids':[str(kp_id)],'question_count':2,'target_minutes':30,'basis':'selected'}),
        ('get',base,None),('get',base+'/report',None),
        ('post',base+'/pause',action),('post',base+'/resume',action),('post',base+'/finish',action),
        ('post',base+'/items',{**action,'question_count':1}),
        ('post',base+'/next',{**owner,'request_key':'TEST_FIXTURE-disabled-next-01','question_count':1,'target_minutes':10}),
        ('patch',base+f'/items/{item_id}/draft',{**owner,'expected_draft_revision':0,'draft_selected_option':'A'}),
        ('post',base+f'/items/{item_id}/answers',{**owner,'idempotency_key':'TEST_FIXTURE-disabled-answer-01',
            'expected_version':1,'selected_option':'A'}),
    ]
    before=snapshot()
    with TestClient(_app(factory)) as client:
        for method,url,payload in requests:
            response=client.request(method,url,params=owner if method=='get' else None,json=payload)
            assert response.status_code==409,(method,url,response.text)
            assert response.json()['error']['code']=='personal_training_disabled'
            assert snapshot()==before
