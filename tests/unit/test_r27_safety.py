from unittest.mock import Mock
from types import SimpleNamespace
from uuid import UUID
import pytest
from backend.schemas.learning_assistant import StudyContext
from backend.services.assistant_router import route_message
from tests.fixtures.naiwa_factory import NaiwaFactory

@pytest.mark.parametrize("personal,expected",[(False,"trusted_practice"),(True,"ai_generated_practice")])
def test_factory_default_provenance_matches_real_schema(personal,expected):
    f=NaiwaFactory(Mock(),UUID(int=27));kp=SimpleNamespace(id=UUID(int=1))
    q=(f.create_test_personal_question(kp) if personal else f.create_test_question(kp))
    assert q.question_provenance==expected
    assert isinstance(q.options,dict) and q.options[q.correct_answer]=="2"
    assert q.content_trust=="unreviewed" and q.answer_reliability=="unknown"

@pytest.mark.parametrize("message",[
    "根据这份资料不要生成题，只解释。",
    "根据这份笔记先不要出题，帮我总结。",
])
def test_negated_material_generation_cannot_enter_generation(message):
    route=route_message(message,StudyContext(surface="chat"))
    assert route.capability=="qa"
    assert not route.write_risk

@pytest.mark.parametrize("message",[
    "不要把刚才生成的题加入今日学习。",
    "先不把刚才生成的题放进今日卷。",
])
def test_negated_generated_append_cannot_enter_planner(message):
    route=route_message(message,StudyContext(surface="chat"))
    assert route.capability=="qa"
    assert not route.write_risk


@pytest.mark.parametrize("message",["可以把刚才生成的题加入今日学习吗？","要不要把刚才生成的题加入今日学习？"])
def test_permission_question_is_not_append_consent(message):
    route=route_message(message,StudyContext(surface="chat"))
    assert route.capability=="qa" and not route.write_risk

@pytest.mark.parametrize("change",["raw_answer","selected_option","confidence","expected_previous_attempt_id"])
def test_same_key_changed_payload_rejected_before_mutating(monkeypatch,change):
    from backend.services import answer_submission_service as service
    from tests.fixtures.naiwa_factory import NOW
    item_id=UUID(int=27)
    monkeypatch.setattr(service,"lock_practice_item",lambda db,item_id: SimpleNamespace(id=item_id))
    old=SimpleNamespace(practice_item_id=item_id,raw_answer="B",grading_evidence={
        "selected_option":"B","confidence":None,"expected_previous_attempt_id":None})
    db=Mock();db.scalar.return_value=old
    args=dict(item_id=item_id,raw_answer="B",selected_option="B",idempotency_key="r27-key",now=NOW)
    args[change]=UUID(int=1) if change=="expected_previous_attempt_id" else "changed"
    with pytest.raises(ValueError,match="idempotency_key_conflict"):
        service.submit_answer(db,**args)
    db.add.assert_not_called();db.commit.assert_not_called()


def test_same_key_same_payload_replays_without_new_write(monkeypatch):
    from backend.services import answer_submission_service as service
    from tests.fixtures.naiwa_factory import NOW
    item_id=UUID(int=27)
    monkeypatch.setattr(service,"lock_practice_item",lambda db,item_id: SimpleNamespace(id=item_id))
    old=SimpleNamespace(practice_item_id=item_id,raw_answer="B",grading_evidence={
        "selected_option":"B","confidence":None,"expected_previous_attempt_id":None})
    response=object();monkeypatch.setattr(service,"submission_response",lambda attempt:response)
    db=Mock();db.scalar.return_value=old
    assert service.submit_answer(db,item_id=item_id,raw_answer=" B ",selected_option="B",
        idempotency_key="r27-key",now=NOW) is response
    db.add.assert_not_called();db.commit.assert_not_called()


@pytest.mark.parametrize("case",["locked","wrong_cluster","wrong_schema","ready"])
def test_full_runner_checks_identity_and_instance_lock_before_test_spawn(monkeypatch,case):
    import psycopg
    import scripts.r25_full_pytest as runner
    from pathlib import Path
    cursor=Mock();cursor.__enter__=Mock(return_value=cursor);cursor.__exit__=Mock(return_value=False)
    conn=Mock();conn.__enter__=Mock(return_value=conn);conn.__exit__=Mock(return_value=False)
    conn.cursor.return_value=cursor
    identifier="different" if case=="wrong_cluster" else "7703578443208394676"
    cursor.fetchone.side_effect=[("naiwa_experience_test",63047,"kaoyan_app",
        str(Path(runner.PROJECT)/"tmp/pg63047"),identifier),(case!="locked",),(True,)]
    cursor.fetchall.return_value=[("wrong" if case=="wrong_schema" else "f58d22ab41c7",)]
    monkeypatch.setattr(psycopg,"connect",Mock(return_value=conn))
    spawn=Mock();monkeypatch.setattr(runner.subprocess,"run",spawn)
    if case=="ready":
        result=runner.verify_identity();assert result["port"]==63047
        assert cursor.execute.call_args.args[0]=="select pg_advisory_unlock(75020260927)"
    else:
        with pytest.raises(RuntimeError):runner.verify_identity()
    spawn.assert_not_called()


def test_explicit_timed_preview_keeps_denied_insert_permission():
    route=route_message("我只有60分钟，想复习洛必达，先给我看看安排，不要直接加入今日卷。",StudyContext(surface="study"))
    assert (route.capability,route.intent)==("planner","plan")
    assert route.write_risk is False


@pytest.mark.parametrize("text",[
    "不要把刚才生成的题加入今日学习。", "可以把刚才生成的题加入今日学习吗？",
    "要不要加入这道题？", "我考虑一下是否加入今日学习。", "先看看，不要加入今日卷。",
    "如果可以就加入今日学习。", "生成一道让我看看。",
    "暂时不加入今日学习。", "我还不想加入这道题。", "明天再加入今日学习。",
])
def test_business_confirmation_does_not_convert_mentions_into_consent(text):
    from backend.services.learning_assistant_service import _explicit_append_consent, _bank_confirmation_kind
    assert _explicit_append_consent(text) is False
    assert _bank_confirmation_kind(text) is None

@pytest.mark.parametrize("text",["把刚才生成的题加入今日学习。","将前两道相似题添加进今日学习。","生成一道并加入今日学习。"])
def test_explicit_append_consent_remains_supported(text):
    from backend.services.learning_assistant_service import _explicit_append_consent
    assert _explicit_append_consent(text) is True


def test_preview_still_checks_frozen_paper_before_builder(monkeypatch):
    from backend.services.practice_request_service import draft_request
    from backend.services import learning_assistant_service as assistant
    from tests.fixtures.naiwa_factory import NOW
    db=Mock();db.scalar.side_effect=[SimpleNamespace(id=UUID(int=1)),UUID(int=2)]
    context=Mock();context.__enter__=Mock(return_value=db);context.__exit__=Mock(return_value=False)
    builder=Mock(side_effect=AssertionError("frozen plan must not reach planning"))
    monkeypatch.setattr(assistant,"planner_handoff",builder)
    result=draft_request(lambda:context,ctx=SimpleNamespace(),user_id=UUID(int=3),
        assistant_id=UUID(int=4),message="再加入一道题",now=NOW)
    assert result["frozen"] is True
    builder.assert_not_called()
