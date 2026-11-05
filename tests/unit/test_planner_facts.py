from backend.services.planner_facts import (
    build_planner_factual_summary,
    render_pending_plan_recommendation,
    validate_planner_factual_summary,
)


def _attempt(attempt_id, question_id, result, assistance="none", assisted=False,
             reliability="ai_consistent_objective"):
    return {
        "attempt_id": attempt_id,
        "question_id": question_id,
        "result": result,
        "assistance_level": assistance,
        "assisted": assisted,
        "evidence_reliability": reliability,
    }


def test_factual_summary_preserves_observation_confirmation_and_plan_boundaries():
    nodes = ["node-408", "node-math", "node-matrix"]
    states = {
        "node-408": {
            "effective_confirmation_count": 0,
            "verified_objective_confirmation_count": 0,
            "recent_attempts": [
                _attempt("a1", "q1", "right"),
                _attempt("a2", "q2", "wrong"),
                _attempt("a3", "q2", "right", "hint_1", True),
            ],
        },
        "node-math": {
            "effective_confirmation_count": 0,
            "verified_objective_confirmation_count": 0,
            "recent_attempts": [_attempt("a4", "q3", "right", "solution", True)],
        },
        "node-matrix": {
            "effective_confirmation_count": 0,
            "verified_objective_confirmation_count": 0,
            "recent_attempts": [_attempt("a5", "q4", "wrong", "hint_1", True)],
        },
    }
    plan = {
        "plan_id": "plan-1",
        "knowledge_point_ids": nodes,
        "total_items": 6,
        "item_count": 6,
        "completed_count": 4,
        "pending_count": 2,
        "completed_question_ids": ["q1", "q2", "q3", "q4"],
        "unstarted_question_ids": ["q5", "q6"],
        "remaining_minutes": 8,
        "pending_items": [
            {"question_id": "q5", "knowledge_point_name": "矩阵相似", "estimated_minutes": 4},
            {"question_id": "q6", "knowledge_point_name": "矩阵相似", "estimated_minutes": 4},
        ],
    }
    inventory = {
        node: {
            "additional_eligible_count": 0,
            "additional_eligible_question_ids": [],
            "today_question_trust": [],
        }
        for node in nodes
    }
    inventory["node-408"]["today_question_trust"] = [
        {"question_id": f"q{i}", "answer_reliability": "ai_generated_consistent"}
        for i in range(1, 3)
    ]
    inventory["node-math"]["today_question_trust"] = [
        {"question_id": "q3", "answer_reliability": "ai_generated_consistent"}
    ]
    inventory["node-matrix"]["today_question_trust"] = [
        {"question_id": f"q{i}", "answer_reliability": "ai_generated_consistent"}
        for i in range(4, 7)
    ]

    summary = build_planner_factual_summary(
        current_plan=plan,
        state_by_node=states,
        inventory_by_node=inventory,
        state_read_ids=set(nodes),
        inventory_complete_ids=set(nodes),
    )

    assert summary["today_plan"]["total_items"] == 6
    assert summary["today_plan"]["completed_items"] == 4
    assert summary["today_plan"]["pending_items"] == 2
    assert summary["today_plan"]["remaining_minutes"] == 8
    assert summary["observations"]["unassisted_correct_observation_count"] == 1
    assert summary["observations"]["hint_assisted_correct_observation_count"] == 1
    assert summary["observations"]["solution_assisted_correct_observation_count"] == 1
    assert summary["observations"]["incorrect_observation_count"] == 2
    assert summary["observations"]["attempt_observation_count"] == 5
    assert summary["observations"]["distinct_questions_by_observation"]["incorrect"] == 2
    assert summary["evidence"]["effective_confirmation_count"] == 0
    assert summary["evidence"]["verified_objective_confirmation_count"] == 0
    assert summary["answer_reliability"]["counts"] == {"ai_generated_consistent": 6}
    assert summary["inventory"]["additional_eligible_count"] == 0
    assert summary["consistency"]["valid"] is True

    message = render_pending_plan_recommendation(summary)
    assert message is not None
    assert "共6题，已完成4题，还有2题待完成，预计还需约8分钟" in message
    assert "无辅助答对观察1次" in message
    assert "有效确认0次，其中已核验客观确认0次" in message
    assert "参考答案为AI一致性参考，尚未达到已核验答案的强证据条件" in message
    assert "提示或查看解析后答对只记录为辅助作答观察" in message
    assert "另有无辅助答对观察1次，但观察不等于强确认" in message
    assert "没有额外可追加的合格在线题（0道）" in message
    assert "q1" not in message and "q2" not in message


def test_summary_counts_repeated_attempts_as_observations_not_distinct_questions():
    states = {"n": {"effective_confirmation_count": 0,
        "verified_objective_confirmation_count": 0,
        "recent_attempts": [
            _attempt("wrong", "same-q", "wrong"),
            _attempt("right-after-hint", "same-q", "right", "hint_2", True),
        ]}}
    summary = build_planner_factual_summary(
        current_plan={"plan_id": "p", "knowledge_point_ids": ["n"],
            "total_items": 1, "completed_count": 0, "pending_count": 1,
            "completed_question_ids": [], "unstarted_question_ids": ["same-q"],
            "pending_items": [{"question_id": "same-q", "knowledge_point_name": "树", "estimated_minutes": 3}],
            "remaining_minutes": 3},
        state_by_node=states,
        inventory_by_node={"n": {"additional_eligible_count": 0,
            "additional_eligible_question_ids": [], "today_question_trust": []}},
        state_read_ids={"n"}, inventory_complete_ids={"n"})
    assert summary["observations"]["attempt_observation_count"] == 2
    assert summary["observations"]["distinct_questions_by_observation"]["incorrect"] == 1
    assert summary["observations"]["distinct_questions_by_observation"]["hint_assisted_correct"] == 1
    assert summary["observations"]["incorrect_observation_count"] == 1
    assert summary["observations"]["hint_assisted_correct_observation_count"] == 1


def test_summary_needs_complete_state_and_inventory_and_rejects_inconsistent_counts():
    incomplete = build_planner_factual_summary(
        current_plan={"plan_id": "p", "knowledge_point_ids": ["n1", "n2"],
            "total_items": 2, "completed_count": 1, "pending_count": 1,
            "completed_question_ids": ["q1"], "unstarted_question_ids": ["q2"],
            "pending_items": [{"question_id": "q2"}], "remaining_minutes": 5},
        state_by_node={"n1": {"recent_attempts": []}},
        inventory_by_node={"n1": {"additional_eligible_count": 0}},
        state_read_ids={"n1"}, inventory_complete_ids={"n1"})
    assert not incomplete["coverage"]["learning_state_complete"]
    assert not incomplete["coverage"]["inventory_complete"]
    assert incomplete["evidence"]["effective_confirmation_count"] is None
    assert render_pending_plan_recommendation(incomplete) is None

    inconsistent = {
        "today_plan": {"total_items": 6, "completed_items": 4, "pending_items": 1,
            "completed_question_ids": ["q"], "pending_question_ids": ["q"],
            "pending_item_details": [{"question_id": "q"}]},
        "inventory": {"additional_eligible_count": 0, "additional_eligible_question_ids": ["other"]},
    }
    assert set(validate_planner_factual_summary(inconsistent)) == {
        "plan_item_counts_do_not_sum", "question_both_completed_and_pending",
        "zero_inventory_has_question_ids", "inventory_count_below_returned_ids"}
