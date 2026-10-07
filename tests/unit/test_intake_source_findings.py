from copy import deepcopy
import pytest
from backend.services.golden_learning_slice import digest
from scripts.annotate_intake_source_findings import annotate
from scripts.prepare_real_slice_review import template, prepare


def inputs():
    row = {"subject": "408", "year": 2011, "question_number": 6,
           "raw_text": "SYNTHETIC", "candidate_node_codes": ["synthetic.basic"],
           "primary_kp_code": None, "issues": ["rights_not_confirmed"],
           "verified": False, "can_import": False, "content_status": "UNVERIFIED"}
    batch = {"version": "structured-real-slice-intake-v1", "questions": [row]}
    findings = {"version": "ai-source-findings-v1", "batch_sha256": digest(batch),
                "human_review_confirmed": False, "questions": [{"candidate_id": "408-2011-q006",
                    "candidate_sha256": digest(row), "issues": ["mapping_conflict", "source_year_conflict"],
                    "note": "Synthetic isolated conflict; not human verification.",
                    "proposed_primary_kp_code": "synthetic.conversion"}]}
    return batch, findings


def test_findings_preserved_without_approving_or_remapping():
    batch, findings = inputs()
    before = deepcopy(batch)
    revised = annotate(batch, findings)
    row = revised["questions"][0]
    assert batch == before
    assert row["primary_kp_code"] is None
    assert row["candidate_node_codes"] == ["synthetic.basic", "synthetic.conversion"]
    assert row["issues"] == ["mapping_conflict", "rights_not_confirmed", "source_year_conflict"]
    assert row["verified"] is False and row["can_import"] is False
    decisions = template(revised)
    assert set(decisions["questions"][0]["resolved_issues"]) == set(row["issues"])
    assert decisions["batch_sha256"] != digest(batch)
    with pytest.raises(ValueError, match="actual human"):
        prepare(revised, decisions)


@pytest.mark.parametrize("mutation", ["stale_batch", "stale_row", "duplicate", "unknown", "approve", "empty_issues", "verified", "blank_mapping"])
def test_unsafe_findings_fail_closed(mutation):
    batch, findings = inputs()
    if mutation == "stale_batch": findings["batch_sha256"] = "0"*64
    if mutation == "stale_row": findings["questions"][0]["candidate_sha256"] = "0"*64
    if mutation == "duplicate": findings["questions"].append(deepcopy(findings["questions"][0]))
    if mutation == "unknown": findings["questions"][0]["candidate_id"] = "unknown"
    if mutation == "approve": findings["human_review_confirmed"] = True
    if mutation == "empty_issues": findings["questions"][0]["issues"] = []
    if mutation == "blank_mapping": findings["questions"][0]["proposed_primary_kp_code"] = " "
    if mutation == "verified":
        batch["questions"][0]["verified"] = True
        findings["batch_sha256"] = digest(batch)
        findings["questions"][0]["candidate_sha256"] = digest(batch["questions"][0])
    with pytest.raises(ValueError):
        annotate(batch, findings)


def test_retracting_ai_subject_inference_preserves_audit_and_review_requirements():
    batch, findings = inputs()
    row = batch["questions"][0]
    row["issues"].append("local_source_subject_edition_conflict")
    row["source_findings"] = {"note": "Earlier AI inference, retained for audit"}
    findings["batch_sha256"] = digest(batch)
    finding = findings["questions"][0]
    finding["candidate_sha256"] = digest(row)
    finding["withdrawn_issues"] = ["local_source_subject_edition_conflict"]
    revised = annotate(batch, findings)["questions"][0]
    assert "local_source_subject_edition_conflict" not in revised["issues"]
    assert "rights_not_confirmed" in revised["issues"]
    assert revised["source_findings_history"] == [row["source_findings"]]
    assert revised["verified"] is False
    assert revised["can_import"] is False
    assert row["issues"] == ["rights_not_confirmed", "local_source_subject_edition_conflict"]


@pytest.mark.parametrize("withdrawn", [["rights_not_confirmed"], ["human_review_missing"],
                                      ["local_source_subject_edition_conflict"],
                                      ["source_year_conflict"]])
def test_withdrawal_cannot_bypass_review_or_erase_missing_issue(withdrawn):
    batch, findings = inputs()
    findings["questions"][0]["withdrawn_issues"] = withdrawn
    with pytest.raises(ValueError, match="withdrawn"):
        annotate(batch, findings)
