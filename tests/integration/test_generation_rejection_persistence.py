"""Actual APIs/owned PG, no paid calls; fixed malformed/valid responses."""
from uuid import uuid4
import json
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select,func
from backend.errors import AppError
from backend.models.learning import Question,QuestionVersion,PracticeItem,DailyPlan
from backend.models.personal_generation import PersonalGenerationBatch
from backend.services.personal_question_service import run_generation
from tests.integration.test_personal_general_generation import general_bank,GeneralModel,request,NOW
from tests.integration.test_generation_confirmation_recovery import generation_fixture,application,events


@pytest.mark.parametrize('fault,code', [('duplicate_options','format_invalid'),('wrong_step','answer_conflict'),
    ('wrong_type','type_mismatch'),('empty_explanation','content_incomplete'),('timeout','provider_timeout')])
def test_failed_checks_persist_specific_diagnostic_and_zero_questions(general_bank,fault,code):
    factory,kp = general_bank
    class ValidWrongTypeModel(GeneralModel):
        def complete(self,*args,**kwargs):
            raw,usage = super().complete(*args,**kwargs)
            data = json.loads(raw)
            # A valid proof payload isolates the requested-type rule. Keeping
            # A-D options on a proof would fail its shape check even earlier.
            data.update(options=None,correct_answer='公比为1/2。',final_value='1/2')
            return json.dumps(data,ensure_ascii=False),usage
    model = ValidWrongTypeModel(fault) if fault=='wrong_type' else GeneralModel(fault)
    body = request(kp)
    result = run_generation(factory,body,model,now=NOW)
    assert result['diagnostics'][0]['code'] == 'personal_generation_' + code,result
    assert not result['question_ids'] and model.calls == 1
    replay = run_generation(factory,body,model,now=NOW)
    assert replay['diagnostics'] == result['diagnostics'] and model.calls == 1
    with factory() as db:
        row = db.scalar(select(PersonalGenerationBatch))
        assert row.status == 'failed' and row.result['diagnostics'] == result['diagnostics']
        for table in (Question,QuestionVersion,PracticeItem,DailyPlan):
            assert db.scalar(select(func.count()).select_from(table)) == 0


def test_truncated_sse_history_and_replay_never_calls_provider_twice(generation_fixture):
    factory,_,kp,sid,model = generation_fixture
    class Truncated:
        calls = 0
        simulation = True
        def complete(self,*args,**kwargs):
            self.calls += 1
            raise AppError('answer_truncated',retryable=False)
    provider = Truncated()
    with TestClient(application(factory,provider)) as client:
        statement = '帮我出一道类似的题，但是要更难一点。原题：当|x|<1时，求级数sum nx^n的和。'
        initial = {'question':statement,'request_key':str(uuid4())}
        frames = events(client.post(f'/api/chat/sessions/{sid}/assistant:stream',json=initial))
        card = next(data['message_id'] for name,data in frames if name=='meta')
        body = {**initial,'request_key':str(uuid4()),'personal_generation_confirmed_kp_id':str(kp),
                'personal_generation_confirmation_message_id':card}
        failed = events(client.post(f'/api/chat/sessions/{sid}/assistant:stream',json=body))
        result = next(data for name,data in failed if name=='personal_generation')
        assert result['diagnostics'][0]['code']=='personal_generation_output_truncated'
        assert failed[-1][0]=='error' and '不是已判定答案错误' in failed[-1][1]['message']
        history = client.get(f'/api/chat/sessions/{sid}/messages').json()
        assert history[-1]['personal_generation']['diagnostics']==result['diagnostics']
        client.post(f'/api/chat/sessions/{sid}/assistant:stream',json=body)
        assert provider.calls==1
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Question)) == 0
        assert db.scalar(select(func.count()).select_from(PracticeItem)) == 0
