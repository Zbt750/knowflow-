"""Full isolated-PG persistence flows; recorded responses never access a model."""
import hashlib
import json
import os
from pathlib import Path
from uuid import UUID, uuid4
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select, func
from backend.models.chat import ChatSession, ChatMessage
from backend.models.learning import (KnowledgePoint, Question, QuestionVersion, DailyPlan,
    PracticeItem, QuestionAttempt, LearningEvent)
from backend.models.learning_task import LearningTask
from backend.models.practice_request import PracticeRequest
from backend.models.personal_generation import PersonalGenerationBatch
from tests.integration.test_personal_general_generation import general_bank
from tests.integration.test_generation_confirmation_recovery import application, events


def save_evidence(name, payload):
    output = os.environ.get('NAIWA_CLOSEOUT_EVIDENCE')
    if output:
        with (Path(output) / name).open('x', encoding='utf-8') as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, default=str)


def counts(factory):
    models = (Question, QuestionVersion, DailyPlan, PracticeItem, QuestionAttempt,
        LearningEvent, LearningTask, PracticeRequest, PersonalGenerationBatch)
    with factory() as db:
        return {m.__tablename__: db.scalar(select(func.count()).select_from(m)) for m in models}


@pytest.mark.parametrize('filename,expected_sha,evidence_name', [
    ('B-GENERATION-1792822891054804600.json',
     'c0e17996652184e3dcb74bebb98e2fc784b6cb47e5b2da64bc67089d1721aa2e', 'recorded-save-flow.json'),
    ('H-RETEST-1792836068109214700.json',
     '7c9fdfca59e5ad12c8fc62a643073722c5c753383975d8db637c369447410627', 'latest-recorded-save-flow.json'),
])
def test_original_full_candidate_is_rejected_through_sse_persistence_and_replay(general_bank,filename,expected_sha,evidence_name):
    factory, kp = general_bank
    source = Path('storage/quality-audits/naiwa-differentiated-acceptance-20261024') / filename
    evidence = json.loads(source.read_text(encoding='utf-8'))
    response = json.loads(evidence['provider_records'][0]['response_text'])
    raw = response['choices'][0]['message']['content']
    assert hashlib.sha256(raw.encode()).hexdigest() == expected_sha
    class Recorded:
        simulation = True
        model = 'recorded-real-response-offline-replay'
        calls = 0
        def complete(self, messages, *, attempt=1):
            self.calls += 1
            return raw, response['usage']
    provider = Recorded()
    with factory.begin() as db:
        row = db.get(KnowledgePoint, kp)
        row.code = 'math.calculus.limit.lhopital'; row.name = '洛必达法则'
        session = ChatSession(title='TEST_FIXTURE closeout recorded rejection', mode='builtin', purpose='study',
            study_date=datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat())
        db.add(session); db.flush(); sid = session.id
    before = counts(factory)
    body = {'question': evidence['user_prompt'], 'request_key': str(uuid4()),
        'study_context': {'surface': 'study', 'knowledge_node_ids': [str(kp)]}}
    with __import__('fastapi.testclient', fromlist=['TestClient']).TestClient(application(factory, provider)) as client:
        initial = events(client.post(f'/api/chat/sessions/{sid}/assistant:stream?purpose=study', json=body))
        assert any(name == 'meta' for name, _ in initial), initial
        mid = next(data['message_id'] for name, data in initial if name == 'meta')
        body.update(request_key=str(uuid4()), personal_generation_confirmed_kp_id=str(kp),
            personal_generation_confirmation_message_id=mid)
        rejected = events(client.post(f'/api/chat/sessions/{sid}/assistant:stream?purpose=study', json=body))
        result = next(data for name, data in rejected if name == 'personal_generation')
        assert result['status'] == 'failed' and result['question_ids'] == []
        assert result['failures'][0]['reason'] == 'CONFIRMED_WRONG'
        assert 'selected_option_conflicts_with_nonfinite_final_value' in result['failures'][0]['issues']
        assert any(name == 'error' for name, _ in rejected)
        client.post(f'/api/chat/sessions/{sid}/assistant:stream?purpose=study', json=body)
        history = client.get(f'/api/chat/sessions/{sid}/messages?purpose=study').json()
        assert provider.calls == 1
        assert history[-1]['personal_generation']['status'] == 'failed'
    after = counts(factory)
    assert all(after[t] == before[t] for t in before if t != 'personal_generation_batches')
    with factory() as db:
        batch = db.scalar(select(PersonalGenerationBatch))
        assert batch.status == 'failed' and not batch.result['question_ids']
    save_evidence(evidence_name, {'evidence_level':'recorded_response_real_pg_and_sse',
        'original_response_sha256':hashlib.sha256(raw.encode()).hexdigest(), 'session_id':sid,
        'before':before, 'after':after, 'result':result, 'events':rejected,
        'history':history, 'simulation_provider_calls':provider.calls, 'real_model_requests':0})


@pytest.mark.parametrize('prompt', [
    '先简要讲清洛必达法则适用的关键条件，然后只从现有题库里找一道洛必达相关、符合在线练习资格的题，给我预览题干、选项、来源、知识点和难度。不要生成题，不要加入今日卷，也不要创建计划。',
    '从题库找一道洛必达法则的题给我预览，不创建计划，也不加入今日卷。',
])
def test_explicit_no_plan_preview_has_no_learning_task_or_plan_side_effect(general_bank, prompt):
    factory, kp = general_bank
    with factory.begin() as db:
        node = db.get(KnowledgePoint, kp); node.code='math.calculus.limit.lhopital'; node.name='洛必达法则'
        session=ChatSession(title='TEST_FIXTURE read only preview', mode='builtin', purpose='study',
            study_date=datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat())
        db.add(session); db.flush(); sid=session.id
    before=counts(factory)
    class NoModel:
        def __getattr__(self, name): raise AssertionError('read-only preview must not invoke model')
    from fastapi.testclient import TestClient
    with TestClient(application(factory, NoModel())) as client:
        frames=events(client.post(f'/api/chat/sessions/{sid}/assistant:stream?purpose=study', json={
            'question':prompt, 'request_key':str(uuid4()),
            'study_context':{'surface':'study','knowledge_node_ids':[str(kp)]}}))
        save_evidence('preview-observed-'+str(sid)+'.json', {'events':frames,'counts':counts(factory)})
        assert any(n=='done' for n,_ in frames), frames
        assert not any(n in {'planner','practice_request'} for n,_ in frames), frames
        done=next(v for n,v in frames if n=='done')
        assert done['status']=='completed'
        # PRE_GENERATION now returns an explicit blindbox count, not a
        # question preview. Verify stronger structured evidence and no leakage.
        assert '0道可用题' in done['answer']
        with factory() as db:
            saved=db.get(ChatMessage,UUID(done['message_id']))
            facts=saved.metadata_['read_only_data_query']
            assert facts['query_status']=='pre_generation_blindbox'
            assert facts['question_count']==0 and facts['available_to_append_count']==0
            assert facts['preview_questions']==[] and facts['returned_preview_count']==0
            assert facts['writes'] is False and facts['model_called'] is False
            assert facts['scope_node_counts']==[{'kp_id':str(kp),'name':'洛必达法则','practice_eligible_count':0}]
        if prompt.startswith('先简要'):
            assert '系统节点讲解' in done['answer'] and 'infty' in done['answer']
        history=client.get(f'/api/chat/sessions/{sid}/messages?purpose=study').json()
        assert history[-1]['content']==done['answer']
    assert counts(factory)==before
    save_evidence('readonly-preview-'+str(sid)+'.json', {'prompt':prompt,'before':before,
        'after':counts(factory),'events':frames,'history':history,'real_model_requests':0})
