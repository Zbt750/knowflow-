from datetime import datetime,timezone
from zoneinfo import ZoneInfo
from fastapi.testclient import TestClient
from sqlalchemy import delete
import pytest
from tests.integration.test_learning_assistant import session_factory,clean_tasks,clean_database,conversations
from backend.models.chat import ChatSession,ChatMessage
from backend.models.practice_request import PracticeRequest
from backend.app import create_app

@pytest.fixture(autouse=True)
def clean_requests(session_factory):
    with session_factory.begin() as db:db.execute(delete(PracticeRequest))

def test_day_session_hidden_from_formal_history_and_native_web_requires_no_model(session_factory,monkeypatch):
    from backend.api.routes import chat
    def not_called(*a,**k):raise AssertionError('native web-unavailable must not initialize model')
    monkeypatch.setattr(chat,'provider_from_settings',not_called)
    with TestClient(create_app()) as client:
        created=client.post('/api/chat/sessions',json={'mode':'builtin','purpose':'study','title':'今日学习'}).json()
        assert created['study_date']==datetime.now(timezone.utc).astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat()
        with session_factory.begin() as db:db.add(ChatMessage(session_id=created['session_id'],role='assistant',content='轻量提示',status='completed'))
        assert all(s['session_id']!=created['session_id'] for s in client.get('/api/chat/sessions').json())
        formal=client.post('/api/chat/sessions',json={'mode':'builtin','purpose':'qa'}).json()
        response=client.post(f"/api/chat/sessions/{formal['session_id']}/assistant:stream",json={'question':'请联网查询2027最新大纲','study_context':{'surface':'chat'}})
        assert response.status_code==200 and '未配置联网搜索' in response.text
        assert 'event: done' in response.text

def test_material_session_requires_explicit_valid_private_scope(session_factory):
    with TestClient(create_app()) as client:
        assert client.post('/api/chat/sessions',json={'mode':'user','purpose':'materials'}).status_code==422
        assert client.post('/api/chat/sessions',json={'mode':'user','purpose':'study'}).status_code==403
