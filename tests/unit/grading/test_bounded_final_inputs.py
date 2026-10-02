import pytest
from pydantic import ValidationError
from backend.services.answer_grading import grade_final_answer, available_grading_method
from backend.services.question_pack import QuestionContent


def grade(answer, expected="ln(2)", method="logarithm_final", verified=True, kind="calculation"):
    return grade_final_answer(question_type=kind, config={"method": method, "verified": verified},
        answer=answer, selected_option=None, expected=expected, options=None)


@pytest.mark.parametrize("answer", ["ln(2)", "ln 2", r"\ln(2)", r"$\ln 2$", "ln(4/2)", r"ln(\frac{4}{2})", "ln(2.0)"])
def test_logarithm_only_compares_exact_positive_rational_arguments(answer):
    result = grade(answer)
    assert result.result == "right" and result.method == "exact_logarithm_v1"


@pytest.mark.parametrize("answer", ["ln(3)", "ln(1/2)", "ln(1)"])
def test_distinct_valid_logarithms_are_wrong(answer):
    assert grade(answer).result == "wrong"


@pytest.mark.parametrize("answer", ["0.693147", "log(2)", "ln(0)", "ln(-2)", "ln(x)",
    "ln(2)+0", "ln(4)/2", "ln(exp(1))", "ln(1/0)", "LN(2)", "2 cm", "__import__('os')", "9" * 129])
def test_unsupported_syntax_is_unknown_not_wrong(answer):
    result = grade(answer)
    assert result.result == "unknown" and result.reason == "unsupported_answer"


@pytest.mark.parametrize("answer,result", [("0", "right"), ("0/2", "right"), ("1", "wrong"), ("ln(2)", "wrong")])
def test_ln_one_has_exact_zero_exception(answer, result):
    assert grade(answer, expected="ln(1)").result == result


@pytest.mark.parametrize("answer", [r"\frac{1}{3}", r"$\dfrac{2}{6}$", r"\tfrac{0.5}{1.5}", "1/3"])
def test_numeric_fraction_formatting_does_not_use_approximation(answer):
    assert grade(answer, expected="1/3", method="numeric_final").result == "right"


def test_signed_fraction_and_invalid_denominator():
    assert grade(r"-\frac{-1}{2}", expected="0.5", method="numeric_final").result == "right"
    assert grade(r"\frac{1}{0}", expected="1", method="numeric_final").result == "unknown"
    assert grade("0.333", expected="1/3", method="numeric_final").result == "wrong"


@pytest.mark.parametrize("verified,kind,expected", [(False,"calculation","ln(2)"), (True,"proof","ln(2)"),
    (True,"subjective","ln(2)"), (True,"calculation","ln(0)"), (True,"calculation","log(2)")])
def test_availability_and_submission_share_domain_and_review_gate(verified, kind, expected):
    assert available_grading_method(question_type=kind, config={"verified":verified,"method":"logarithm_final"},
        expected=expected, options=None) is None
    assert grade("ln(2)", expected=expected, verified=verified, kind=kind).result == "unknown"


def test_reference_domain_and_empty_answer():
    assert grade("ln(2)", expected="ln(-1)").reason == "unsupported_reference"
    assert grade("").reason == "not_answered"


def test_reviewed_pack_supports_only_applicable_logarithm_reference():
    import json
    from pathlib import Path
    data = json.loads(Path("eval/golden/integral_binary_tree_v1.json").read_text(encoding="utf-8"))
    content = next(q["content"] for q in data["questions"] if q["content"]["source_id"] == "M07")
    proposed = {**content, "grading_method": "logarithm_final"}
    assert QuestionContent.model_validate(proposed).grading_method == "logarithm_final"
    with pytest.raises(ValidationError):
        QuestionContent.model_validate({**proposed, "correct_answer":"ln(0)"})
    with pytest.raises(ValidationError):
        QuestionContent.model_validate({**proposed, "question_type":"proof"})


def test_proposal_is_bound_to_unchanged_unverified_asset():
    import hashlib
    import json
    from pathlib import Path
    proposal = json.loads(Path("eval/golden/p4-grading-proposal-v1.json").read_text(encoding="utf-8"))
    raw = Path(proposal["source_asset"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == proposal["source_asset_sha256"]
    data = json.loads(raw)
    candidate = next(q for q in data["questions"] if q["content"]["source_id"] == proposal["source_id"])
    assert candidate["content"]["correct_answer"] == proposal["candidate_answer"]
    assert candidate["content"]["grading_method"] is None
    assert all(review["status"] == "GENERATED" for review in candidate["reviews"].values())
    assert proposal["review_status"] == "UNVERIFIED" and not proposal["development_database_imported"]
