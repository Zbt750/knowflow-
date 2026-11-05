from copy import deepcopy

import pytest

from backend.services.golden_learning_slice import digest
from scripts.check_slice_release_readiness import audit, options_dict


def inputs():
    candidate = {"subject": "408", "year": 2025, "question_number": 3,
        "question_type": "single_choice", "options": [{"label": "A", "text": "Synthetic A"},
            {"label": "B", "text": "Synthetic B"}]}
    batch = {"version": "structured-real-slice-intake-v1", "questions": [candidate]}
    row = {"candidate_id": "408-2025-q003", "candidate": candidate, "candidate_sha256": digest(candidate),
        "proposed_answer": "A", "potential_grading_method_after_review": "single_choice",
        "human_review_confirmed": False, "can_import": False, "probe_id": None}
    worksheet = {"version": "real-slice-derivation-worksheet-v1", "batch_sha256": digest(batch),
        "questions": [row], "probes": {}}
    return worksheet, batch


def test_hypothetical_parser_success_never_releases_content():
    worksheet, batch = inputs()
    before = deepcopy(worksheet)
    report = audit(worksheet, batch)
    assert report["hypothetical_parser_applicable_count"] == 1
    row = report["questions"][0]
    assert row["current_unverified_verdict"]["result"] == "unknown"
    assert row["hypothetical_parser_verdict_NOT_APPROVAL"]["result"] == "right"
    assert not row["can_release"] and not row["can_produce_objective_evidence"]
    assert worksheet == before
    assert report["review_queues"]["ready_for_human_review"] == ["408-2025-q003"]
    assert report["intake_count"] == report["selected_intake_count"] == 1
    assert report["not_selected_intake_ids"] == []


def test_review_queues_preserve_unselected_and_online_rows_without_approval():
    worksheet, batch = inputs()
    batch["questions"].append({"subject": "408", "year": 2024, "question_number": 7})
    worksheet["batch_sha256"] = digest(batch)
    worksheet["questions"][0]["original_issues"] = ["local_source_year_conflict"]
    record = {"question_type": "fill_blank", "correct_answer": "2", "options": None}
    worksheet["online_integral_review"] = {"questions": [{
        "candidate_id": "math2-2025-q011", "record": record, "record_sha256": digest(record),
        "potential_grading_method_after_review": "numeric_final",
        "human_review_confirmed": False, "can_import": False}]}
    report = audit(worksheet, batch)
    assert report["not_selected_intake_ids"] == ["408-2024-q007"]
    assert report["intake_count"] == 2 and report["selected_intake_count"] == 1
    assert report["review_queues"]["source_conflict"] == ["408-2025-q003"]
    assert report["review_queues"]["ready_for_human_review"] == ["math2-2025-q011"]
    assert sum(map(len, report["review_queues"].values())) == report["count"]
    assert report["verified_count"] == 0 and not report["release_ready"]


@pytest.mark.parametrize("missing_kind,expected_queue", [
    (True, "structure_missing"), (False, "grader_unsupported")])
def test_review_queue_keeps_unsupported_content(missing_kind, expected_queue):
    worksheet, batch = inputs()
    candidate = batch["questions"][0]
    candidate["question_type"] = None if missing_kind else "proof"
    worksheet["questions"][0]["candidate_sha256"] = digest(candidate)
    worksheet["batch_sha256"] = digest(batch)
    report = audit(worksheet, batch)
    assert report["review_queues"][expected_queue] == ["408-2025-q003"]
    assert not report["questions"][0]["can_release"]


@pytest.mark.parametrize("mutation", ["batch", "content", "approval"])
def test_stale_or_forged_inputs_fail_closed(mutation):
    worksheet, batch = inputs()
    if mutation == "batch":
        batch["questions"].append({"subject": "408", "year": 2024, "question_number": 1})
    elif mutation == "content":
        worksheet["questions"][0]["candidate"]["question_type"] = "proof"
    else:
        worksheet["questions"][0]["human_review_confirmed"] = True
    with pytest.raises(ValueError):
        audit(worksheet, batch)


def test_bounded_unbraced_fraction_supported_without_auto_release():
    worksheet, batch = inputs()
    record = {"question_type": "fill_blank", "correct_answer": "$-\\frac14$", "options": None}
    row = {"candidate_id": "math2-2025-q013", "record": record, "record_sha256": digest(record),
        "potential_grading_method_after_review": "numeric_final", "human_review_confirmed": False,
        "can_import": False, "probe_id": None}
    worksheet["online_integral_review"] = {"questions": [row]}
    report = audit(worksheet, batch)
    verdict = report["questions"][1]
    assert verdict["hypothetical_parser_verdict_NOT_APPROVAL"]["result"] == "right"
    assert verdict["current_unverified_verdict"]["result"] == "unknown"
    assert not verdict["can_release"]
    record["correct_answer"] = "-1/4"
    row["record_sha256"] = digest(record)
    assert audit(worksheet, batch)["questions"][1]["hypothetical_supported_method"] == "numeric_final"


def test_failed_real_options_and_probe_are_retained():
    worksheet, batch = inputs()
    row = worksheet["questions"][0]
    row["actual_option_check"] = {"matches_proposal": False}
    row["printed_answer_matches_proposal"] = False
    row["probe_id"] = "missing"
    blockers = audit(worksheet, batch)["questions"][0]["blockers"]
    assert "actual_option_parse_or_derivation_failed" in blockers
    assert "printed_answer_conflicts_with_derivation" in blockers
    assert "derivation_probe_missing_or_failed" in blockers


def test_duplicate_options_and_rows_not_accepted():
    assert options_dict([{"label": "A"}, {"label": "A"}]) is None
    worksheet, batch = inputs()
    worksheet["questions"].append(deepcopy(worksheet["questions"][0]))
    with pytest.raises(ValueError, match="Duplicate worksheet"):
        audit(worksheet, batch)


def test_structural_proposal_cannot_carry_approval():
    worksheet, batch = inputs()
    worksheet["questions"][0]["structural_proposal"] = {"status": "VERIFIED", "can_import": True}
    with pytest.raises(ValueError, match="cannot carry approval"):
        audit(worksheet, batch)


def test_original_source_conflicts_are_explicit_blockers():
    worksheet, batch = inputs()
    conflicts = ["local_source_year_conflict", "local_source_question_number_conflict",
                 "local_source_subject_edition_conflict", "primary_mapping_conversion_conflict"]
    worksheet["questions"][0]["original_issues"] = conflicts
    row = audit(worksheet, batch)["questions"][0]
    assert set(conflicts) <= set(row["blockers"])
    assert not row["can_release"]


def test_clearing_worksheet_notes_does_not_erase_intake_conflicts():
    worksheet, batch = inputs()
    content = worksheet["questions"][0]["candidate"]
    content["issues"] = ["local_source_year_conflict"]
    worksheet["questions"][0]["candidate_sha256"] = digest(content)
    worksheet["questions"][0]["original_issues"] = []
    worksheet["batch_sha256"] = digest(batch)
    row = audit(worksheet, batch)["questions"][0]
    assert "local_source_year_conflict" in row["blockers"]
    assert "local_source_year_conflict" in row["preserved_original_issues"]
