import pytest

from scripts.audit_real_learning_slices import SLICE_SCOPES, build_report


def supply():
    return {"created_at": "synthetic-snapshot", "nodes": [{"code": code, "name": code, "path": code,
        "online": 1, "automatic_grading": 0}
        for scope in SLICE_SCOPES.values() for code in [scope["primary"], *scope["related"]]]}


def test_cross_node_reference_is_deduplicated_without_merging_nodes(tmp_path):
    codes = SLICE_SCOPES["integral"]
    refs = [{"knowledge_point_code": c, "subject": "math2", "year": 2025,
             "question_number": 12, "question_source_url": "https://example.invalid/source"}
            for c in [codes["primary"], codes["related"][0], codes["primary"]]]
    row = build_report(supply(), refs, tmp_path)["slices"][0]
    assert row["unique_source_pointers"] == 1
    assert len(row["source_pointers"][0]["candidate_node_codes"]) == 2
    assert row["online_questions"] == 5
    assert row["verified_question_count"] is None
    assert not row["release_ready"]
    assert row["normalization"] == "scope_only_no_alias_merge_no_evidence_pooling"


def test_missing_node_rejects_stale_or_incompatible_snapshot(tmp_path):
    snapshot = supply()
    snapshot["nodes"].pop()
    with pytest.raises(ValueError, match="missing"):
        build_report(snapshot, [], tmp_path)


def test_subject_and_year_are_part_of_reference_identity(tmp_path):
    code = SLICE_SCOPES["binary_tree"]["primary"]
    refs = [{"knowledge_point_code": code, "subject": "408", "year": year, "question_number": 1}
            for year in [2024, 2025]]
    row = build_report(supply(), refs, tmp_path)["slices"][1]
    assert row["unique_source_pointers"] == 2
    assert all(not p["source_urls"] for p in row["source_pointers"])


def test_lesson_existence_and_hash_do_not_claim_verification(tmp_path):
    code = SLICE_SCOPES["integral"]["primary"]
    folder = tmp_path / "seed" / "lessons"
    folder.mkdir(parents=True)
    (folder / f"{code}.md").write_text("# Synthetic lesson", encoding="utf-8")
    node = build_report(supply(), [], tmp_path)["slices"][0]["nodes"][0]
    assert node["lesson_exists"] and len(node["lesson_sha256"]) == 64
    assert node["lesson_verification"] == "not_established_by_this_audit"
