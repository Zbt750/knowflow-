from backend.services.personal_training_chat import parse_training_command
from backend.services.personal_generation_intent import _named_multi_targets
from types import SimpleNamespace
from uuid import uuid4


def test_explicit_training_commands_are_distinct_from_general_chat():
    assert parse_training_command("给我安排30分钟洛必达专项").action == "create"
    count = parse_training_command("给我安排五道隐函数练习")
    assert (count.action, count.count) == ("create", 5)
    recent = parse_training_command("根据最近错题创建一个专项")
    assert recent.action == "create" and recent.recent_mistakes
    assert parse_training_command("我现在有哪些专项").action == "list"
    assert parse_training_command("上次专项完成了吗").action == "status"
    assert parse_training_command("我在专项中做错了哪些题").action == "mistakes"
    recent_ai = parse_training_command("根据刚才做错的题生成三道变式题")
    assert recent_ai.action == "ai_create" and recent_ai.recent_mistakes and recent_ai.count == 3
    recent_rule = parse_training_command("我最近总是把隐函数求导做错，专项练习一下")
    assert recent_rule.action == "create" and recent_rule.recent_mistakes


def test_training_lifecycle_and_append_commands_route_to_independent_service():
    assert parse_training_command("给当前专项追加三道题").action == "append"
    append_ai = parse_training_command("给当前专项追加三道AI练习题")
    assert append_ai.action == "ai_append" and append_ai.count == 3
    assert parse_training_command("把当前专项难度提高").action == "increase_difficulty"
    assert parse_training_command("当前专项难度调高").action == "increase_difficulty"
    assert parse_training_command("暂停当前专项").action == "pause"
    assert parse_training_command("继续上次没做完的专项").action == "resume"
    assert parse_training_command("继续上次的专项").action == "resume"
    assert parse_training_command("结束专项，分析我这次的薄弱点").action == "finish"
    assert parse_training_command("生成三道洛必达法则单选练习题").action == "ai_create"


def test_compound_personal_training_generation_keeps_each_node_count_and_type():
    lhopital = SimpleNamespace(id=uuid4(), name="洛必达法则", code="TEST_FIXTURE.lhopital")
    implicit = SimpleNamespace(id=uuid4(), name="隐函数求导", code="TEST_FIXTURE.implicit")
    text = "给我生成三道洛必达法则单选题、两道隐函数求导填空题"
    command = parse_training_command(text)
    assert command is not None and command.action == "ai_create"
    targets = _named_multi_targets(text, [lhopital, implicit], "single_choice", "basic")
    assert targets is not None
    by_node = {target.kp_id: (target.count, target.question_type) for target in targets}
    assert by_node == {
        lhopital.id: (3, "single_choice"),
        implicit.id: (2, "fill_blank"),
    }


def test_chat_ai_request_uses_resolved_nodes_and_shared_generation_schema():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from backend.models.learning import KnowledgePoint
    from backend.services.personal_training_chat import _make_ai_request

    engine = create_engine("sqlite://")
    try:
        KnowledgePoint.__table__.create(engine)
        with Session(engine) as db:
            nodes = [KnowledgePoint(code=f"TEST_FIXTURE.chat-intent.{index}", name=name,
                subject="考研数学", is_active=True, is_assessable=True, is_reference_only=False)
                for index, name in enumerate(("洛必达法则", "隐函数求导"))]
            db.add_all(nodes); db.flush()
            text = "给我生成三道洛必达法则单选题、两道隐函数求导填空题"
            command = parse_training_command(text)
            request = _make_ai_request(db, text=text, owner_session_id=uuid4(), current=None,
                context=None, request_key=uuid4(), command=command)
            assert [(target.kp_id, target.count, target.question_type) for target in request.targets] == [
                (nodes[0].id, 3, "single_choice"),
                (nodes[1].id, 2, "fill_blank"),
            ]
            assert request.generation_mode == "ai_generated"
            assert request.append_to_today is False and request.plan_id is None
    finally:
        engine.dispose()


def test_ordinary_qa_and_nonexplicit_ambiguous_requests_are_not_intercepted():
    assert parse_training_command("什么是洛必达法则？") is None
    assert parse_training_command("这个有点难") is None
    assert parse_training_command("练习题应该怎么安排？") is None
    assert parse_training_command("这个题目的难度提高是什么意思？") is None
    assert parse_training_command("把知识点难度提高") is None
