from copy import deepcopy

import pytest

from backend.services.golden_learning_slice import digest
from scripts.stage_online_review_intake import build_intake
from scripts.prepare_real_slice_review import prepare, template


def fixture():
    record = {"id": "synthetic", "kp_code": "synthetic.math", "stem": "SYNTHETIC ONLY",
        "question_type": "fill_blank", "correct_answer": "1", "grading_config": {"verified": False,
        "provenance": {"source": {"source_type": "exam", "subject": "数学二", "year": 2025, "question_number": 1}}}}
    return {"version": "real-slice-derivation-worksheet-v1", "online_integral_review": {"questions": [
        {"candidate_id": "math2-2025-q001", "record": record, "record_sha256": digest(record)}]}}


def test_snapshot_intake_cannot_certify():
    worksheet = fixture()
    before = deepcopy(worksheet)
    batch = build_intake(worksheet)
    assert not batch["questions"][0]["verified"] and not batch["questions"][0]["can_import"]
    assert worksheet == before
    with pytest.raises(ValueError, match="actual human review"):
        prepare(batch, template(batch))


@pytest.mark.parametrize("change", ["stale", "identity", "duplicate", "empty"])
def test_bad_snapshot_intake_rejected(change):
    worksheet = fixture()
    rows = worksheet["online_integral_review"]["questions"]
    if change == "stale": rows[0]["record"]["stem"] += " EDIT"
    if change == "identity": rows[0]["candidate_id"] = "math2-2025-q099"
    if change == "duplicate": rows.append(deepcopy(rows[0]))
    if change == "empty": rows.clear()
    with pytest.raises(ValueError): build_intake(worksheet)
