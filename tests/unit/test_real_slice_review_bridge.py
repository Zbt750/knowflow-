"""SIMULATED human attestations exist only in these pure tests; never actual approvals."""
from copy import deepcopy
from datetime import date

import pytest

from backend.services.golden_learning_slice import ASPECTS, digest
from backend.services.question_pack import PackQuestion, fingerprint
from scripts.prepare_real_slice_review import prepare, template


def reviewed_fixture():
    candidate = {"subject": "408", "year": 2025, "question_number": 3,
        "candidate_node_codes": ["cs408.synthetic"], "issues": ["rights_not_confirmed", "answer_review_pending"]}
    batch = {"version": "structured-real-slice-intake-v1", "questions": [candidate]}
    q = PackQuestion.model_validate({"source_id": "408-2025-q003", "kp_code": "cs408.synthetic",
        "question_type": "single_choice", "stem": "Synthetic binary arithmetic fixture",
        "options": {"A": "2", "B": "3"}, "correct_answer": "A", "explanation": "Synthetic bit weight explanation",
        "estimated_minutes": 2, "skill_tags": ["synthetic"], "grading_method": "single_choice",
        "answer_reviewed_by": "SIMULATED TEST ONLY", "answer_reviewed_on": date.today().isoformat(),
        "content_reviewed_by": "SIMULATED TEST ONLY", "content_reviewed_on": date.today().isoformat(),
        "answer_provenance": "human_verified", "answer_reliability": "verified",
        "answer_review_method": "SIMULATED independent review", "answer_review_note": "SIMULATED fixture note only",
        "source": {"kind": "licensed", "source_type": "exam",
            "year": 2025, "question_number": 3, "subject": "408", "paper_title": "SIMULATED exam fixture",
            "citation": "Synthetic fixture, NOT a real question", "rights_basis": "SIMULATED permission, not a real license",
            "reviewed_by": "SIMULATED TEST ONLY", "reviewed_on": date.today().isoformat()}})
    # Hash the exact serialized representation sent to prepare(), including
    # optional-field presence; a model with omitted fields is not that payload.
    q = PackQuestion.model_validate(q.model_dump(mode="json"))
    sha = fingerprint(q)
    decisions = template(batch)
    decisions["human_review_confirmed"] = True
    row = decisions["questions"][0]
    row.update(approved_question=q.model_dump(mode="json"), approved_question_sha256=sha,
        reviews={aspect: {"status": "VERIFIED", "reviewer_kind": "human", "reviewed_by": "SIMULATED TEST ONLY",
            "reviewed_on": date.today().isoformat(), "content_sha256": sha, "note": "SIMULATED fixture note only"}
            for aspect in ASPECTS}, resolved_issues={issue: "SIMULATED resolution only" for issue in candidate["issues"]})
    return batch, decisions


def test_template_is_unapproved_and_cannot_export():
    batch, _ = reviewed_fixture()
    draft = template(batch)
    assert not draft["human_review_confirmed"]
    with pytest.raises(ValueError, match="human"):
        prepare(batch, draft)


def test_simulated_review_exports_existing_pack_schema_without_database_writes():
    batch, decisions = reviewed_fixture()
    pack = prepare(batch, decisions)
    assert len(pack.questions) == 1
    assert pack.questions[0].source.source_type == "exam"


@pytest.mark.parametrize("mutation", ["batch", "candidate", "answer", "mapping", "identity", "reviewer", "aspect", "resolution", "date"])
def test_modified_content_or_incomplete_review_rejected(mutation):
    batch, decisions = reviewed_fixture()
    row = decisions["questions"][0]
    if mutation == "batch": batch["extra"] = "modified"
    if mutation == "candidate": row["candidate_sha256"] = "0" * 64
    if mutation in {"answer", "mapping", "identity", "reviewer"}:
        field = {"answer": "correct_answer", "mapping": "kp_code", "identity": "source_id", "reviewer": "answer_reviewed_by"}[mutation]
        row["approved_question"][field] = {"answer": "B", "mapping": "cs408.other", "identity": "408-2025-q004", "reviewer": "different"}[mutation]
        # Even a freshly calculated content hash cannot bypass identity or reviewer checks.
        if mutation != "answer":
            sha = fingerprint(PackQuestion.model_validate(row["approved_question"]))
            row["approved_question_sha256"] = sha
            for r in row["reviews"].values(): r["content_sha256"] = sha
    if mutation == "aspect": row["reviews"].pop("answer")
    if mutation == "resolution": row["resolved_issues"]["rights_not_confirmed"] = ""
    if mutation == "date": row["reviews"]["source"]["reviewed_on"] = "2025-01-01"
    with pytest.raises(ValueError):
        prepare(batch, decisions)


def test_duplicate_decisions_do_not_duplicate_questions():
    batch, decisions = reviewed_fixture()
    decisions["questions"].append(deepcopy(decisions["questions"][0]))
    with pytest.raises(ValueError, match="duplicate"):
        prepare(batch, decisions)
