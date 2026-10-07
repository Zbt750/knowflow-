from copy import deepcopy
import pytest
from scripts.prepare_recent_exam_practice import build


def inputs():
    selection = {"version": "local-recent-exam-comparison-v1", "compared_on": "2026-10-03",
        "papers": {"408-2025": {"title": "隔离合成来源卷", "relative_path": "408/2025/test.pdf",
            "edition": "合成测试，不是真题", "sha256": "a" * 64}},
        "questions": [{"subject": "408", "year": 2025, "number": 1, "page": 1,
            "additional_pages": [2], "kp_code": "test.node", "mapping_rationale": "原页知识范围对照",
            "type_basis": "明确单项选择题", "comparison_complete": True, "unresolved_issues": [],
            "stem": "仅用于隔离测试的合成题干", "options": {"A": "甲", "B": "乙", "C": "丙", "D": "丁"}}]}
    sources = {"408": {"rows": [{"year": 2025, "num": 1, "answer": "B"}]}}
    refs = [{"subject": "408", "year": 2025, "question_number": 1, "knowledge_point_code": "test.node"}]
    return selection, sources, refs


def test_local_transcription_keeps_unverified_grading_and_cross_page_provenance():
    selection, sources, refs = inputs()
    before = deepcopy(selection)
    q = build(selection, sources, refs).questions[0]
    assert selection == before
    assert q.content_status == "source_transcribed"
    assert q.grading_method is None and q.answer_reviewed_by is None
    assert "第1,2页" in q.source.citation
    assert "非真人" in q.source.reviewed_by


@pytest.mark.parametrize("problem", ["scope", "blocked", "uncompared", "issue", "mapping", "answer", "duplicate", "page", "missing_option"])
def test_import_preparation_fails_closed(problem):
    selection, sources, refs = inputs()
    row = selection["questions"][0]
    if problem == "scope": row["year"] = 2024
    if problem == "blocked": row.update(subject="408", year=2026, number=3)
    if problem == "uncompared": row["comparison_complete"] = False
    if problem == "issue": row["unresolved_issues"] = ["missing_diagram"]
    if problem == "mapping": row["kp_code"] = "not.in.source"
    if problem == "answer": sources["408"]["rows"][0]["answer"] = None
    if problem == "duplicate": selection["questions"].append(deepcopy(row))
    if problem == "page": row["additional_pages"] = [0]
    if problem == "missing_option": del row["options"]["D"]
    with pytest.raises(ValueError):
        build(selection, sources, refs)
