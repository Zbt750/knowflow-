from types import SimpleNamespace
from uuid import uuid4

from backend.services.evidence_pool import assess_evidence_pool


def make_question(stem, *, variant=False):
    return SimpleNamespace(id=uuid4(), question_type="single_choice", stem=stem,
        options={"A": "甲", "B": "乙"}, is_variant=variant)


def eligible(q, *, capability="verified_objective", answer_provenance="verified_reference"):
    return SimpleNamespace(practice_eligible=True, evidence_capability=capability,
        answer_provenance=answer_provenance, grading_capability="deterministic")


def test_sufficient_requires_distinct_objective_questions_variant_and_unused_opportunity():
    first, second = make_question("题目一"), make_question("题目二", variant=True)
    result = assess_evidence_pool(questions=[first, second],
        eligibility_by_id={first.id: eligible(first), second.id: eligible(second)},
        attempted_question_ids=set())
    assert result.status == "SUFFICIENT"
    assert result.verified_objective_question_count == 2
    assert result.distinct_objective_question_count == 2
    assert result.unattempted_objective_question_count == 2


def test_duplicate_text_is_not_a_distinct_question_even_with_different_ids():
    first, copy = make_question("同一道题"), make_question("同一道题", variant=True)
    result = assess_evidence_pool(questions=[first, copy],
        eligibility_by_id={first.id: eligible(first), copy.id: eligible(copy)},
        attempted_question_ids=set())
    assert result.status == "INSUFFICIENT"
    assert "NO_DISTINCT_QUESTION" in result.reasons


def test_repeated_attempts_do_not_create_a_delayed_opportunity_or_more_questions():
    first, second = make_question("题目一"), make_question("题目二", variant=True)
    result = assess_evidence_pool(questions=[first, second],
        eligibility_by_id={first.id: eligible(first), second.id: eligible(second)},
        attempted_question_ids={first.id, second.id})
    assert result.status == "INSUFFICIENT"
    assert result.distinct_objective_question_count == 2
    assert result.unattempted_objective_question_count == 0
    assert "NO_DELAYED_VERIFICATION_OPPORTUNITY" in result.reasons


def test_ai_reference_answers_do_not_count_as_verified_objective_opportunity():
    q = make_question("AI答案题", variant=True)
    result = assess_evidence_pool(questions=[q],
        eligibility_by_id={q.id: eligible(q, capability="ai_answer_comparison_only", answer_provenance="ai_generated")},
        attempted_question_ids=set())
    assert result.status == "INSUFFICIENT"
    assert result.verified_objective_question_count == 0
    assert "ANSWER_RELIABILITY_TOO_LOW" in result.reasons


def test_unknown_pool_is_not_a_learner_mastery_label():
    result = assess_evidence_pool(questions=[], eligibility_by_id={}, attempted_question_ids=set(), known=False)
    assert result.status == "UNKNOWN"
    assert result.reasons == ()


def test_versioned_pool_keeps_strict_type_skill_and_distinct_gates_but_not_origin_quota():
    from backend.mastery.policy import MasteryPolicy

    questions=[make_question(f"真实题{i}") for i in range(3)]
    for q in questions: q.question_provenance="real_exam"; q.skill_tags=["topic"]
    policy=MasteryPolicy(policy_version=2,required_question_origins={"real_exam":3},
        min_confirmations=3,min_real_questions=3,required_variant_count=0,
        required_skill_tags=frozenset({"topic"}),min_day_span=2)
    arguments={"questions":questions,"eligibility_by_id":{q.id:eligible(q) for q in questions},
        "attempted_question_ids":{q.id for q in questions},"policy":policy}
    result=assess_evidence_pool(**arguments)
    # Inventory remains available for a future independent retest; source
    # identity does not gate eligibility for a public objective evidence pool.
    assert result.status=="SUFFICIENT" and result.unattempted_objective_question_count==0
    questions[-1].question_provenance="trusted_practice"
    result=assess_evidence_pool(**arguments)
    assert result.status=="SUFFICIENT"
    # Other reliability gates remain unchanged.
    arguments["eligibility_by_id"][questions[-1].id]=eligible(questions[-1],capability="ai_consistent_objective",answer_provenance="ai_generated")
    assert assess_evidence_pool(**arguments).status=="INSUFFICIENT"
