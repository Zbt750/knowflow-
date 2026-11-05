from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from backend.models.learning import KnowledgePoint, Question
from backend.services.answer_consistency import (
    ANSWER_ATTESTATION_PROMPT_VERSION,
    ANSWER_ATTESTATION_RUN_ROLES,
    ANSWER_CONSISTENCY_PROMPT_VERSION,
    apply_consistency_reliability,
    answer_attestation_outcome,
    build_attestation_run,
    build_attestation_solver_messages,
    build_attestation_verifier_messages,
    build_run,
    consistency_check_key,
    consistency_input_hash,
    consistency_outcome,
    normalize_consistency_answer,
    parse_final_answer_payload,
    parse_solver_output,
    parse_verifier_payload,
)
from backend.services.question_eligibility import question_eligibility


def ai_choice(*, answer="A", reliability="model_generated"):
    node = KnowledgePoint(id=uuid4(), code="synthetic.ai", name="隔离节点", subject="math2",
        is_active=True, is_assessable=True, is_reference_only=False)
    q = Question(id=uuid4(), kp_id=node.id, question_type="single_choice", grading_mode="self_assessed",
        grading_config={"verified": False, "practice_method": "single_choice"},
        stem="独立验证一项数学概念，选择正确选项。", options={"A": "甲", "B": "乙"},
        correct_answer=answer, explanation="隔离测试参考说明。", question_role="basic",
        skill_tags=["概念"], estimated_minutes=4, is_variant=False, is_active=True,
        question_provenance="real_exam", content_trust="verified", source_status="verified",
        answer_provenance="ai_generated", answer_reliability=reliability,
        content_reviewed_by="synthetic-review", content_reviewed_at=datetime(2026, 10, 1, tzinfo=timezone.utc))
    return q, node


def make_run(q, check, number, answer, status="completed"):
    return build_run(question=q, check_key=check, run_number=number, model="offline-fake",
        normalized_answer=answer, status=status, latency_ms=11, usage=None,
        error_code="test_error" if status != "completed" else None)


def test_multiple_choice_normalization_accepts_label_case_and_rejects_ambiguous_text():
    assert normalize_consistency_answer(question_type="single_choice", method="single_choice",
        answer="答案：a.", options={"A": "甲", "B": "乙"}, expected="A") == "choice:A"
    assert normalize_consistency_answer(question_type="single_choice", method="single_choice",
        answer="A 或 B", options={"A": "甲", "B": "乙"}, expected="A") is None


def test_numeric_normalization_is_exact_and_bounded():
    normalize = lambda value: normalize_consistency_answer(question_type="calculation", method="numeric_final",
        answer=value, options=None, expected="1/2")
    assert normalize("\\frac{1}{2}") == "rational:1/2"
    assert normalize("0.5") == "rational:1/2"
    assert normalize("sqrt(2)") is None


def test_solver_output_parser_never_persists_free_form_reasoning():
    assert parse_solver_output('{"answer":"A"}') == "A"
    assert parse_solver_output('{"answer":"A","reasoning":"secret"}') is None
    assert parse_solver_output("先分析一下，答案是 A") is None


def test_two_independent_outputs_must_match_each_other_and_current_ai_key():
    q, _ = ai_choice()
    check = consistency_check_key(q, model="offline-fake")
    first = make_run(q, check, 1, "choice:A")
    second = make_run(q, check, 2, "choice:A")
    outcome = consistency_outcome(q, [first, second])
    assert outcome["status"] == "AI_CONSISTENT"
    before_provenance = q.answer_provenance
    assert apply_consistency_reliability(q, outcome)
    assert q.answer_reliability == "ai_generated_consistent"
    assert q.answer_provenance == before_provenance == "ai_generated"

    changed_key, _ = ai_choice(answer="B")
    same_solvers = [make_run(changed_key, consistency_check_key(changed_key, model="offline-fake"), 1, "choice:A"),
                    make_run(changed_key, consistency_check_key(changed_key, model="offline-fake"), 2, "choice:A")]
    mismatch = consistency_outcome(changed_key, same_solvers)
    assert mismatch["status"] == "AI_DISAGREEMENT"
    assert apply_consistency_reliability(changed_key, mismatch)
    assert changed_key.answer_provenance == "ai_generated"
    assert changed_key.answer_reliability == "ai_disagreement"
    assert not question_eligibility(changed_key, _).practice_eligible


def test_disagreeing_runs_cannot_majority_vote_or_upgrade():
    q, _ = ai_choice()
    check = consistency_check_key(q, model="offline-fake")
    runs = [make_run(q, check, 1, "choice:A"), make_run(q, check, 2, "choice:B"),
            make_run(q, check, 3, "choice:A")]
    outcome = consistency_outcome(q, runs)
    assert outcome["status"] == "AI_DISAGREEMENT"
    assert apply_consistency_reliability(q, outcome)
    assert q.answer_reliability == "ai_disagreement"


def test_proof_and_programming_are_not_string_compared():
    for qtype in ("proof", "program", "discussion"):
        assert normalize_consistency_answer(question_type=qtype, method=None,
            answer="答案相同", options=None, expected="答案相同") is None


def test_content_hash_and_check_key_are_stable_and_versioned():
    q, _ = ai_choice()
    first = consistency_input_hash(q)
    assert first == consistency_input_hash(q)
    assert consistency_check_key(q, model="m", prompt_version=ANSWER_CONSISTENCY_PROMPT_VERSION) != consistency_check_key(
        q, model="m", prompt_version="future-prompt")


def test_verified_reference_answer_is_never_rewritten_by_consistency_result():
    q, _ = ai_choice()
    q.answer_provenance = "verified_reference"
    q.answer_reliability = "verified"
    assert not apply_consistency_reliability(q, {"status": "AI_DISAGREEMENT"})
    assert q.answer_provenance == "verified_reference"
    assert q.answer_reliability == "verified"


def test_three_role_attestation_requires_independent_agreement_and_exact_verify_support():
    q, _ = ai_choice(answer="B")
    from backend.services.answer_consistency import answer_attestation_check_key
    check = answer_attestation_check_key(q, model="offline-fake")
    a = build_attestation_run(question=q, check_key=check, run_number=1, run_role="solve_a",
        model="offline-fake", final_answer="A", normalized_answer="choice:A", status="completed",
        latency_ms=10, usage=None)
    b = build_attestation_run(question=q, check_key=check, run_number=2, run_role="solve_b",
        model="offline-fake", final_answer="A", normalized_answer="choice:A", status="completed",
        latency_ms=12, usage=None)
    c = build_attestation_run(question=q, check_key=check, run_number=3, run_role="verify_c",
        model="offline-fake", final_answer=None, normalized_answer=None, status="completed",
        latency_ms=8, usage=None,
        verification_result={"status": "supports", "supported_answers": ["choice:A"], "note": "选项 A"},
        candidate_answers_sha256="b" * 64)

    result = answer_attestation_outcome([a, b, c])
    assert result["status"] == "AI_CONSISTENT"
    assert result["normalized_answer"] == "choice:A"
    assert result["final_answer"] == "A"

    c.verification_result = {"status": "rejects", "supported_answers": [], "note": "不支持"}
    rejected = answer_attestation_outcome([a, b, c])
    assert rejected["status"] == "AI_DISAGREEMENT"
    assert rejected["normalized_answer"] is None
    c.verification_result = {"status": "supports", "supported_answers": ["choice:A", "choice:A"], "note": "重复列出同一候选"}
    assert answer_attestation_outcome([a, b, c])["status"] == "AI_CONSISTENT"
    c.verification_result = {"status": "supports", "supported_answers": ["choice:A", "choice:B"], "note": "额外候选冲突"}
    assert answer_attestation_outcome([a, b, c])["status"] == "NEEDS_REVIEW"


def test_three_role_attestation_rejects_missing_roles_disagreement_and_uncertain_verdict():
    q, _ = ai_choice()
    from backend.services.answer_consistency import answer_attestation_check_key
    check = answer_attestation_check_key(q, model="offline-fake")
    a = build_attestation_run(question=q, check_key=check, run_number=1, run_role="solve_a",
        model="offline-fake", final_answer="A", normalized_answer="choice:A", status="completed",
        latency_ms=1, usage=None)
    b = build_attestation_run(question=q, check_key=check, run_number=2, run_role="solve_b",
        model="offline-fake", final_answer="B", normalized_answer="choice:B", status="completed",
        latency_ms=1, usage=None)
    assert answer_attestation_outcome([a, b])["status"] == "INCOMPLETE"
    c = build_attestation_run(question=q, check_key=check, run_number=3, run_role="verify_c",
        model="offline-fake", final_answer=None, normalized_answer=None, status="completed",
        latency_ms=1, usage=None,
        verification_result={"status": "uncertain", "supported_answers": [], "note": "题面不充分"},
        candidate_answers_sha256="c" * 64)
    assert answer_attestation_outcome([a, b, c])["status"] == "AI_DISAGREEMENT"
    b.normalized_final_answer = "choice:A"
    b.final_answer = "A"
    assert answer_attestation_outcome([a, b, c])["status"] == "NEEDS_REVIEW"


def test_three_role_protocol_only_accepts_final_answer_json_and_keeps_solver_isolated():
    assert ANSWER_ATTESTATION_PROMPT_VERSION == "solve-a-b-verify-c-v1"
    assert ANSWER_ATTESTATION_RUN_ROLES == ("solve_a", "solve_b", "verify_c")
    assert parse_final_answer_payload('{"answer":"A"}') == "A"
    assert parse_final_answer_payload('{"answer":"A","reasoning":"do not store"}') is None
    assert parse_final_answer_payload("推导后答案为 A") is None
    assert parse_verifier_payload('{"status":"supports","supported_answers":["choice:A"],"note":"支持"}') == {
        "status": "supports", "supported_answers": ["choice:A"], "note": "支持"}
    two = parse_verifier_payload('{"status":"supports","supported_answers":["A","B"],"note":""}')
    assert two and len(two["supported_answers"]) == 2  # outcome gate rejects non-exact support

    q, _ = ai_choice()
    solver = build_attestation_solver_messages(q)
    verifier = build_attestation_verifier_messages(q, answer_a="choice:A", answer_b="choice:A")
    assert "reasoning" not in solver[-1]["content"]
    assert "reasoning" not in verifier[-1]["content"]
    assert "choice:A" in verifier[-1]["content"]
