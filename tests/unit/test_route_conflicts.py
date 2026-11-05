"""R22: route_conflicts 诊断的自动化覆盖。"""

import uuid

from backend.schemas.learning_assistant import StudyContext
from backend.services.route_diagnostics import diagnose_route


def _ctx() -> StudyContext:
    return StudyContext(surface="chat")


def test_negation_is_recorded_and_blocks_write():
    result = diagnose_route("不要生成新题，只给我讲解。", _ctx())
    assert result["has_negation"] is True
    assert result["final_intent"].startswith("qa")
    assert result["write_risk"] is False


def test_compound_retrieve_then_append_reports_conflict_shape():
    result = diagnose_route("先检索，再加两道。", _ctx())
    assert result["final_intent"] == "data_query/find"
    assert result["candidates"], "应记录候选规则"
    assert result["conflicts"] is not None


def test_generated_question_append_is_planner_not_generation():
    result = diagnose_route("把刚才生成的题加入今日学习。", _ctx())
    assert result["final_intent"] == "planner/plan"
    assert result["final_rule"] == "generated_question_append_request"


def test_bank_only_query_stays_read_only():
    result = diagnose_route("我只想看看题库，不要创建计划。", _ctx())
    assert result["final_intent"] == "data_query/find"
    assert result["write_risk"] is False


def test_material_generation_is_write_and_needs_confirmation():
    result = diagnose_route("根据这份资料出五道题。", _ctx())
    assert result["final_intent"] == "generation/generate"
    assert result["needs_confirmation"] is True
