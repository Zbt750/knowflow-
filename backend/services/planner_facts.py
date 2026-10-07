"""Deterministic facts used to ground learning-task recommendations."""
from __future__ import annotations

from collections import Counter
from typing import Any


_RELIABILITY_LABELS = {
    "verified_objective": "已核验客观答案",
    "ai_generated_consistent": "AI一致性参考答案",
    "ai_consistent_objective": "AI一致性参考答案",
    "model_generated": "模型生成参考答案",
    "unknown": "信任状态未明确",
}


def _attempt_identity(attempt: dict[str, Any]) -> tuple[Any, ...]:
    attempt_id = attempt.get("attempt_id")
    if attempt_id:
        return ("id", str(attempt_id))
    return ("legacy", attempt.get("kp_id"), attempt.get("question_id"),
            attempt.get("submitted_at"), attempt.get("attempt_number"),
            attempt.get("result"), attempt.get("assistance_level"))


def build_planner_factual_summary(
    *,
    current_plan: dict[str, Any],
    state_by_node: dict[str, dict[str, Any]],
    inventory_by_node: dict[str, dict[str, Any]],
    state_read_ids: set[str],
    inventory_complete_ids: set[str],
) -> dict[str, Any]:
    """Aggregate observable attempt facts and server-owned plan/inventory counts.

    Attempt categories count observations, not distinct questions. Distinct question
    counts are also included so a correction sequence cannot inflate question totals.
    """
    plan_node_ids = {str(value) for value in current_plan.get("knowledge_point_ids", [])}
    plan_nodes = sorted(plan_node_ids)
    state_covered = bool(plan_nodes) and plan_node_ids.issubset(state_read_ids)
    inventory_covered = bool(plan_nodes) and plan_node_ids.issubset(inventory_complete_ids)

    attempts_by_identity: dict[tuple[Any, ...], dict[str, Any]] = {}
    effective_confirmations = 0
    verified_objective_confirmations = 0
    for node_id in plan_nodes:
        state = state_by_node.get(node_id)
        if state is None:
            continue
        effective_confirmations += int(state.get("effective_confirmation_count", 0) or 0)
        verified_objective_confirmations += int(state.get("verified_objective_confirmation_count", 0) or 0)
        for attempt in state.get("recent_attempts", []):
            attempts_by_identity.setdefault(_attempt_identity({**attempt, "kp_id": node_id}), attempt)

    observation_counts = Counter()
    observation_questions: dict[str, set[str]] = {
        key: set() for key in ("unassisted_correct", "hint_assisted_correct",
                               "solution_assisted_correct", "process_review_assisted_correct",
                               "incorrect", "other_correct", "ungraded")
    }
    for attempt in attempts_by_identity.values():
        result = attempt.get("result")
        assistance = attempt.get("assistance_level")
        assisted = attempt.get("assisted")
        if result == "wrong":
            category = "incorrect"
        elif result == "right" and assistance in {"hint_1", "hint_2"}:
            category = "hint_assisted_correct"
        elif result == "right" and assistance == "solution":
            category = "solution_assisted_correct"
        elif result == "right" and assistance == "process_review":
            category = "process_review_assisted_correct"
        elif result == "right" and assisted is False and assistance in {None, "none"}:
            category = "unassisted_correct"
        elif result == "right":
            category = "other_correct"
        else:
            category = "ungraded"
        observation_counts[category] += 1
        question_id = attempt.get("question_id")
        if question_id:
            observation_questions[category].add(str(question_id))

    total_items = current_plan.get("total_items", current_plan.get("item_count"))
    completed_items = current_plan.get("completed_count", 0)
    pending_items_count = current_plan.get("pending_count", current_plan.get("unstarted_count", 0))
    pending_items = list(current_plan.get("pending_items", []))

    additional_count: int | None = None
    additional_ids: set[str] = set()
    if inventory_covered:
        per_node_counts = []
        for node_id in plan_nodes:
            row = inventory_by_node.get(node_id)
            if row is None or row.get("additional_eligible_count") is None:
                per_node_counts = []
                break
            per_node_counts.append(int(row["additional_eligible_count"]))
            additional_ids.update(str(value) for value in row.get("additional_eligible_question_ids", []))
        if len(per_node_counts) == len(plan_nodes):
            additional_count = sum(per_node_counts)

    plan_question_ids = set(str(value) for value in current_plan.get("completed_question_ids", []))
    plan_question_ids.update(str(value) for value in current_plan.get("unstarted_question_ids", []))
    reliability_counts = Counter()
    observed_plan_question_ids: set[str] = set()
    for node_id in plan_nodes:
        row = inventory_by_node.get(node_id) or {}
        for question in row.get("today_question_trust", []):
            question_id = str(question.get("question_id"))
            if question_id in plan_question_ids and question_id not in observed_plan_question_ids:
                observed_plan_question_ids.add(question_id)
                reliability_counts[str(question.get("answer_reliability") or "unknown")] += 1

    summary = {
        "version": "planner-factual-summary-v1",
        "coverage": {
            "plan_node_ids": plan_nodes,
            "learning_state_complete": state_covered,
            "inventory_complete": inventory_covered,
        },
        "today_plan": {
            "plan_id": current_plan.get("plan_id"),
            "total_items": total_items,
            "completed_items": completed_items,
            "pending_items": pending_items_count,
            "remaining_minutes": current_plan.get("remaining_minutes"),
            "completed_question_ids": sorted(set(current_plan.get("completed_question_ids", []))),
            "pending_question_ids": sorted(set(current_plan.get("unstarted_question_ids", []))),
            "pending_item_details": pending_items,
        },
        "observations": {
            "attempt_observation_count": len(attempts_by_identity),
            "unassisted_correct_observation_count": observation_counts["unassisted_correct"],
            "hint_assisted_correct_observation_count": observation_counts["hint_assisted_correct"],
            "solution_assisted_correct_observation_count": observation_counts["solution_assisted_correct"],
            "process_review_assisted_correct_observation_count": observation_counts["process_review_assisted_correct"],
            "incorrect_observation_count": observation_counts["incorrect"],
            "other_correct_observation_count": observation_counts["other_correct"],
            "ungraded_observation_count": observation_counts["ungraded"],
            "distinct_questions_by_observation": {key: len(value) for key, value in observation_questions.items()},
            "observation_window_note": "Counts cover the recent attempts returned by the state tool; attempts are observations and may refer to the same question.",
        },
        "evidence": {
            "effective_confirmation_count": effective_confirmations if state_covered else None,
            "verified_objective_confirmation_count": verified_objective_confirmations if state_covered else None,
        },
        "answer_reliability": {
            "current_plan_question_count_observed": len(observed_plan_question_ids),
            "counts": dict(sorted(reliability_counts.items())),
            "labels": {key: _RELIABILITY_LABELS.get(key, key) for key in reliability_counts},
        },
        "inventory": {
            "additional_eligible_count": additional_count,
            "additional_eligible_question_ids": sorted(additional_ids),
            "meaning": "Zero additional questions means no eligible questions outside the current plan in this fully checked scope; it does not mean the plan has no pending items.",
        },
    }
    errors = validate_planner_factual_summary(summary)
    summary["consistency"] = {"valid": not errors, "errors": errors}
    return summary


def validate_planner_factual_summary(summary: dict[str, Any]) -> list[str]:
    """Check internal count, status, and inventory invariants without reading prose."""
    errors: list[str] = []
    plan = summary.get("today_plan") or {}
    total = plan.get("total_items")
    completed = plan.get("completed_items")
    pending = plan.get("pending_items")
    if all(type(value) is int for value in (total, completed, pending)) and completed + pending != total:
        errors.append("plan_item_counts_do_not_sum")
    completed_ids = set(plan.get("completed_question_ids") or [])
    pending_ids = set(plan.get("pending_question_ids") or [])
    if completed_ids & pending_ids:
        errors.append("question_both_completed_and_pending")
    details = plan.get("pending_item_details")
    if isinstance(pending, int) and isinstance(details, list) and len(details) != pending:
        errors.append("pending_item_details_count_mismatch")
    inventory = summary.get("inventory") or {}
    additional_count = inventory.get("additional_eligible_count")
    additional_ids = inventory.get("additional_eligible_question_ids") or []
    if additional_count == 0 and additional_ids:
        errors.append("zero_inventory_has_question_ids")
    if isinstance(additional_count, int) and additional_count < len(additional_ids):
        errors.append("inventory_count_below_returned_ids")
    return errors


def render_pending_plan_recommendation(summary: dict[str, Any]) -> str | None:
    """Safely answer a replan when the current plan has work but no new inventory."""
    if summary.get("consistency", {}).get("valid") is not True:
        return None
    coverage = summary.get("coverage") or {}
    inventory = summary.get("inventory") or {}
    plan = summary.get("today_plan") or {}
    if (not summary.get("version") == "planner-factual-summary-v1"
            or not coverage.get("learning_state_complete")
            or not coverage.get("inventory_complete")
            or inventory.get("additional_eligible_count") != 0
            or not isinstance(plan.get("pending_items"), int)
            or plan["pending_items"] <= 0):
        return None

    lines: list[str] = []
    total, completed, pending = plan.get("total_items"), plan.get("completed_items"), plan.get("pending_items")
    remaining = plan.get("remaining_minutes")
    if all(type(value) is int for value in (total, completed, pending)):
        time_text = f"，预计还需约{remaining}分钟" if type(remaining) is int else ""
        lines.append(f"今天的练习卷共{total}题，已完成{completed}题，还有{pending}题待完成{time_text}。")

    details = plan.get("pending_item_details") or []
    grouped: dict[str, dict[str, Any]] = {}
    for item in details:
        label = str(item.get("knowledge_point_name") or "今日卷剩余题目")
        group = grouped.setdefault(label, {"count": 0, "minutes": 0, "minutes_known": True})
        group["count"] += 1
        minutes = item.get("estimated_minutes")
        if type(minutes) is int:
            group["minutes"] += max(0, minutes)
        else:
            group["minutes_known"] = False
    if grouped:
        parts = []
        for label, item in grouped.items():
            suffix = f"（约{item['minutes']}分钟）" if item["minutes_known"] else ""
            parts.append(f"{label}{item['count']}题{suffix}")
        lines.append("建议先完成今日卷剩余内容：" + "、".join(parts) + "。")

    observations = summary.get("observations") or {}
    observation_labels = (
        ("unassisted_correct_observation_count", "无辅助答对观察"),
        ("hint_assisted_correct_observation_count", "提示后答对观察"),
        ("solution_assisted_correct_observation_count", "查看解析后答对观察"),
        ("incorrect_observation_count", "按参考答案比对为错误的观察"),
    )
    observed = [f"{label}{observations.get(key, 0)}次" for key, label in observation_labels if observations.get(key, 0)]
    if observed:
        lines.append("最近可见作答记录：" + "、".join(observed) + "。这些是作答观察；多次记录可能来自同一道题。")

    evidence = summary.get("evidence") or {}
    effective = evidence.get("effective_confirmation_count")
    verified = evidence.get("verified_objective_confirmation_count")
    reliability = summary.get("answer_reliability") or {}
    trust_counts = reliability.get("counts") or {}
    trust_labels = reliability.get("labels") or {}
    if trust_counts:
        trust_text = "、".join(f"{trust_labels.get(key, key)}{count}道" for key, count in trust_counts.items())
        lines.append(f"今日卷题目答案信任分布：{trust_text}。")
    if type(effective) is int and type(verified) is int:
        explanation = []
        if trust_counts.get("ai_generated_consistent", 0) or trust_counts.get("ai_consistent_objective", 0):
            explanation.append("题库参考答案为AI一致性参考，尚未达到已核验答案的强证据条件")
        if (observations.get("hint_assisted_correct_observation_count", 0)
                or observations.get("solution_assisted_correct_observation_count", 0)):
            explanation.append("提示或查看解析后答对只记录为辅助作答观察")
        if observations.get("unassisted_correct_observation_count", 0):
            explanation.append(
                f"另有无辅助答对观察{observations['unassisted_correct_observation_count']}次，"
                "但观察不等于强确认"
            )
        reason = "；".join(explanation) or "现有作答尚未满足强证据条件"
        lines.append(
            f"当前范围有效确认{effective}次，其中已核验客观确认{verified}次；{reason}，"
            "因此不能据此判定已掌握。"
        )

    lines.append("今日卷涉及范围内没有额外可追加的合格在线题（0道）；这是新增题库存为空，当前卷仍有待完成题目。建议先完成上面列出的题，再根据新的作答记录调整。")
    return "".join(lines)
