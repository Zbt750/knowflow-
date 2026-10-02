"""Synthetic assets remain unverified even after arithmetic and comparator checks."""
from copy import deepcopy
from datetime import date
from fractions import Fraction
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.services.golden_learning_slice import ASPECTS, GoldenSlice, Review, audit_slice, reviewed_pack
from scripts.audit_golden_learning_slice import audit_files, render_review_sheet

ROOT = Path(__file__).resolve().parents[2]
ASSET = ROOT / "eval/golden/integral_binary_tree_v1.json"


def load_asset():
    return GoldenSlice.model_validate_json(ASSET.read_text(encoding="utf-8"))


def attest_for_test(asset):
    """SIMULATED human review for protocol testing only; never saves to files/DB."""
    data = asset.model_dump(mode="json")
    for q, row in zip(asset.questions, data["questions"]):
        row["reviews"] = {aspect: {"status": "VERIFIED", "reviewer_kind": "human",
            "reviewed_by": "SIMULATED TEST REVIEWER - NOT AN ACTUAL CONTENT REVIEW",
            "reviewed_on": date.today().isoformat(), "content_sha256": q.content_hash(),
            "note": "Isolated protocol fixture, not a real certification"} for aspect in ASPECTS}
    return GoldenSlice.model_validate(data)


def integrate_polynomial(coefficients, lower, upper):
    return sum((Fraction(c, i + 1) * (Fraction(upper) ** (i + 1) - Fraction(lower) ** (i + 1))
                for i, c in enumerate(coefficients)), Fraction(0))


def test_independent_finite_oracles_for_the_supported_answers():
    # Separate algorithms/formulas, not a comparison of the stored answer with itself.
    # These check this finite dataset only and do not confer VERIFIED status.
    answers = {
        "M01": integrate_polynomial([0, 0, 1], 0, 1),
        "M02": integrate_polynomial([0, 0, 0, 1], -1, 1),
        "M03": integrate_polynomial([1, 0, 3], 0, 2),
        "M04": integrate_polynomial([0, 2, 0, 2], 0, 1),
        "M05": integrate_polynomial([0, 1, -1], 0, 1),
        "M06": integrate_polynomial([0, -1], -1, 0) + integrate_polynomial([0, 1], 0, 1),
        "T01": 7 + 1, "T02": 5 + 3 + (5 - 1), "T03": 2 ** 4 - 1,
        "T04": sum(2 * i > 13 for i in range(1, 14)),
        "T05": 2 * 5 - (5 - 1), "T07": 4,
    }
    asset = load_asset()
    for q in asset.questions:
        c = q.content
        if c.source_id in answers:
            answer = c.options[c.correct_answer] if c.options else c.correct_answer
            assert Fraction(answer) == answers[c.source_id]
    adjacency = {"A": ("B", "C"), "B": ("D", "E"), "C": (), "D": (), "E": ()}
    def preorder(node):
        return [node] + [n for child in adjacency[node] for n in preorder(child)]
    c = next(q.content for q in asset.questions if q.content.source_id == "T06")
    assert c.options[c.correct_answer].split() == preorder("A")
    assert not any(q.verified for q in asset.questions)


def test_audit_passes_without_promoting_generated_assets():
    asset = load_asset()
    before = asset.model_dump(mode="json")
    report = audit_files(asset)
    assert report["structural_checks_passed"]
    assert report["answerable_drafts"] == 16 and report["verified_questions"] == 0
    assert report["proposed_methods"] == {"numeric_final": 9, "single_choice": 4, "manual_only": 3}
    assert not report["release_ready"] and not report["human_review_complete"]
    assert all(r["actual_gate_result"] == "unknown" for r in report["cases"])
    assert before == asset.model_dump(mode="json")
    with pytest.raises(ValueError, match="human review incomplete"):
        reviewed_pack(asset)


@pytest.mark.parametrize("aspect", sorted(ASPECTS))
def test_every_aspect_is_required_for_export(aspect):
    data = attest_for_test(load_asset()).model_dump(mode="json")
    data["questions"][0]["reviews"][aspect] = {"status": "UNVERIFIED"}
    with pytest.raises(ValueError, match="human review incomplete"):
        reviewed_pack(GoldenSlice.model_validate(data))


@pytest.mark.parametrize("field,value", [("correct_answer", "2/3"), ("explanation", "修改后的候选解析"),
    ("stem", "修改后的题目内容"), ("kp_code", "other.node"), ("grading_method", None)])
def test_edited_reviewed_content_invalidates_stamps(field, value):
    data = attest_for_test(load_asset()).model_dump(mode="json")
    data["questions"][0]["content"][field] = value
    with pytest.raises(ValidationError): GoldenSlice.model_validate(data)


def test_verified_label_alone_is_not_a_review():
    with pytest.raises(ValidationError, match="human review attestation"):
        Review(status="VERIFIED")
    data = load_asset().model_dump(mode="json")
    data["questions"][0]["reviews"]["answer"] = {"status": "VERIFIED"}
    with pytest.raises(ValidationError): GoldenSlice.model_validate(data)


@pytest.mark.parametrize("change", ["duplicate_id", "duplicate_node", "outside_scope", "missing_aspect", "source", "probe"])
def test_asset_boundaries(change):
    data = attest_for_test(load_asset()).model_dump(mode="json")
    if change == "duplicate_id": data["questions"].append(deepcopy(data["questions"][0]))
    if change == "duplicate_node": data["topics"].append(deepcopy(data["topics"][0]))
    if change == "outside_scope": data["questions"][0]["content"]["kp_code"] = "outside.scope"
    if change == "missing_aspect": del data["questions"][0]["reviews"]["mapping"]
    if change == "source": data["questions"][0]["source"]["citation"] = "另一份来源"
    if change == "probe": data["questions"][0]["probes"][0]["result"] = "wrong"
    with pytest.raises(ValidationError): GoldenSlice.model_validate(data)


def test_only_simulated_fully_reviewed_questions_export_with_manual_boundaries():
    pack = reviewed_pack(attest_for_test(load_asset()))
    assert len(pack.questions) == 16
    assert sum(q.grading_method is None for q in pack.questions) == 3
    assert all("SIMULATED" in q.answer_reviewed_by for q in pack.questions)


def test_wrong_probe_fails_even_if_simulated_review_is_complete():
    data = load_asset().model_dump(mode="json")
    data["questions"][0]["probes"][0]["result"] = "wrong"
    asset = attest_for_test(GoldenSlice.model_validate(data))
    assert not audit_slice(asset)["all_probes_passed"]
    with pytest.raises(ValueError, match="grading probes failed"):
        reviewed_pack(asset)


def test_missing_or_changed_lesson_prevents_release(tmp_path):
    report = audit_files(load_asset(), root=tmp_path)
    assert not report["structural_checks_passed"]
    assert all(not t["lesson_hash_matches"] for t in report["topics"])


def test_review_sheet_keeps_every_candidate_and_the_unverified_boundary():
    asset = load_asset()
    sheet = render_review_sheet(asset, audit_files(asset))
    assert sheet.count("### ") == 16
    assert "GENERATED" in sheet and "不自动判分" in sheet
    assert "不是历年真题" in sheet and "隔离模拟" in sheet
    assert sheet == render_review_sheet(asset, audit_files(asset))


def test_future_review_and_lesson_hash_mismatch_are_rejected():
    with pytest.raises(ValidationError, match="future"):
        Review(status="UNVERIFIED", reviewed_on="2999-01-01")
    data = load_asset().model_dump(mode="json")
    data["topics"][0]["lesson_review"] = {"status": "VERIFIED", "reviewer_kind": "human",
        "reviewed_by": "SIMULATED", "reviewed_on": date.today().isoformat(),
        "content_sha256": "0" * 64, "note": "Simulated stale lesson review"}
    with pytest.raises(ValidationError, match="lesson review hash mismatch"):
        GoldenSlice.model_validate(data)
