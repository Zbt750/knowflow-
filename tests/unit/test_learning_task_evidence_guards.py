from types import SimpleNamespace
from copy import deepcopy
import json

import pytest

from backend.errors import AppError
from backend.services.learning_task_service import (
    _grounded_source_correction,
    _missing_plan_message,
    _model_turn,
    _source_claim_conflicts,
    _validated_plan_summary,
    _finalization_messages,
)


def source_trace(*categories):
    return [{
        "tool": "find_questions",
        "status": "completed",
        "result": {"questions": [
            {"kp_name": "定积分的计算", "source_category": category}
            for category in categories
        ]},
    }]


def test_source_claim_is_rejected_when_tool_evidence_contains_exam_item():
    trace = source_trace("development_original", "exam_curated", "unclassified_public")
    model_text = "该节点没有正式历年真题，可练习题目全部由AI生成。"
    assert _source_claim_conflicts(model_text, trace)
    grounded = _grounded_source_correction(trace)
    assert "整理真题 1 道" in grounded
    assert "开发原创 1 道" in grounded
    assert "不是全库总量" in grounded
    assert "没有正式历年真题" not in grounded


def test_source_claim_is_not_conflict_when_evidence_supports_observed_ai_only_sample():
    assert not _source_claim_conflicts("返回样本均为AI生成。", source_trace("development_original"))


def test_unknown_source_does_not_support_an_all_ai_claim():
    assert _source_claim_conflicts("返回的题目全部由AI生成。", source_trace("unclassified_public"))


def test_plan_budget_error_is_reported_as_a_hard_limit_not_success():
    trace = [{"tool": "validate_plan", "status": "error",
        "result": {"valid": False, "errors": ["time_budget_exceeded"]}}]
    message = _missing_plan_message(trace, budget_minutes=20)
    assert "超过20分钟上限" in message
    assert "没有写入今日学习" in message


def test_validated_draft_summary_uses_server_counts_and_confirmation_boundary():
    summary = _validated_plan_summary({
        "questions": [
            {"kp_name": "定积分", "question_type": "single_choice"},
            {"kp_name": "定积分", "question_type": "fill_blank"},
        ],
        "total_minutes": 18,
        "budget_minutes": 20,
        "review_nodes": [],
    })
    assert "定积分1道选择题" in summary and "定积分1道填空题" in summary
    assert "共2道不同在线题" in summary and "预计18分钟，不超过20分钟预算" in summary
    assert "只有你确认后才会创建或追加今日试卷" in summary
    assert _validated_plan_summary({"questions": [], "total_minutes": 21, "budget_minutes": 20}) == ""


def test_evaluation_meter_stop_is_not_reported_as_a_provider_failure():
    from scripts.phase5_eval_meter import BudgetStop

    class StoppedProvider:
        model = "deepseek-flash"

        def tool_turn(self, *_args, **_kwargs):
            raise BudgetStop("evaluation_budget_stop")

    calls = []
    with pytest.raises(AppError) as exc:
        _model_turn(StoppedProvider(), [], calls, turn=3, timeout=1)
    assert exc.value.code == "generation_failed"
    assert exc.value.detail == "provider_request_state_unknown"
    assert calls[0]["error_code"] == "provider_request_state_unknown"
    assert calls[0]['physical_request_attempts'] is None
    assert calls[0]["usage_observed"] is False
    assert calls[0]["retryable"] is False


def test_finalizer_bounds_large_chinese_history_without_losing_inventory_counts():
    long_note = "隔离验收中的较长中文学习记录" * 35
    states = [{
        "kp_id": f"node-{i}", "state": "unseen", "self_report_available": False,
        "effective_confirmation_count": 0,
        "learning_progress": {"observed_attempt_count": 40, "reason": long_note},
        "recent_attempts": [{"question_id": f"q-{i}-{j}", "raw_answer": long_note,
            "grading_evidence": {"reference_answer": long_note, "notice": long_note}}
            for j in range(16)],
    } for i in range(8)]
    trace = [
        {"tool": "get_learning_state", "status": "completed", "result": {"states": states}},
        {"tool": "get_question_availability", "status": "completed", "result": {
            "practice_eligible_count": 123, "available_to_append_count": 27,
            "eligible_nodes": [{"kp_id": f"node-{i}", "name": long_note} for i in range(8)]}},
        {"tool": "find_questions", "status": "completed", "result": {
            "questions": [{"question_id": "candidate-1", "kp_name": "洛必达法则", "minutes": 5}]}},
        {"tool": "list_review_needs", "status": "completed", "result": {"nodes": [
            {"kp_id": f"node-{i}", "note": long_note, "attempts": states[i]["recent_attempts"]}
            for i in range(8)]}},
    ]
    original = deepcopy(trace)
    facts = {"today_plan": {"completed_items": 4, "pending_items": 2},
        "evidence": {"effective_confirmation_count": 0},
        "observations": {"unassisted_correct_observation_count": 1}}
    messages = _finalization_messages("依据记录给出90分钟建议，不创建计划", 90, "recommend", trace, None,
        planner_factual_summary=facts)

    class Finalizer:
        model = "fixed-no-network"

        def tool_turn(self, request_messages, tools, *, timeout):
            assert not tools
            payload = json.loads(request_messages[-1]["content"])
            assert len(request_messages[-1]["content"].encode("utf-8")) <= 24000
            assert payload["evidence"]["_preview"]["is_partial"] is True
            assert payload["evidence"]["_preview"]["source_record_counts"]["learning_states"] == 8
            inventory = payload["evidence"]["inventories"][0]
            assert inventory["practice_eligible_count"] == 123
            assert inventory["available_to_append_count"] == 27
            assert payload["AUTHORITATIVE_PLANNER_FACTUAL_SUMMARY"] == facts
            assert payload["write_permission"] is False
            return {"message": {"content": '{"message":"依据已展示证据给出有限建议。","needs_clarification":false}'}}

    calls = []
    _model_turn(Finalizer(), messages, calls, turn=3, timeout=1,
        allow_tools=False, intent="recommend", compact_messages_enabled=False)
    assert len(calls) == 1
    assert trace == original, "model-facing preview must not truncate persisted audit evidence"
