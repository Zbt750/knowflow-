from copy import deepcopy

import pytest

from backend.services.golden_learning_slice import digest
from scripts.prepare_slice_derivation_review import DRAFTS, build_online_integral_review, build_worksheet, orphan_indices, parse_option_array, propose_count_choices, run_probes, simpson
from scripts.prepare_real_slice_review import prepare, template


def batch_fixture():
    return {"version": "structured-real-slice-intake-v1", "questions": [
        {"subject": key.split("-")[0], "year": int(key.split("-")[1]),
         "question_number": int(key.split("-q")[1]), "raw_text": "SYNTHETIC TEST ONLY",
         "issues": ["rights_not_confirmed"], "candidate_node_codes": ["synthetic"]}
        for key in DRAFTS]}


def test_bounded_derivations():
    probes = run_probes()
    assert len(probes) == 13
    assert all(p["passed"] for p in probes.values())
    assert all(not p["certifies_source_or_human_review"] for p in probes.values())
    assert probes["height5_storage"]["detail"]["min_units"] == 16
    assert probes["height5_storage"]["detail"]["worst_case_units"] == 31


def test_no_auto_approval_or_import():
    batch = batch_fixture()
    result = build_worksheet(batch)
    assert result["release_ready"] is False
    assert all(q["review_status"] == "UNVERIFIED" and not q["can_import"] for q in result["questions"])
    assert all(q["original_issues"] == ["rights_not_confirmed"] for q in result["questions"])
    with pytest.raises(ValueError, match="actual human review"):
        prepare(batch, template(batch))


def test_exact_source_hash_and_input_unchanged():
    batch = batch_fixture()
    original = deepcopy(batch)
    result = build_worksheet(batch)
    assert batch == original
    assert result["batch_sha256"] == digest(batch)
    changed = deepcopy(batch)
    changed["questions"][0]["raw_text"] += " CHANGED"
    revised = build_worksheet(changed)
    assert result["questions"][0]["candidate_sha256"] != revised["questions"][0]["candidate_sha256"]


def test_missing_and_duplicate_fail_closed():
    batch = batch_fixture()
    batch["questions"].pop()
    with pytest.raises(ValueError, match="Missing required"):
        build_worksheet(batch)
    batch = batch_fixture()
    batch["questions"].append(deepcopy(batch["questions"][0]))
    with pytest.raises(ValueError, match="Duplicate"):
        build_worksheet(batch)


def test_basic_probe_boundaries():
    assert orphan_indices([1, -1, 2, 3]) == [3]
    assert simpson(lambda x: x * x, 0, 1, 2) == pytest.approx(1 / 3)
    with pytest.raises(ValueError):
        simpson(lambda x: x, 0, 1, 3)


@pytest.mark.parametrize("text", ["R[] = {1, -1, 3}", "[1, -1, 3]"])
def test_source_array_formats(text):
    assert parse_option_array(text) == [1, -1, 3]


def test_option_parse_failure_not_success():
    batch = batch_fixture()
    candidate = next(q for q in batch["questions"] if q["year"] == 2025)
    candidate["options"] = [{"label": "A", "text": "unreadable"}]
    row = next(q for q in build_worksheet(batch)["questions"] if "actual_option_check" in q)
    assert not row["actual_option_check"]["matches_proposal"]
    assert parse_option_array("[__import__('os').system('evil')]") is None


def test_online_review_does_not_certify_existing_ai_answers():
    row = {"stem": "设 $\\int_1^{+\\infty}\\frac{3}{x(2x+a)}dx=\\ln2$，则 $a=$____。", "grading_config": {"verified": False, "provenance": {"source": {"year": 2025, "question_number": 11}}}}
    report = build_online_integral_review([row])
    assert report["questions"][0]["ai_proposed_answer"] == "6"
    assert not report["questions"][0]["can_enable_grading"]
    assert len(report["missing_expected_identities"]) == 4
    with pytest.raises(ValueError, match="Duplicate online"):
        build_online_integral_review([row, row])


@pytest.mark.parametrize("stem,answer,probe", [
    ("设 $\\int_1^{+\\infty}\\frac{a}{x(2x+a)}\\,dx=\\ln2$，则 $a=$____。", "2", "improper_parameter2"),
    ("Unrecognized content with the same year and number", None, None),
    (None, None, None),
])
def test_q011_derivation_is_content_bound(stem, answer, probe):
    row = {"stem": stem, "grading_config": {"provenance": {"source": {"year": 2025, "question_number": 11}}}}
    before = deepcopy(row)
    result = build_online_integral_review([row])["questions"][0]
    assert result["ai_proposed_answer"] == answer
    assert result["probe_id"] == probe
    assert result["human_review_confirmed"] is False
    assert result["can_enable_grading"] is False
    if answer is None:
        assert result["potential_grading_method_after_review"] is None
    assert row == before


def test_count_option_structure_is_draft_only_and_fail_closed():
    proposal = propose_count_choices("SYNTHETIC ONLY\nA. 0\nB. 1\nC. 2\nD. 3\n")
    assert proposal["proposed_options"] == {"A": "0", "B": "1", "C": "2", "D": "3"}
    assert proposal["status"] == "UNVERIFIED" and not proposal["can_import"]
    assert propose_count_choices("A. 0\nA. 1\nC. 2\nD. 3") is None
    assert propose_count_choices("A. 0\nB. 1\nC. 2") is None
