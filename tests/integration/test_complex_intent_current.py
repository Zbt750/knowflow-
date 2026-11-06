"""Current service/SSE regressions on the runner-owned disposable PostgreSQL.

No retained experience database and no model/network Provider is used. The
question fixtures are explicitly synthetic test exercises, never real exams.
"""
import json
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from tests.integration.test_learning_assistant import (
    session_factory, clean_database, conversations, NOW, talk, client, clock,
)
from tests.integration.test_learning_tasks import clean_tasks
from tests.integration.test_learning_loop import mark_isolated_question_trusted
from backend.models.chat import ChatSession, ChatMessage
from backend.models.learning import (
    KnowledgePoint, Question, QuestionVersion, DailyPlan, PracticeItem,
    QuestionAttempt, LearningEvent,
)
from backend.models.learning_task import LearningTask
from backend.models.personal_generation import PersonalGenerationBatch
from backend.models.practice_request import PracticeRequest
from backend.schemas.learning_assistant import AssistantRequest, StudyContext
from backend.schemas.learning_task import ConfirmTask
from backend.services.learning_task_service import confirm_task
from backend.services.practice_request_service import send_request, plan_request


class NoModelProvider:
    model = "OFFLINE - no model output"

    def complete(self, *a, **kw):
        raise AssertionError("this business path must not call a model")

    def tool_turn(self, *a, **kw):
        raise AssertionError("this business path must not call an Agent model")

    async def stream(self, *a, **kw):
        raise AssertionError("this business path must use actual lesson and business tools")
        yield ""


def qa_session(factory, *, purpose="qa"):
    with factory.begin() as db:
        row = ChatSession(mode="builtin", purpose=purpose,
            study_date=NOW.date().isoformat() if purpose == "study" else None,
            title="ISOLATED CURRENT COMPLEX INTENT TEST")
        db.add(row)
        db.flush()
        return row.id


def ask(factory, session_id, text):
    frames = talk(factory, session_id,
        AssistantRequest(question=text, study_context=StudyContext(surface="chat")),
        NoModelProvider())
    assert not any(event == "error" for event, _ in frames), frames
    assert frames[-1][0] == "done"
    return frames


def request_view(frames):
    return next(data for event, data in frames if event == "practice_request")


def private_details(factory, view):
    # Daily-plan candidates stay private until materialization. Retain the
    # original immutable-version and transactional assertions at the DB boundary.
    assert 'preview_draft' not in view['details']
    assert '"question_id"' not in json.dumps(view)
    with factory() as db:
        return db.get(PracticeRequest, UUID(view['id'])).request


def protected_rows(factory, *, include_requests=True):
    models = [Question, QuestionVersion, DailyPlan, PracticeItem, QuestionAttempt,
        LearningEvent, LearningTask, PersonalGenerationBatch]
    if include_requests:
        models.append(PracticeRequest)
    with factory() as db:
        return {model.__tablename__: sorted(
            json.dumps(dict(row), sort_keys=True, default=str, ensure_ascii=False)
            for row in db.execute(select(model.__table__)).mappings()) for model in models}


@pytest.fixture
def extra_lhopital_questions(session_factory):
    with session_factory.begin() as db:
        node = db.scalar(select(KnowledgePoint).where(
            KnowledgePoint.code == "math.calculus.limit.lhopital"))
        assert node is not None
        for index in range(3):
            question = Question(kp_id=node.id, question_type="single_choice",
                stem=f"[合成隔离测试题] 洛必达候选 {index}：求极限 $\\lim_{{x\\to0}}\\sin x/x$。",
                options={"A": "1", "B": "0"}, correct_answer="A",
                explanation="[合成测试解析] 分子分母求导后极限为1。",
                estimated_minutes=1, grading_mode="objective",
                grading_config={"verified": True, "method": "single_choice"})
            mark_isolated_question_trusted(question, db=db)
        return node.id


def test_compound_explanation_and_real_question_preview_keep_no_plan_side_effects(session_factory, extra_lhopital_questions, client, clock):
    clock.now = NOW
    sid = qa_session(session_factory)
    before = protected_rows(session_factory, include_requests=False)
    frames = ask(session_factory, sid,
        "洛必达法则是怎么样的，帮我从题库里面拿出一道放进今日卷。")
    view = request_view(frames)
    draft = private_details(session_factory, view)["preview_draft"]
    assert view["status"] == "draft" and len(draft["questions"]) == 1
    answer = next(data["answer"] for event, data in frames if event == "done")
    assert "系统节点讲解" in answer and "去心邻域" in answer and "今日卷尚未生成" in answer
    assert [step["tool"] for step in private_details(session_factory, view)["preview_trace"]] == [
        "read_lesson", "get_learning_state", "get_question_availability", "find_questions", "validate_plan"]
    selected = draft["questions"][0]
    with session_factory() as db:
        bound = db.get(QuestionVersion, UUID(selected["question_version"]))
        assert bound.question_id == UUID(selected["question_id"])
        assert bound.stem == selected["stem"] and bound.options == selected["options"]
        saved = db.scalar(select(ChatMessage).where(ChatMessage.session_id == sid,
            ChatMessage.role == 'assistant').order_by(ChatMessage.seq.desc()))
        replay_key = UUID(saved.metadata_['request_key'])
    replay = talk(session_factory, sid, AssistantRequest(
        question='洛必达法则是怎么样的，帮我从题库里面拿出一道放进今日卷。',
        study_context=StudyContext(surface='chat'), request_key=replay_key), NoModelProvider())
    replay_answer = next(data['answer'] for event, data in replay if event == 'done')
    assert '系统节点讲解' in replay_answer and '去心邻域' in replay_answer
    assert selected['stem'] not in replay_answer
    history = client.get(f'/api/chat/sessions/{sid}/messages')
    assert history.status_code == 200, history.text
    restored = history.json()[-1]['content']
    assert '系统节点讲解' in restored and '去心邻域' in restored
    assert selected['stem'] not in restored
    assert protected_rows(session_factory, include_requests=False) == before


def test_specific_preview_version_survives_formal_confirm_and_repeat(session_factory, extra_lhopital_questions):
    sid = qa_session(session_factory)
    frames = ask(session_factory, sid, "有没有洛必达法则的题目？")
    with session_factory() as db:
        message = db.scalar(select(ChatMessage).where(ChatMessage.session_id == sid,
            ChatMessage.role == "assistant").order_by(ChatMessage.seq.desc()))
        refs = message.metadata_["read_only_data_query"]["preview_questions"]
    assert len(refs) == 1
    before = protected_rows(session_factory, include_requests=False)
    view = request_view(ask(session_factory, sid, "把刚才那道题加入今日卷"))
    selected = private_details(session_factory, view)["preview_draft"]["questions"][0]
    assert (selected["question_id"], selected["question_version"]) == (
        refs[0]["question_id"], refs[0]["question_version"])
    assert protected_rows(session_factory, include_requests=False) == before
    study = qa_session(session_factory, purpose="study")
    rid = UUID(view["id"])
    send_request(session_factory, rid, source_conversation_id=sid, target_study_session_id=study, now=NOW)
    task = plan_request(session_factory, rid, study_session_id=study, provider=NoModelProvider(), now=NOW)["task"]
    result = confirm_task(session_factory, UUID(task["task_id"]), ConfirmTask(draft_version=task["draft_version"]), now=NOW)
    with session_factory() as db:
        items = list(db.scalars(select(PracticeItem)))
        assert len(items) == 1
        assert str(items[0].question_id) == selected["question_id"]
        assert str(items[0].question_version_id) == selected["question_version"]
    committed = protected_rows(session_factory)
    repeated = confirm_task(session_factory, UUID(task["task_id"]), ConfirmTask(draft_version=task["draft_version"]), now=NOW)
    assert repeated.append_result == result.append_result
    assert protected_rows(session_factory) == committed


def test_same_node_replacement_excludes_old_question_and_retires_preview(session_factory, extra_lhopital_questions):
    sid = qa_session(session_factory)
    first = request_view(ask(session_factory, sid, "先给我安排一道洛必达法则的待确认方案，不要生成今日卷。"))
    before = protected_rows(session_factory, include_requests=False)
    second = request_view(ask(session_factory, sid, "换一道同知识点的"))
    old = private_details(session_factory, first)["preview_draft"]["questions"][0]
    new = private_details(session_factory, second)["preview_draft"]["questions"][0]
    assert new["question_id"] != old["question_id"] and new["kp_id"] == old["kp_id"]
    assert new["question_type"] == old["question_type"]
    with session_factory() as db:
        assert db.get(PracticeRequest, UUID(first["id"])).status == "declined"
        assert db.get(PracticeRequest, UUID(second["id"])).status == "draft"
    assert protected_rows(session_factory, include_requests=False) == before


def test_cancel_and_replace_explicit_topic_uses_new_server_scope(session_factory, extra_lhopital_questions):
    with session_factory.begin() as db:
        old_node = KnowledgePoint(code="math.isolated.old.preview", name="隔离等比级数",
            subject="考研数学", is_assessable=True, is_active=True)
        db.add(old_node)
        db.flush()
        old_node_id = old_node.id
        question = Question(kp_id=old_node_id, question_type="single_choice",
            stem="[合成隔离测试题] 等比数列首项1、公比1/2，前两项和？",
            options={"A": "3/2", "B": "2"}, correct_answer="A", explanation="1+1/2=3/2。",
            estimated_minutes=1, grading_mode="objective",
            grading_config={"verified": True, "method": "single_choice"})
        mark_isolated_question_trusted(question, db=db)
    sid = qa_session(session_factory)
    first = request_view(ask(session_factory, sid, "先给我安排一道隔离等比级数题的待确认方案，不要生成今日卷。"))
    before = protected_rows(session_factory, include_requests=False)
    second = request_view(ask(session_factory, sid, "取消刚才的题，换一道洛必达的"))
    old = private_details(session_factory, first)["preview_draft"]["questions"][0]
    new = private_details(session_factory, second)["preview_draft"]["questions"][0]
    assert UUID(old["kp_id"]) == old_node_id
    assert UUID(new["kp_id"]) == extra_lhopital_questions
    assert new["question_id"] != old["question_id"]
    assert private_details(session_factory, second)["constraints"]["resolved_scope_node_ids"] == [str(extra_lhopital_questions)]
    assert str(old_node_id) not in private_details(session_factory, second)["constraints"]["resolved_scope_node_ids"]
    with session_factory() as db:
        assert db.get(PracticeRequest, UUID(first["id"])).status == "declined"
    assert protected_rows(session_factory, include_requests=False) == before


def test_read_only_bank_browse_after_preview_has_no_learning_side_effect(session_factory, extra_lhopital_questions):
    sid = qa_session(session_factory)
    request_view(ask(session_factory, sid, "先给我安排一道洛必达法则的待确认方案，不要生成今日卷。"))
    before = protected_rows(session_factory)
    frames = ask(session_factory, sid, "我只想看看题库里有哪些洛必达法则的题，不要创建计划。")
    assert not any(event in {"practice_request", "planner"} for event, _ in frames)
    with session_factory() as db:
        message = db.scalar(select(ChatMessage).where(ChatMessage.session_id == sid,
            ChatMessage.role == "assistant").order_by(ChatMessage.seq.desc()))
        evidence = message.metadata_["read_only_data_query"]
        assert evidence["query_status"] == "executed" and evidence["query_type"] == "find"
        assert evidence["scope_node_ids"] == [str(extra_lhopital_questions)]
        assert evidence["preview_questions"]
    assert protected_rows(session_factory) == before
