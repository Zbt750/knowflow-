from types import SimpleNamespace

from scripts.prepare_verified_slice_candidates import (
    audit_source_availability, bounded_candidate_method,
)


def _source(**values):
    return {"source_type": "exam", "subject": "408", "year": 2021,
        "question_number": 23, "paper_title": "Synthetic source identity only",
        "citation": "Reference metadata with no downloaded source", **values}


def test_no_metadata_and_metadata_only_are_separate(tmp_path):
    assert audit_source_availability({}, tmp_path)["status"] == "SOURCE_MISSING"
    result = audit_source_availability(_source(), tmp_path)
    assert result["status"] == "SOURCE_METADATA_ONLY"
    assert not result["answer_verified"] and not result["answer_source_available"]


def test_original_question_paper_does_not_prove_the_current_answer(tmp_path):
    folder = tmp_path / "个人复习原卷/408"
    folder.mkdir(parents=True)
    (folder / "2021-test.pdf").write_bytes(b"%PDF-1.7\nSynthetic test file")
    result = audit_source_availability(_source(citation="个人复习原卷/408/2021-test.pdf（题面来源）"), tmp_path)
    assert result["status"] == "SOURCE_AMBIGUOUS"
    assert result["question_source_available"]
    assert not result["answer_source_available"] and not result["answer_verified"]


def test_declared_local_answer_source_only_makes_manual_review_possible(tmp_path):
    (tmp_path / "answer.txt").write_text("Synthetic fixture, not an actual authoritative answer", encoding="utf-8")
    result = audit_source_availability(_source(answer_reference_path="answer.txt"), tmp_path)
    assert result["status"] == "SOURCE_AVAILABLE_FOR_REVIEW"
    assert result["answer_source_available"]
    assert not result["answer_verified"]


def test_corrupt_pdf_and_path_escape_do_not_count_as_available(tmp_path):
    (tmp_path / "bad.pdf").write_bytes(b"not a PDF")
    for locator in ("bad.pdf", "../outside.txt", "missing.pdf"):
        result = audit_source_availability(_source(answer_reference_path=locator), tmp_path)
        assert result["status"] == "SOURCE_METADATA_ONLY"
        assert result["files"] == []


def test_ai_transcription_draft_cannot_become_an_answer_source(tmp_path):
    folder = tmp_path / "逐题整理/408/2021"
    folder.mkdir(parents=True)
    (folder / "Q23.md").write_text("参考答案草稿：B；待人工核验", encoding="utf-8")
    result = audit_source_availability(_source(citation="逐题整理/408/2021/Q23.md"), tmp_path)
    assert result["status"] == "SOURCE_AMBIGUOUS"
    assert not result["answer_source_available"] and not result["answer_verified"]


def test_candidate_comparer_support_does_not_activate_grading():
    question = SimpleNamespace(question_type="fill_blank", correct_answer="1/3", options=None,
        grading_config={"verified": False})
    assert bounded_candidate_method(question) == "numeric_final"
    assert question.grading_config["verified"] is False
    question.correct_answer = "x+1"
    assert bounded_candidate_method(question) is None
    question.question_type = "proof"
    assert bounded_candidate_method(question) is None

