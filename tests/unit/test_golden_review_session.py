"""SIMULATED declarations only; no real review package or development DB writes."""
from copy import deepcopy
from uuid import uuid4

import pytest

from backend.services.golden_learning_slice import digest
from backend.services.golden_review_session import (
    ORDER, ISSUES, configure, new_draft, record_review, export_bundle,
    save_revision, restore, grader_probes, material_index, private_directory,
)
from scripts.prepare_real_slice_review import prepare
from backend.services.question_verification_upgrade import validate_reviews
from scripts.review_golden_slice import interactive


def fixture_view(kind="single_choice"):
    view = {"question_id": str(uuid4()), "content": {
        "question_type": kind, "stem": "TEST_FIXTURE synthetic arithmetic question",
        "options": {"A": "1", "B": "2", "C": "3"} if kind == "single_choice" else None,
        "correct_answer": "A" if kind == "single_choice" else "1",
        "explanation": "TEST_FIXTURE synthetic explanation, never exam certification",
        "question_role": "basic", "difficulty": "basic", "estimated_minutes": 2,
        "skill_tags": ["TEST_FIXTURE"], "is_variant": False},
        "source": {"kind": "user_provided", "source_type": "exam", "year": 2025,
            "question_number": 6 if kind == "single_choice" else 11, "subject": "math2",
            "paper_title": "SIMULATED TEST exam", "citation": "SIMULATED source fixture",
            "rights_basis": "SIMULATED local permission fixture", "reviewed_by": "TEST INTAKE",
            "reviewed_on": "2026-01-01"},
        "node": {"id": str(uuid4()), "code": "math.synthetic", "name": "TEST_FIXTURE", "active": True, "assessable": True},
        "snapshot": {"TEST_FIXTURE": True}, "question_content_sha256": "1" * 64,
        "answer_version_sha256": "2" * 64, "snapshot_sha256": digest({"TEST_FIXTURE": True}),
        "eligibility": {}, "material": {}, "source_file": {"status": "not_supplied"},
        "hard_blockers": [], "issues": [i for group in ISSUES.values() for i in group]}
    view["binding_sha256"] = digest(view)
    return view


def configured(view=None):
    view = view or fixture_view()
    draft = new_draft([view])
    row = draft["questions"][0]
    configure(row, reviewer="SIMULATED TEST OPERATOR", citation="SIMULATED reviewed source",
        rights_basis="SIMULATED local-only use", answer_note="SIMULATED independent solution note",
        method="single_choice" if view["content"]["question_type"] == "single_choice" else "numeric_final")
    return draft, row


def completed(view=None):
    draft, row = configured(view)
    for aspect in ORDER:
        record_review(row, aspect, "VERIFIED", row["proposal"]["answer_review_note"] if aspect == "answer" else "SIMULATED per-aspect review note")
    row["resolutions"] = {i: "SIMULATED specific issue resolution" for i in row["resolutions"]}
    return draft, row


def test_new_draft_and_preparation_never_approve():
    draft, row = configured()
    assert draft["human_review_confirmed"] is False
    assert all(r["status"] == "PENDING" for r in row["reviews"].values())
    record_review(row, "stem", "VERIFIED", "SIMULATED stem review only")
    assert row["reviews"]["stem"]["status"] == "VERIFIED"
    assert row["reviews"]["answer"]["status"] == "PENDING"


@pytest.mark.parametrize("status", ["PENDING", "REJECTED"])
def test_incomplete_or_rejected_cannot_export(status):
    draft, row = completed()
    record_review(row, "grading", status, "SIMULATED not approved")
    with pytest.raises(ValueError, match="Incomplete"):
        export_bundle(draft, [row["view"]])


@pytest.mark.parametrize("status", ["", "yes", "ALL", "UNVERIFIED"])
def test_no_enter_default_or_all_pass(status):
    _, row = configured()
    with pytest.raises(ValueError, match="Explicit"):
        record_review(row, "source", status, "SIMULATED note")
    assert all(r["status"] == "PENDING" for r in row["reviews"].values())


def test_missing_reviewer_cannot_prepare():
    row = new_draft([fixture_view()])["questions"][0]
    with pytest.raises(ValueError, match="reviewer"):
        configure(row, reviewer=" ", citation="TEST source", rights_basis="TEST local",
            answer_note="TEST answer note", method="single_choice")


@pytest.mark.parametrize("status", ["VERIFIED", "REJECTED", "PENDING"])
def test_any_explicit_review_needs_configured_identity(status):
    row = new_draft([fixture_view()])["questions"][0]
    with pytest.raises(ValueError):
        record_review(row, "source", status, "SIMULATED decision without reviewer")
    assert row["reviews"]["source"] == {"status": "PENDING", "note": ""}


def test_rejected_decision_has_real_operator_and_version_fields():
    _, row = configured()
    record_review(row, "source", "REJECTED", "SIMULATED source mismatch")
    stamp = row["reviews"]["source"]
    assert stamp["reviewed_by"] == "SIMULATED TEST OPERATOR"
    assert stamp["content_sha256"] == row["proposal_sha256"] and stamp["reviewed_on"]


@pytest.mark.parametrize("field", ["content", "answer_version_sha256", "snapshot_sha256", "source_file", "node"])
def test_live_drift_rejects_old_signoff(field):
    draft, row = completed()
    current = deepcopy(row["view"])
    current[field] = {"changed": True} if isinstance(current[field], dict) else "0" * 64
    current["binding_sha256"] = digest({k: v for k, v in current.items() if k != "binding_sha256"})
    with pytest.raises(ValueError, match="drift"):
        export_bundle(draft, [current])


def test_q6_old_negative_sign_fingerprint_rejected():
    current = fixture_view()
    current["content"]["options"]["C"] = "$-1/\\ln2$"
    current["binding_sha256"] = digest({k: v for k, v in current.items() if k != "binding_sha256"})
    draft, row = completed(current)
    old = deepcopy(row["view"])
    old["content"]["options"]["C"] = "$1/\\ln2$"
    old["answer_version_sha256"] = "d" * 64
    old["binding_sha256"] = digest({k: v for k, v in old.items() if k != "binding_sha256"})
    draft["questions"][0]["view"] = old
    with pytest.raises(ValueError, match="drift"):
        export_bundle(draft, [current])


def test_resume_keeps_every_decision_and_old_files(tmp_path):
    root = tmp_path
    directory = root / "storage/answer-trust/test"
    draft, row = configured()
    record_review(row, "source", "REJECTED", "SIMULATED source discrepancy")
    first = save_revision(draft, directory, root)
    original = first.read_bytes()
    second = save_revision(draft, directory, root)
    resumed = restore(second, [row["view"]], root)
    assert resumed == draft
    assert first != second and first.read_bytes() == original
    assert resumed["questions"][0]["reviews"]["source"]["status"] == "REJECTED"


def test_saved_draft_corruption_rejected(tmp_path):
    import json
    draft, row = configured()
    path = save_revision(draft, tmp_path / "storage/answer-trust/test", tmp_path)
    payload = json.loads(path.read_text())
    payload["draft"]["questions"][0]["reviews"]["source"]["status"] = "VERIFIED"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="integrity"):
        restore(path, [row["view"]], tmp_path)


@pytest.mark.parametrize("kind", ["single_choice", "fill_blank"])
def test_simulated_export_accepted_by_existing_strict_contract(kind):
    draft, row = completed(fixture_view(kind))
    before = deepcopy(draft)
    bundle = export_bundle(draft, [row["view"]])
    pack = prepare(bundle["batch"], bundle["decisions"])
    q = pack.questions[0]
    validate_reviews(q, bundle["decisions"]["questions"][0]["reviews"])
    assert q.answer_provenance == "human_verified"
    assert bundle["targets"][q.source_id]["question_id"] == row["view"]["question_id"]
    assert not bundle["database_written"] and draft == before


def test_unresolved_issue_cannot_export():
    draft, row = completed()
    row["resolutions"]["source_identity_and_locator"] = ""
    with pytest.raises(ValueError, match="unresolved"):
        export_bundle(draft, [row["view"]])


def test_changing_source_or_reviewer_resets_old_signoffs():
    draft, row = completed()
    configure(row, reviewer="SIMULATED SECOND OPERATOR", citation="SIMULATED new precise locator",
        rights_basis="SIMULATED local use", answer_note="SIMULATED new solution note", method="single_choice")
    assert all(r["status"] == "PENDING" for r in row["reviews"].values())
    assert all(not r for r in row["resolutions"].values())


def test_proposal_content_change_rejected_even_with_rehashed_fingerprint():
    from backend.services.question_pack import PackQuestion, fingerprint
    draft, row = completed()
    row["proposal"]["options"]["C"] = "modified"
    row["proposal_sha256"] = fingerprint(PackQuestion.model_validate(row["proposal"]))
    with pytest.raises(ValueError, match="cannot correct"):
        export_bundle(draft, [row["view"]])


def test_actual_numeric_boundary_no_tolerance_and_unsupported_unknown():
    probes = grader_probes(fixture_view("fill_blank"), "numeric_final")
    assert probes["passed"] and probes["harness_only"] and not probes["grants_verified_grader"]
    checks = {c["case"]: c["actual"] for c in probes["cases"]}
    assert checks["no_tolerance"] == "wrong"
    assert checks["expression"] == checks["illegal"] == checks["blank"] == "unknown"
    assert checks["equivalent_integer"] == checks["equivalent_decimal"] == checks["equivalent_fraction"] == "right"


def test_actual_single_choice_boundaries():
    probes = grader_probes(fixture_view(), "single_choice")
    assert probes["passed"]
    checks = {c["case"]: c["actual"] for c in probes["cases"]}
    assert checks["case_and_spaces"] == "right"
    assert checks["illegal"] == checks["free_text_not_option"] == "unknown"


def test_enter_in_interactive_does_not_approve():
    draft = new_draft([fixture_view()])
    replies = iter(["1", "1", "", "b", "q"])
    saved = []
    assert interactive(draft, lambda d: saved.append(deepcopy(d)), lambda _: next(replies), lambda _: None) == "quit"
    assert saved and all(r["status"] == "PENDING" for r in draft["questions"][0]["reviews"].values())


def test_corrected_q6_locator_overrides_only_stale_q6_material():
    index = material_index({"questions": [{"question_id": "q6", "declared_original_source_file": "old"},
        {"question_id": "q7", "declared_original_source_file": "keep"}]},
        {"question_id": "q6", "source": {"pdf_path": "new", "pdf_sha256": "a" * 64, "page": 2, "question_number": 6},
         "hashes": {"answer_version_sha256": "b" * 64}})
    assert index["q6"]["path"] == "new" and index["q7"]["path"] == "keep"


def test_public_or_symlink_escape_rejected(tmp_path):
    with pytest.raises(ValueError, match="private"):
        private_directory(tmp_path / "docs", tmp_path)


def test_unresolved_q7_page_range_cannot_export_even_with_checkmarks():
    v = fixture_view()
    v["source"]["citation"] = "SIMULATED PDF 第 2–3 页; exact locator pending"
    v["issues"].append("page_range_conflict_p2_vs_p2_3")
    v["binding_sha256"] = digest({k: val for k, val in v.items() if k != "binding_sha256"})
    draft, row = completed(v)
    # Even complete simulated signoffs cannot silently retain the old locator.
    row["proposal"]["source"]["citation"] = v["source"]["citation"]
    from backend.services.question_pack import PackQuestion, fingerprint
    sha = fingerprint(PackQuestion.model_validate(row["proposal"]))
    row["proposal_sha256"] = sha
    for r in row["reviews"].values():
        r["content_sha256"] = sha
    with pytest.raises(ValueError, match="page conflict"):
        export_bundle(draft, [v])


def test_main_partial_draft_cannot_emit_bundle(tmp_path, monkeypatch):
    import scripts.review_golden_slice as cli
    draft, row = configured()
    path = save_revision(draft, tmp_path / "storage/answer-trust/test", tmp_path)
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(cli, "read_live", lambda *a, **kw: ([row["view"]], {"transaction_read_only": "on"}, None))
    with pytest.raises(ValueError, match="Incomplete"):
        cli.main(["--resume", str(path), "--export", "--output-dir", str(path.parent)])
    assert not list(path.parent.glob("bundle-*"))


def test_main_complete_simulated_draft_exports_new_bundle_without_rewriting(tmp_path, monkeypatch):
    import scripts.review_golden_slice as cli
    draft, row = completed()
    path = save_revision(draft, tmp_path / "storage/answer-trust/test", tmp_path)
    original = path.read_bytes()
    expected = export_bundle(draft, [row["view"]])["targets"]
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(cli, "read_live", lambda *a, **kw: ([row["view"]], {"transaction_read_only": "on"}, expected if kw.get("approved_pack") else None))
    assert cli.main(["--resume", str(path), "--export", "--output-dir", str(path.parent)]) == 0
    assert path.read_bytes() == original
    out = next(path.parent.glob("bundle-*"))
    assert {p.name for p in out.iterdir()} == {"batch.json", "decisions.json", "targets.json", "pack.json", "manifest.json"}
