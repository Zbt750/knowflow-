"""Real PostgreSQL query refinement; a model invocation is a test failure."""
import json
from uuid import uuid4
import pytest
from sqlalchemy import func, select, text
from fastapi.testclient import TestClient
from tests.integration.test_learning_loop import session_factory
from tests.integration.query_followup_backend import prepare_fixture, NoModel, NOW
from backend.models.chat import ChatMessage
from backend.models.learning import Question, QuestionVersion, PracticeItem, QuestionAttempt, LearningEvent


@pytest.fixture(autouse=True)
def query_fixture(session_factory):
    with session_factory.begin() as db:
        db.execute(text("TRUNCATE chat_sessions, knowledge_points, questions, daily_plans CASCADE"))
    return prepare_fixture(session_factory)


@pytest.fixture
def query_client(monkeypatch):
    from scripts.e2e_backend import create_e2e_app
    from backend.chat import service
    import backend.app as app_module
    # The offline factory assigns Provider directly. Record the original first
    # so fixture teardown also restores it for following real-Provider unit tests.
    monkeypatch.setattr(service, "Provider", service.Provider)
    app = create_e2e_app()
    monkeypatch.setattr(service, "Provider", NoModel)
    monkeypatch.setattr(app_module, "_try_build_retrieval_stack", lambda *args: False)
    from backend.api.deps import get_time_provider
    app.dependency_overrides[get_time_provider] = lambda: lambda: NOW
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def send(client, sid, message):
    response = client.post(f"/api/chat/sessions/{sid}/assistant:stream", json={"question": message,
        "study_context": {"surface": "chat", "conversation_id": sid}, "request_key": str(uuid4())})
    assert response.status_code == 200
    frames = [(part.splitlines()[0][7:], json.loads(part.splitlines()[1][6:]))
        for part in response.text.strip().split("\n\n") if part.strip()]
    assert not [data for event, data in frames if event == "error"], frames
    assert frames[-1][0] == "done", frames
    return frames[-1][1]


def trace(factory, sid):
    with factory() as db:
        row = db.scalar(select(ChatMessage).where(ChatMessage.session_id == sid,
            ChatMessage.role == "assistant").order_by(ChatMessage.seq.desc()))
        return row.metadata_["read_only_data_query"]


def new_session(client):
    return client.post("/api/chat/sessions", json={"title": "隔离多轮统计", "mode": "builtin", "purpose": "qa"}).json()["session_id"]


def test_five_filtered_bank_questions_execute_through_assistant_without_mutating_formal_paper(query_client,session_factory,query_fixture):
    from uuid import UUID
    from backend.models.learning import DailyPlan
    from tests.integration.test_learning_loop import mark_isolated_question_trusted
    new_ids=[]
    with session_factory.begin() as db:
        for index in range(5):
            q=Question(kp_id=UUID(query_fixture['lhopital_id']),stem=f'SYNTHETIC quantity query {index}: 2+2=?',
                question_type='single_choice',difficulty='medium',options={'A':'4','B':'5'},correct_answer='A',
                explanation='合成测试 2+2=4',estimated_minutes=5,grading_mode='auto',
                grading_config={'verified':True,'method':'single_choice'},is_active=True)
            mark_isolated_question_trusted(q,db=db);db.flush();new_ids.append(str(q.id))
        before={m.__name__:db.scalar(select(func.count()).select_from(m)) for m in (DailyPlan,PracticeItem,QuestionAttempt,QuestionVersion)}
    sid=new_session(query_client)
    response=send(query_client,sid,'从正式题库找五道中等难度的洛必达法则题，排除做过的，不要加入今日卷')
    evidence=trace(session_factory,sid)
    assert evidence['tools_used'][-1]=='find_questions'
    assert evidence['requested_preview_count']==evidence['returned_preview_count']==5
    assert {q['question_id'] for q in evidence['preview_questions']}==set(new_ids)
    assert len(evidence['preview_questions'])==5 and evidence['writes'] is False
    assert '预览 5 道' in response['answer']
    with session_factory() as db:
        for row in evidence['preview_questions']:
            q=db.get(Question,UUID(row['question_id']))
            assert row['question_version']==str(q.current_version_id) and q.difficulty=='medium'
        after={m.__name__:db.scalar(select(func.count()).select_from(m)) for m in (DailyPlan,PracticeItem,QuestionAttempt,QuestionVersion)}
    assert before==after


def test_real_sse_refinement_subject_node_source_history(query_client, session_factory):
    sid = new_session(query_client)
    messages = [("我题库里有多少道数学二的可练题？", "question_count", 4),
        ("那其中洛必达法则的题有多少道？", "question_count", 3),
        ("其中多少道是真题？", "question_count", 2),
        ("这些题我做过几道？", "distinct_question_count", 2),
        ("那里面我做错过哪些？", "distinct_question_count", 1)]
    with session_factory() as db:
        before = {m.__name__: db.scalar(select(func.count()).select_from(m)) for m in
            (Question, QuestionVersion, PracticeItem, QuestionAttempt, LearningEvent)}
    for message, key, count in messages:
        result = send(query_client, sid, message)
        data = trace(session_factory, sid)
        assert data[key] == count, (message, result, data)
        assert data["model_called"] is False and data["writes"] is False
        assert data["query_state"]["subject"] == "考研数学"
    assert "洛必达真题甲" in result["answer"] and "洛必达原创丙" not in result["answer"]
    assert data["tools_used"] == ["question_attempts", "learning_events", "get_learning_state"]
    assert all(ref["binding_valid"] for ref in data["version_binding"])
    with session_factory() as db:
        after = {m.__name__: db.scalar(select(func.count()).select_from(m)) for m in
            (Question, QuestionVersion, PracticeItem, QuestionAttempt, LearningEvent)}
    assert before == after
    restored = query_client.get(f"/api/chat/sessions/{sid}/messages").json()
    assert len(restored) == 10


def test_unknown_node_and_other_session_never_inherit(query_client, session_factory):
    first, other = new_session(query_client), new_session(query_client)
    send(query_client, first, "我题库里有多少道数学二的可练题？")
    send(query_client, first, "那其中不存在法则的题有多少道？")
    assert trace(session_factory, first)["query_status"] == "needs_clarification"
    result = send(query_client, other, "其中多少道是真题？")
    assert trace(session_factory, other)["query_status"] == "needs_clarification"
    assert "请先说明" in result["answer"]


def test_latest_explanation_is_not_overridden_by_query_context(query_client, session_factory):
    sid = new_session(query_client)
    send(query_client, sid, "我题库里有多少道数学二的可练题？")
    from backend.services.assistant_data_queries import classify_session_data_query
    assert classify_session_data_query(session_factory, session_id=sid, message="请解释洛必达法则的使用条件") is None
    assert classify_session_data_query(session_factory, session_id=sid, message="检查这道题的解题思路") is None


def test_database_query_failure_is_error_not_general_fallback(query_client, monkeypatch):
    from sqlalchemy.exc import OperationalError
    import backend.services.assistant_data_queries as queries
    def broken(*args, **kwargs):
        raise OperationalError("SELECT", {}, RuntimeError("isolated fixture failure"))
    monkeypatch.setattr(queries, "execute_read_only_data_query", broken)
    sid = new_session(query_client)
    response = query_client.post(f"/api/chat/sessions/{sid}/assistant:stream", json={"question": "数学二题库有多少道题？"})
    assert "event: error" in response.text
    assert "通用知识" not in response.text


def test_new_explicit_query_resets_scope_and_intervening_answer_ends_antecedent(query_client, session_factory):
    sid = new_session(query_client)
    send(query_client, sid, "我题库里有多少道数学二的可练题？")
    send(query_client, sid, "那其中洛必达法则的题有多少道？")
    send(query_client, sid, "408题库有多少道可练题？")
    assert trace(session_factory, sid)["question_count"] == 1
    assert trace(session_factory, sid)["query_state"]["subject"] == "408"
    with session_factory.begin() as db:
        db.add(ChatMessage(session_id=sid, role="user", content="换个话题", status="completed"))
        db.add(ChatMessage(session_id=sid, role="assistant", content="现在讨论新的学习话题。", status="completed"))
    send(query_client, sid, "其中多少道是真题？")
    assert trace(session_factory, sid)["query_status"] == "needs_clarification"


def test_followup_executes_fresh_sql_not_previous_count(query_client, session_factory, query_fixture):
    from uuid import UUID
    sid = new_session(query_client)
    send(query_client, sid, "我题库里有多少道数学二的可练题？")
    with session_factory.begin() as db:
        db.get(Question, UUID(query_fixture["question_ids"][0])).is_hidden = True
    send(query_client, sid, "那其中洛必达法则的题有多少道？")
    assert trace(session_factory, sid)["question_count"] == 2


def test_refining_to_unrelated_node_does_not_escape_previous_scope(query_client, session_factory):
    sid = new_session(query_client)
    send(query_client, sid, "数学二题库有多少道可练题？")
    send(query_client, sid, "其中线性表的题有多少道？")
    assert trace(session_factory, sid)["query_status"] == "needs_clarification"


def test_corresponding_practice_uses_same_conversation_material_topic(query_client, session_factory):
    # Synthetic antecedent only for this free regression. The paid acceptance
    # separately reproduces the actual upload/RAG/query through Vue and SSE.
    sid = new_session(query_client)
    with session_factory.begin() as db:
        db.add(ChatMessage(session_id=sid, role="user", content="这份资料里洛必达法则在哪一部分？", status="completed"))
        db.add(ChatMessage(session_id=sid, role="assistant", content="资料第一、二节讲洛必达的条件和例题。", status="completed"))
    result = send(query_client, sid, "我的题库里有没有对应的练习题？")
    data = trace(session_factory, sid)
    assert data["query_status"] == "executed"
    assert data["question_count"] == 3
    assert data["scope_node_names"] == ["洛必达法则"]
    assert "没有可靠匹配" not in result["answer"]
