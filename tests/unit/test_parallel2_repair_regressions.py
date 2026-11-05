"""Deterministic regressions for the 2026-10-25 independent UI findings."""
import pytest
from uuid import UUID

from backend.schemas.learning_assistant import StudyContext
from backend.services.assistant_router import route_message
from backend.services.assistant_data_queries import _uuid_list
from backend.services.learner_self_report import extract_self_reports


@pytest.mark.parametrize("message", [
    "我独立答对了几道题？辅助作答的有几道？答错了几道？",
    "请统计我最近的学习情况，先看全局，再单独看洛必达法则。",
])
def test_attempt_statistics_route_to_learning_evidence_not_inventory(message):
    route = route_message(message, StudyContext(surface="study"))
    assert (route.capability, route.intent) == ("data_query", "learning_state")


def test_today_summary_and_tomorrow_suggestion_are_read_only_and_no_default_budget():
    route = route_message("我今天学得怎么样？明天该怎么安排？", StudyContext(surface="study"))
    assert (route.capability, route.intent, route.reason) == (
        "data_query", "today_summary", "today_learning_and_next_step")
    assert route_message("今天学习总结", StudyContext(surface="study")).intent == "today_summary"


def test_short_correct_answer_count_is_not_misrouted_to_inventory():
    route = route_message("我最近答对了几道题？", StudyContext(surface="study"))
    assert (route.capability, route.intent, route.reason) == (
        "data_query", "learning_state", "attempt_statistics")


def test_unconfirmed_plan_budget_change_refines_the_existing_draft():
    task = {"status": "ready", "committed": False, "budget_minutes": 90}
    route = route_message("我现在只剩25分钟了，保留最重要的部分，其他内容推迟。",
        StudyContext(surface="study", task_id=UUID("30000000-0000-0000-0000-000000000003")), task=task)
    assert (route.capability, route.intent, route.reason, route.write_risk) == (
        "planner", "plan", "active_draft_refinement", False)


@pytest.mark.parametrize("message", [
    "根据最近错题给我90分钟数学二整体复习建议，不创建计划",
    "围绕当前题目给我复习建议",
    "今天只有60分钟，给我数学二复习建议，先不创建计划",
])
def test_explicit_no_plan_request_is_read_only_recommendation(message):
    route = route_message(message, StudyContext(surface="study"))
    assert (route.capability, route.intent, route.write_risk) == ("planner", "recommend", False)


def test_student_correction_requests_objective_evidence_and_is_saved_as_unverified_self_report():
    text = "你刚才说我极限最差，但我最近极限连续答对了，真正容易错的是积分换元。请根据记录重新判断。"
    route = route_message(text, StudyContext(surface="study"))
    assert (route.capability, route.intent, route.reason) == (
        "data_query", "evidence_basis", "learning_evidence_attribution")
    claims = extract_self_reports(text)
    assert claims == [{
        "topic": "积分换元", "assessment": "needs_help",
        "statement": "真正容易错的是积分换元", "source": "self_report",
        "independently_verified": False,
    }]


def test_add_recent_wrong_item_routes_to_exact_wrong_item_lookup_before_planning():
    route = route_message("把刚才那道错题加入今天的学习。", StudyContext(surface="study"))
    assert (route.capability, route.intent, route.reason) == (
        "data_query", "recent_wrong_item", "add_recent_wrong_item_needs_context")
    bound = StudyContext(surface="study", attempt_id=UUID("10000000-0000-0000-0000-000000000001"),
        practice_item_id=UUID("20000000-0000-0000-0000-000000000002"))
    contextual = route_message("把刚才那道错题加入今天的学习。", bound)
    assert (contextual.capability, contextual.intent, contextual.reason) == (
        "planner", "plan", "add_recent_wrong_item")


@pytest.mark.parametrize("message", [
    "今天只有60分钟了，先帮我复习数学二积分，再安排几道练习题。",
    "我今天只有60分钟，先复习数学二积分，再安排一些练习。",
])
def test_scoped_question_request_keeps_scope_and_uses_question_planning_path(message):
    route = route_message(message, StudyContext(surface="study"))
    assert (route.capability, route.intent) == ("planner", "plan")
    assert route.reason in {"learning_task_request", "explicit_bank_selection"}


def test_scoped_question_plan_is_not_downgraded_to_activity_only_schedule():
    text = "我今天只有60分钟，先帮我复习数学二积分，再安排几道练习题。"
    route = route_message(text, StudyContext(surface="study"))
    assert (route.capability, route.intent, route.reason) == (
        "planner", "plan", "learning_task_request")


def test_unknown_unnamed_knowledge_scope_asks_for_clarification_not_a_lesson_sample():
    route = route_message("帮我复习一个题库里没有的知识点。", StudyContext(surface="study"))
    assert (route.capability, route.intent, route.reason) == (
        "data_query", "scope_clarification", "unresolved_knowledge_scope")


def test_unknown_knowledge_point_request_is_read_only_scope_clarification():
    route = route_message("帮我复习一个题库里没有的知识点。", StudyContext(surface="study"))
    assert (route.capability, route.intent, route.reason) == (
        "data_query", "scope_clarification", "unresolved_knowledge_scope")


def test_today_summary_and_wrong_item_addition_do_not_fall_into_plan_or_inventory():
    today = route_message("我今天学得怎么样？明天该怎么安排？", StudyContext(surface="study"))
    wrong = route_message("把刚才那道错题加入今天的学习。", StudyContext(surface="study"))
    assert (today.capability, today.intent, today.reason) == (
        "data_query", "today_summary", "today_learning_and_next_step")
    assert (wrong.capability, wrong.intent, wrong.reason) == (
        "data_query", "recent_wrong_item", "add_recent_wrong_item_needs_context")


def test_composite_global_and_named_topic_statistics_route_to_scoped_query():
    route = route_message(
        "我全库的正确率，和洛必达这个知识点的正确率分别是多少？",
        StudyContext(surface="study"))
    assert (route.capability, route.intent, route.reason) == (
        "data_query", "learning_state", "comparison_of_learning_scopes")


def test_same_scope_question_followup_uses_inventory_read_path():
    route = route_message("再给我一道同类题。", StudyContext(surface="study", knowledge_node_ids=[]))
    assert (route.capability, route.intent) == ("data_query", "find")


def test_mastery_confirmation_with_no_attempts_is_evidence_query_and_records_only_self_report():
    text = "我觉得自己已经掌握了特征值，但还没做过题。你能确认我掌握了吗？"
    route = route_message(text, StudyContext(surface="study"))
    assert (route.capability, route.intent) == ("data_query", "evidence_basis")
    claims = extract_self_reports(text)
    assert claims == [{
        "topic": "特征值", "assessment": "can_use",
        "statement": "我觉得自己已经掌握了特征值", "source": "self_report",
        "independently_verified": False,
    }]


def test_positive_natural_self_report_variants_are_unverified():
    for text in ("我感觉特征值还可以", "我觉得自己掌握了特征值", "我估计积分换元会做"):
        claims = extract_self_reports(text)
        assert claims and claims[0]["source"] == "self_report"
        assert claims[0]["independently_verified"] is False


def test_self_report_with_adjustment_request_is_planner_input_not_evidence_query():
    text = "我其实极限还可以，主要是积分换元经常做错。请根据这个新信息调整。"
    route = route_message(text, StudyContext(surface="study"))
    assert (route.capability, route.intent) == ("planner", "plan")
    claims = extract_self_reports(text)
    assert [(claim['topic'], claim['assessment'], claim['source'], claim['independently_verified'])
        for claim in claims] == [
            ('极限', 'can_use', 'self_report', False),
            ('积分换元', 'needs_help', 'self_report', False),
        ]


def test_stale_or_malformed_question_ids_in_prior_query_metadata_are_ignored():
    assert _uuid_list([
        "70000000-0000-0000-0000-000000000001", "not-a-uuid", None, {},
    ]) == [UUID("70000000-0000-0000-0000-000000000001")]
