"""Actual FastAPI/SSE + owned PostgreSQL; all Provider output is simulated."""
import json
import hashlib
import os
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from tests.integration.test_generation_confirmation_recovery import generation_fixture, application, events
from backend.api.routes import chat as routes
from backend.errors import AppError
from backend.models.chat import ChatMessage
from backend.models.learning import Question, QuestionVersion, DailyPlan, PracticeItem, QuestionAttempt, LearningEvent


def protected(factory):
    with factory() as db:
        return {model.__tablename__: sorted(json.dumps(dict(row), sort_keys=True, default=str)
            for row in db.execute(select(model.__table__)).mappings())
            for model in [Question, QuestionVersion, DailyPlan, PracticeItem, QuestionAttempt, LearningEvent]}


def evidence(name, **data):
    output = os.environ.get('PHASE45I_CLOSE_OUTPUT')
    if output:
        # New runner directory per run; never overwrite an earlier evidence file.
        with (Path(output) / f'{name}.json').open('x', encoding='utf-8') as handle:
            json.dump({'simulated_provider': True, **data}, handle, ensure_ascii=False, indent=2, default=str)


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


@pytest.mark.parametrize('fail', [False, True])
def test_route_terminal_history_replay_and_read_only_recovery_agree(generation_fixture, monkeypatch, fail):
    factory, _, _, sid, _ = generation_fixture
    formula = r'模拟教学内容：\[\lim_{x\to0}\frac{1-\cos x}{x^2}=\frac12\]'

    class Simulated:
        model = 'OFFLINE_SIMULATED_TERMINAL_TEST'
        calls = 0

        async def stream(self, messages, *, attempt=1):
            self.calls += 1
            yield formula
            if fail:
                raise AppError('generation_failed', retryable=False)

        def complete(self, *args, **kwargs):
            raise AssertionError('expected actual streaming route')

    provider = Simulated()
    monkeypatch.setattr(routes, '_DeferredProvider', lambda _settings: provider)
    before = protected(factory)
    with TestClient(application(factory)) as client:
        body = {'question': '请说明函数极限的含义，作为普通知识讲解，不安排练习。',
            'request_key': str(uuid4()), 'study_context': {'surface': 'chat'}}
        frames = events(client.post(f'/api/chat/sessions/{sid}/assistant:stream', json=body))
        terminal = [(name, data) for name, data in frames if name in {'done', 'error'}]
        assert len(terminal) == 1, frames
        assert terminal[0][0] == ('error' if fail else 'done')
        assert not any(name in {'planner', 'practice_request', 'personal_generation'} for name, _ in frames)
        mid = next(data['message_id'] for name, data in frames if name == 'meta')
        history = client.get(f'/api/chat/sessions/{sid}/messages').json()
        assistants = [row for row in history if row['role'] == 'assistant']
        assert len(assistants) == 1
        saved = assistants[0]
        assert saved['request_key'] == body['request_key']
        assert saved['message_id'] == mid
        assert saved['status'] == ('failed' if fail else 'completed')
        assert saved['content'].count(formula) == 1
        if not fail:
            assert terminal[0][1]['answer'] == saved['content']
            assert ''.join(data['text'] for name, data in frames if name == 'delta') == saved['content']
        with factory() as db:
            rows_before = [dict(row) for row in db.execute(select(ChatMessage.__table__)).mappings()]
            assert db.get(ChatMessage, UUID(mid)).status == saved['status']
        for _ in range(3):
            assert client.get(f'/api/chat/sessions/{sid}/messages').json() == history
        if not fail:
            calls = provider.calls
            replay = events(client.post(f'/api/chat/sessions/{sid}/assistant:stream', json=body))
            assert any(name == 'meta' and data.get('replayed') for name, data in replay)
            assert provider.calls == calls
            assert client.get(f'/api/chat/sessions/{sid}/messages').json() == history
        with factory() as db:
            rows_after = [dict(row) for row in db.execute(select(ChatMessage.__table__)).mappings()]
            assert rows_after == rows_before
    after = protected(factory)
    assert after == before
    evidence('terminal-failed' if fail else 'terminal-completed', frames=frames, history=history,
        provider_calls=provider.calls, protected_tables_before=before, protected_tables_after=after,
        before_sha256=fingerprint(before), after_sha256=fingerprint(after),
        chat_before_sha256=fingerprint(rows_before), chat_after_sha256=fingerprint(rows_after))


def test_history_keys_distinguish_two_tab_turns_and_study_purpose(generation_fixture, monkeypatch):
    factory, _, _, sid, _ = generation_fixture
    class Simulated:
        model = 'OFFLINE_SIMULATED_MULTI_TURN'
        async def stream(self, messages, *, attempt=1):
            yield r'模拟讲解：\(\frac12\)。'
    monkeypatch.setattr(routes, '_DeferredProvider', lambda _settings: Simulated())
    before = protected(factory)
    with TestClient(application(factory)) as client:
        ids=[];keys=[str(uuid4()),str(uuid4())]
        for key in keys:
            frames=events(client.post(f'/api/chat/sessions/{sid}/assistant:stream',json={
                'question':'请说明函数极限，不安排练习。','request_key':key,'study_context':{'surface':'chat'}}))
            assert frames[-1][0]=='done'
            ids.append(next(data['message_id'] for name,data in frames if name=='meta'))
        history=client.get(f'/api/chat/sessions/{sid}/messages').json()
        assert [row['message_id'] for row in history if row['role']=='assistant']==ids
        assert [row['request_key'] for row in history if row['role']=='assistant']==keys
        study=client.post('/api/chat/sessions',json={'title':'ISOLATED study boundary','mode':'builtin','purpose':'study'}).json()
        assert client.get(f'/api/chat/sessions/{study["session_id"]}/messages?purpose=study').json()==[]
        assert str(sid) not in {row['session_id'] for row in client.get('/api/chat/sessions?purpose=study').json()}
        assert study['session_id'] not in {row['session_id'] for row in client.get('/api/chat/sessions?purpose=qa').json()}
        assert client.get(f'/api/chat/sessions/{sid}/messages').json()==history
    assert protected(factory)==before
    evidence('multi-tab-purpose', message_ids=ids, request_keys=keys, history=history,
        protected_tables_before=before, protected_tables_after=protected(factory))
