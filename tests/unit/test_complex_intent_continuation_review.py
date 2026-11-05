"""Offline regressions for persisted previews and bounded candidate selection.

The controlled rows stand in for an already-read database result; no browser,
database connection, model output or external socket is used here.
"""
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from backend.schemas.learning_assistant import PlannerHandoff
from backend.schemas.learning_task import FindQuestions
from backend.services.assistant_router import CapabilityRoute
from backend.services.learning_task_tools import TaskTools
from backend.services.practice_request_service import draft_request


NOW = datetime(2040, 4, 3, tzinfo=timezone.utc)


class _Scalars(list):
    def all(self):
        return list(self)


def _question(kp_id, *, category="development_original", question_type="single_choice"):
    return SimpleNamespace(id=uuid4(), kp_id=kp_id, current_version_id=uuid4(),
        question_type=question_type, difficulty="basic", estimated_minutes=5,
        question_role="basic", is_variant=False, grading_config={}, skill_tags=[],
        category=category)


def _find(monkeypatch, rows, constraints, *, today=(), existing_facts=None, complete_ids=None):
    """Exercise the real candidate window after controlled eligible-row reads."""
    import backend.services.learning_task_tools as module

    kp_id = rows[0].kp_id
    node = SimpleNamespace(id=kp_id, name="洛必达法则")
    assessment = SimpleNamespace(practice_eligible=True, blocking_reasons=[],
        answer_comparison_method="reference", verified_grading_method=None,
        public_dict=lambda: {"practice_eligible": True})
    monkeypatch.setattr(module, "question_eligibility", lambda *a: assessment)
    monkeypatch.setattr(module, "_question_source_category", lambda q: q.category)

    class DB:
        def scalars(self, statement):
            entity = statement.column_descriptions[0].get("entity")
            return _Scalars(rows if entity is module.Question else [])

        def get(self, model, identifier):
            assert model is module.KnowledgePoint and identifier == kp_id
            return node

    tools = TaskTools.__new__(TaskTools)
    # __new__ bypasses the production constructor's default difficulty field.
    tools.required_difficulty = None
    tools.handoff = {"constraints": constraints}
    tools.explicit_scope = {kp_id}
    tools.current_plan_node_ids = set()
    tools.excluded_scope = set()
    tools.state_facts = {}
    tools.questions = set()
    tools.inventory_facts = existing_facts if existing_facts is not None else {}
    tools.inventory_complete_ids = complete_ids if complete_ids is not None else set()
    tools._check_nodes = lambda ids: None
    tools._today_question_ids = lambda db: set(today)
    return tools.find_questions(DB(), FindQuestions(kp_ids=[kp_id]))


def test_existing_plan_rows_cannot_hide_the_next_unused_candidate(monkeypatch):
    kp_id = uuid4()
    rows = [_question(kp_id) for _ in range(17)]
    result = _find(monkeypatch, rows, {"existing_bank_only": True},
        today=[q.id for q in rows[:16]])
    assert [q["question_id"] for q in result["questions"]] == [str(rows[16].id)]
    assert not result["questions"][0]["in_today_plan"]


def test_source_constraint_is_applied_before_candidate_window(monkeypatch):
    kp_id = uuid4()
    rows = [_question(kp_id, category="personal_ai_practice") for _ in range(16)]
    allowed = _question(kp_id)
    result = _find(monkeypatch, [*rows, allowed], {"existing_bank_only": True,
        "preview_query_state": {"excluded_source_categories": ["personal_ai_practice"]}})
    assert [q["question_id"] for q in result["questions"]] == [str(allowed.id)]


def test_question_type_constraint_is_applied_before_candidate_window(monkeypatch):
    kp_id = uuid4()
    rows = [_question(kp_id, question_type="fill_blank") for _ in range(16)]
    allowed = _question(kp_id)
    result = _find(monkeypatch, [*rows, allowed], {"existing_bank_only": True,
        "preview_question_type": "single_choice"})
    assert [q["question_id"] for q in result["questions"]] == [str(allowed.id)]


def test_positive_source_constraint_is_applied_before_candidate_window(monkeypatch):
    kp_id = uuid4()
    rows = [_question(kp_id) for _ in range(16)]
    allowed = _question(kp_id, category="exam_curated")
    result = _find(monkeypatch, [*rows, allowed], {"existing_bank_only": True,
        "preview_query_state": {"source_categories": ["exam_curated"]}})
    assert [q["question_id"] for q in result["questions"]] == [str(allowed.id)]


def test_pinned_question_version_is_not_lost_to_candidate_window(monkeypatch):
    kp_id = uuid4()
    rows = [_question(kp_id) for _ in range(17)]
    pinned = rows[-1]
    result = _find(monkeypatch, rows, {"existing_bank_only": True,
        "selected_question_refs": [{"question_id": str(pinned.id),
            "question_version": str(pinned.current_version_id)}]})
    assert [(q["question_id"], q["question_version"]) for q in result["questions"]] == [
        (str(pinned.id), str(pinned.current_version_id))]


def test_changed_pinned_version_is_never_silently_substituted(monkeypatch):
    kp_id = uuid4()
    row = _question(kp_id)
    result = _find(monkeypatch, [row], {"existing_bank_only": True,
        "selected_question_refs": [{"question_id": str(row.id), "question_version": str(uuid4())}]})
    assert result["questions"] == []


def test_replacement_excludes_old_question_before_candidate_window(monkeypatch):
    kp_id = uuid4()
    rows = [_question(kp_id) for _ in range(17)]
    result = _find(monkeypatch, rows, {"existing_bank_only": True,
        "excluded_preview_question_ids": [str(rows[0].id)]})
    assert str(rows[0].id) not in {q["question_id"] for q in result["questions"]}
    assert str(rows[-1].id) in {q["question_id"] for q in result["questions"]}


def test_ordinary_find_still_reports_today_and_other_source_rows(monkeypatch):
    kp_id = uuid4()
    rows = [_question(kp_id), _question(kp_id, category="personal_ai_practice")]
    result = _find(monkeypatch, rows, {}, today=[rows[0].id])
    assert len(result["questions"]) == 2
    assert result["questions"][0]["in_today_plan"] is True


def test_preview_subset_preserves_prior_complete_scope_inventory(monkeypatch):
    from copy import deepcopy
    kp_id = uuid4()
    rows = [_question(kp_id) for _ in range(2)]
    facts = {str(kp_id): {"additional_eligible_count": 37,
        "additional_eligible_question_ids": [str(uuid4()) for _ in range(37)],
        "today_question_trust": []}}
    complete = {str(kp_id)}
    before = deepcopy(facts)
    result = _find(monkeypatch, rows, {"existing_bank_only": True,
        "selected_question_refs": [{"question_id": str(rows[0].id),
            "question_version": str(rows[0].current_version_id)}]},
        existing_facts=facts, complete_ids=complete)
    assert facts == before and complete == {str(kp_id)}
    assert result["additional_eligible_count"] is None
    assert result["additional_eligible_question_ids"] == []


def test_preview_subset_does_not_claim_new_complete_scope_inventory(monkeypatch):
    kp_id = uuid4()
    facts, complete = {}, set()
    _find(monkeypatch, [_question(kp_id)], {"existing_bank_only": True},
        existing_facts=facts, complete_ids=complete)
    assert facts == {} and complete == set()


class _ReachedBuilder(Exception):
    pass


def _replacement(monkeypatch, *, reason, explicit_node, original_node, message, resolved_nodes=None):
    import backend.services.learning_assistant_service as assistant
    import backend.services.practice_preview_reference as previews
    import backend.services.practice_request_service as requests
    import backend.services.composite_bank_plan as composite

    rid, question_id, version = uuid4(), uuid4(), uuid4()
    handoff = PlannerHandoff(user_problem=message, source_conversation_id=uuid4(),
        source_message_id=uuid4(), request_type="plan", generated_at=NOW,
        target_knowledge_node_ids=[explicit_node],
        constraints={"scope_explicit": True, "scope_version": 1,
            "scope_origin": "explicit_message_scope",
            "resolved_scope_node_ids": [str(k) for k in resolved_nodes or [explicit_node]]})
    ref = {"question_id": str(question_id), "question_version": str(version),
        "kp_id": str(original_node), "question_type": "single_choice",
        "query_state": {"scope_node_ids": [str(original_node)], "source_categories": ["exam_curated"]},
        "request_id": str(rid), "source_message_id": str(uuid4())}
    captured = {"cancelled": []}
    monkeypatch.setattr(assistant, "planner_handoff", lambda *a, **kw: handoff)
    monkeypatch.setattr(previews, "latest_preview", lambda *a, **kw: (ref, None))
    monkeypatch.setattr(requests, "decline_request", lambda factory, request_id, **kw: captured["cancelled"].append(request_id))

    def build(factory, *, handoff, now):
        captured["handoff"] = handoff
        raise _ReachedBuilder

    monkeypatch.setattr(composite, "build_explained_plan", build)
    class NoPlan:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def scalar(self, statement):
            from backend.models.learning import DailyPlan
            assert statement.column_descriptions[0]["entity"] is DailyPlan
            return None
    args = dict(factory=NoPlan, ctx=SimpleNamespace(conversation_id=uuid4()), user_id=uuid4(),
        assistant_id=uuid4(), message=message, now=NOW,
        route=CapabilityRoute("planner", "plan", 1, reason))
    return args, captured, ref


def test_cancel_and_replace_can_follow_an_explicit_new_topic(monkeypatch):
    old, new = uuid4(), uuid4()
    args, captured, ref = _replacement(monkeypatch, reason="replace_preview", explicit_node=new,
        original_node=old, message="取消刚才的题，换一道洛必达的")
    with pytest.raises(_ReachedBuilder):
        draft_request(**args)
    assert captured["cancelled"] == []  # Builder failed: retain the previous valid draft.
    handoff = captured["handoff"]
    assert handoff.target_knowledge_node_ids == [new]
    assert handoff.constraints["resolved_scope_node_ids"] == [str(new)]
    assert ref["question_id"] in handoff.constraints["excluded_preview_question_ids"]


def test_new_chapter_scope_keeps_server_resolved_descendants(monkeypatch):
    old, chapter, child_a, child_b = [uuid4() for _ in range(4)]
    resolved = [chapter, child_a, child_b]
    args, captured, _ = _replacement(monkeypatch, reason="replace_preview", explicit_node=chapter,
        original_node=old, message="取消刚才的题，换一道微分学章节的题", resolved_nodes=resolved)
    with pytest.raises(_ReachedBuilder):
        draft_request(**args)
    handoff = captured["handoff"]
    assert handoff.target_knowledge_node_ids == [chapter]
    assert handoff.constraints["resolved_scope_node_ids"] == [str(k) for k in resolved]
    assert handoff.constraints["preview_query_state"]["scope_node_ids"] == [str(k) for k in resolved]


def test_adding_a_specific_preview_cannot_change_its_topic(monkeypatch):
    args, captured, _ = _replacement(monkeypatch, reason="select_preview", explicit_node=uuid4(),
        original_node=uuid4(), message="把刚才那道洛必达题加入今日卷")
    result = draft_request(**args)
    assert "不同" in result["notice"]
    assert captured["cancelled"] == [] and "handoff" not in captured


def test_qa_composite_request_passes_the_explanation_subgoal_to_the_builder(monkeypatch):
    node = uuid4()
    args, captured, _ = _replacement(monkeypatch, reason="explicit_bank_selection", explicit_node=node,
        original_node=node, message="讲讲洛必达法则，再从题库挑一道加入今日卷")
    args["route"] = CapabilityRoute("planner", "plan", 1, "explicit_bank_selection",
        explanation_request="讲讲洛必达法则")
    with pytest.raises(_ReachedBuilder):
        draft_request(**args)
    assert captured["handoff"].constraints["explanation_request"] == "讲讲洛必达法则"


def test_same_topic_replacement_keeps_constraints_and_cancels_only_the_old_draft(monkeypatch):
    node = uuid4()
    args, captured, ref = _replacement(monkeypatch, reason="replace_preview", explicit_node=node,
        original_node=node, message="取消刚才的题，换一道同知识点的")
    with pytest.raises(_ReachedBuilder):
        draft_request(**args)
    assert captured["cancelled"] == []  # Builder failed: retain the previous valid draft.
    handoff = captured["handoff"]
    assert handoff.target_knowledge_node_ids == [node]
    assert handoff.constraints["preview_query_state"]["source_categories"] == ["exam_curated"]
    assert handoff.constraints["preview_question_type"] == "single_choice"
    assert handoff.constraints["excluded_preview_question_ids"] == [ref["question_id"]]


def test_incomplete_candidate_scan_is_not_reported_as_empty_inventory(monkeypatch):
    import backend.services.composite_bank_plan as composite
    node = uuid4()
    handoff = PlannerHandoff(source_conversation_id=uuid4(), source_message_id=uuid4(),
        generated_at=NOW, request_type="plan", user_problem="讲讲洛必达，再选一道题", 
        target_knowledge_node_ids=[node], constraints={"scope_explicit": True,
            "explanation_request": "讲讲洛必达"})

    class Tools:
        explicit_scope = {node}
        draft = None

        def __init__(self, *a, **kw):
            pass

        def execute(self, name, args):
            if name == "read_lesson":
                return {"available": True, "name": "洛必达法则", "markdown": "保留的系统讲解"}
            if name == "find_questions":
                return {"questions": [], "candidate_list_complete": False}
            if name == "validate_plan":
                raise AssertionError("incomplete empty candidates cannot create a draft")
            return {}

    monkeypatch.setattr(composite, "TaskTools", Tools)
    result = composite.build_explained_plan(None, handoff=handoff, now=NOW)
    assert result["status"] == "needs_info" and result["draft"] is None
    assert result["error_code"] == "candidate_inventory_incomplete"
    assert "不能据此断言没有" in result["message"] and "保留的系统讲解" in result["message"]
