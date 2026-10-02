from scripts.audit_multichunk_facts import audit_fact, audit_report


FACT = {
    "id": "common-persistence",
    "answer_any": ["持久化"],
    "sources": [
        {"material_title": "说明", "evidence_any": ["数据库持久化"]},
        {"material_title": "补充", "evidence_any": ["保留数据库数据"]},
    ],
}
BLOCKS = [
    {"label": "C1", "material_title": "说明", "context": "阶段F：数据库持久化"},
    {"label": "C2", "material_title": "补充", "context": "应保留数据库数据"},
]


def test_fact_audit_requires_each_source_and_its_citation():
    complete = audit_fact("共同要求是持久化 [C1][C2]", BLOCKS, FACT)
    assert complete["answer_present"] is True
    assert complete["evidence_present"] is True
    assert complete["sources_cited_somewhere"] is True

    missing_citation = audit_fact("共同要求是持久化 [C1]", BLOCKS, FACT)
    assert missing_citation["evidence_present"] is True
    assert missing_citation["sources_cited_somewhere"] is False

    wrong_file = audit_fact("共同要求是持久化 [C1][C2]", BLOCKS[:1], FACT)
    assert wrong_file["evidence_present"] is False
    assert wrong_file["sources_cited_somewhere"] is False


def test_fact_audit_does_not_treat_other_label_as_support():
    result = audit_fact("共同要求是持久化 [C3]", BLOCKS, FACT)
    assert result["sources_cited_somewhere"] is False


def test_report_audit_distinguishes_missing_snapshot_from_failed_coverage():
    checklist = {"version": "test-v1", "cases": {"cross-file": [FACT]}}
    report = {"cases": [
        {"case_id": "cross-file", "answer": "共同要求是持久化 [C1][C2]", "actual_evidence": {"blocks": BLOCKS}},
        {"case_id": "cross-file", "error_type": "EvalError"},
        {"case_id": "unlisted", "answer": "ignored"},
    ]}
    result = audit_report(report, checklist)
    assert [item["status"] for item in result["cases"]] == ["checked", "unavailable"]
    assert result["cases"][0]["facts"][0]["evidence_present"] is True
    assert result["cases"][1]["facts"] == []
