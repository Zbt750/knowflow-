from copy import deepcopy

import pytest

from backend.chat.context_screening import POLICY_VERSION, MIN_COSINE
from scripts.run_ragas_chat_eval import EvalError, validate_screening_snapshot


def snapshot(mode):
    return {"contexts": ["合成依据"], "context_screening": {
        "version": POLICY_VERSION, "threshold": MIN_COSINE, "mode": mode,
        "before_count": 2 if mode == "filter" else 1, "after_count": 1,
        "removed_count": 1 if mode == "filter" else 0,
        "would_remove_count": 1 if mode == "filter" else 0,
        "applied": mode == "filter", "reason": "eligible" if mode == "filter" else "disabled"}}


@pytest.mark.parametrize("mode", ["off", "filter"])
def test_expected_arm_matches_actual_evidence_and_does_not_mutate_snapshot(mode):
    report = snapshot(mode)
    original = deepcopy(report)
    validate_screening_snapshot(report, mode)
    assert original == report


def test_legacy_evaluation_without_arm_remains_supported():
    validate_screening_snapshot({}, None)


@pytest.mark.parametrize("field,value", [
    ("mode", "off"), ("version", "old"), ("threshold", 0.7),
    ("before_count", 5), ("after_count", 2), ("removed_count", -1),
    ("removed_count", True), ("would_remove_count", 0),
    ("applied", False), ("reason", "degraded_retrieval"),
])
def test_wrong_arm_or_unapplied_policy_is_rejected_before_paid_judging(field, value):
    report = snapshot("filter")
    report["context_screening"][field] = value
    with pytest.raises(EvalError):
        validate_screening_snapshot(report, "filter")


def test_off_arm_cannot_hide_filtering_and_missing_diagnostics_do_not_pass():
    report = snapshot("off")
    report["context_screening"].update(before_count=2, removed_count=1)
    with pytest.raises(EvalError):
        validate_screening_snapshot(report, "off")
    with pytest.raises(EvalError):
        validate_screening_snapshot({}, "filter")
