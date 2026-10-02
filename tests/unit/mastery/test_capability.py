from uuid import uuid4
import pytest
from backend.mastery.capability import (CapabilityQuestion, CapabilityAttempt,
    capability_keys, project_capabilities)


def question(kind="calculation", role="basic", variant=False, gradable=True, tags=()):
    return CapabilityQuestion(uuid4(), kind, role, variant, gradable, tags)


def profile(questions=(), attempts=(), confirmed=(), pending=(), **kwargs):
    return project_capabilities(subject="考研数学", questions=list(questions),
        recent_attempts=list(attempts), confirmed_ids=set(confirmed), pending_ids=set(pending), **kwargs)


def dimension(result, key="final_result"):
    return next(d for d in result.dimensions if d.key == key)


@pytest.mark.parametrize("kind,role,variant,expected", [
    ("single_choice", "basic", False, ("concept_conditions",)),
    ("multiple_choice", "typical", False, ("concept_conditions",)),
    ("fill_blank", "typical", False, ("final_result",)),
    ("calculation", "comprehensive", False, ("final_result", "application_transfer")),
    ("single_choice", "variant", True, ("concept_conditions", "application_transfer")),
    ("program_output", "basic", False, ("final_result",)),
    ("code_execution", "basic", False, ("final_result",)),
    ("proof", "comprehensive", True, ("reasoning_process",)),
    ("discussion", "basic", False, ("reasoning_process",)),
    ("program", "variant", True, ("algorithm_process",)),
    ("algorithm", "basic", False, ("algorithm_process",)),
    ("unknown_new_type", "basic", False, ("other",)),
])
def test_mapping_does_not_guess_from_stem(kind, role, variant, expected):
    assert capability_keys(kind, role, variant) == expected


def test_no_questions_means_unverified_not_unskilled():
    result = profile()
    assert len(result.dimensions) == 4
    assert all(d.status == "not_verified" and d.independent_question_count == 0 for d in result.dimensions)
    assert "score" not in result.model_dump_json()
    assert "不能据此判断不会" in dimension(result).reason


def test_confirmations_are_unique_and_not_a_mastery_declaration():
    q = question(tags=("换元", "换元"))
    result = profile([q], confirmed=[q.id, q.id])
    d = dimension(result)
    assert d.status == "independent_evidence" and d.independent_question_count == 1
    assert d.independent_question_ids == [q.id] and d.observed_skill_tags == ["换元"]
    assert "不代表全面掌握" in d.reason
    assert dimension(result, "reasoning_process").independent_question_count == 0


def test_pending_review_overrides_old_success_for_same_question():
    a, b = question(), question()
    d = dimension(profile([a, b], confirmed=[a.id, b.id], pending=[a.id]))
    assert d.status == "needs_retest" and d.independent_question_ids == [b.id]
    assert d.pending_review_question_count == 1


@pytest.mark.parametrize("category,assisted", [
    ("self_corrected", False), ("solution_assisted_correct", True),
    ("process_review_assisted_correct", True), ("low_confidence_correct", False),
    ("independent_correct_history_unknown", False), ("unable_to_grade", None),
])
def test_attempts_without_current_confirmation_remain_limited(category, assisted):
    q = question()
    d = dimension(profile([q], [CapabilityAttempt(q.id, "right", assisted, category)]))
    assert d.status == "limited_evidence" and d.independent_question_count == 0
    assert d.recent_assisted_attempt_count == (1 if assisted else 0)


@pytest.mark.parametrize("kind,key", [("proof", "reasoning_process"), ("program", "algorithm_process"), ("new", "other")])
def test_final_answer_or_misconfigured_grader_never_confirms_process(kind, key):
    q = question(kind, gradable=True)
    d = dimension(profile([q], confirmed=[q.id], pending=[q.id]), key)
    assert d.independent_question_count == d.reliable_grading_question_count == 0
    assert d.evidence_scope == "process" and d.status == "not_verified"


def test_unverified_config_cannot_use_confirmation():
    q = question(gradable=False)
    d = dimension(profile([q], confirmed=[q.id]))
    assert d.independent_question_count == 0 and "缺少" in d.reason


def test_transfer_requires_observed_role_not_a_later_metadata_edit():
    q = question(role="comprehensive")
    result = profile([q], confirmed=[q.id], transfer_confirmed_ids=set())
    assert dimension(result).independent_question_count == 1
    assert dimension(result, "application_transfer").independent_question_count == 0


def test_408_exposes_algorithm_gap_even_without_online_questions():
    result = project_capabilities(subject="408", questions=[], recent_attempts=[], confirmed_ids=set(), pending_ids={uuid4()})
    assert dimension(result, "algorithm_process").status == "not_verified"
    assert result.unmapped_pending_review_count == 1
