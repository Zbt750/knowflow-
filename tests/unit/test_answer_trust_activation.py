from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.mastery.enums import EventType, MasteryState, SelfGrade
from backend.mastery.evidence import classify_evidence, classify_objective_evidence
from backend.mastery.policy import MasteryPolicy
from backend.mastery.rules import graduation_check
from backend.mastery.transition import transition
from backend.mastery.types import DomainLearningEvent, MasterySnapshot
from scripts import answer_trust_migration_preflight as preflight
from scripts.activate_answer_trust_migration import verify_inputs


@pytest.mark.parametrize("env,host,db", [
    ("prod", "localhost", "kaoyan"), ("test", "localhost", "kaoyan_test"),
    ("dev", "example.org", "kaoyan"), ("dev", "localhost", "other"),
])
def test_activation_guard_refuses_other_databases(env, host, db):
    with pytest.raises(ValueError, match="local"):
        preflight.local_database_url(SimpleNamespace(app_env=env,
            active_database_url=f"postgresql+psycopg://user:placeholder@{host}/{db}"))


def test_fingerprint_detects_changed_content_even_if_counts_match():
    before = {"tables": {"questions": {"rows": 2, "sha256": "old"}}}
    assert preflight.compare_fingerprints(before, before)["passed"]
    after = {"tables": {"questions": {"rows": 2, "sha256": "new"}}}
    assert preflight.compare_fingerprints(before, after) == {
        "passed": False, "changed_existing_tables": ["questions"],
        "unexpected_data_tables": [], "protected_table_count": 1}
    assert not preflight.compare_fingerprints(before, {"tables": {}})["passed"]
    assert not preflight.compare_fingerprints(before, {"tables": {
        **before["tables"], "unexpected": {"rows": 0, "sha256": "empty"}}})["passed"]


def test_private_reports_cannot_overwrite_or_escape(tmp_path, monkeypatch):
    monkeypatch.setattr(preflight, "ROOT", tmp_path)
    target = tmp_path / "storage/answer-trust/before.json"
    assert preflight.private_output(target) == target
    with pytest.raises(ValueError):
        preflight.private_output(tmp_path / "outside.json")
    target.parent.mkdir(parents=True)
    target.touch()
    with pytest.raises(ValueError):
        preflight.private_output(target)


def test_activation_requires_matching_restore_of_expected_backup():
    before = {"format": preflight.FORMAT, "phase": "before", "passed": True,
        "revision": preflight.PREVIOUS, "tables": {"questions": {"rows": 518}}}
    recovery = {"restore_passed": True, "cleanup_passed": True,
        "database_sha256": "backup-sha", "restored_migration_revision": preflight.PREVIOUS,
        "development_database_modified": False, "restored_row_counts": {"questions": 518}}
    verify_inputs(before, recovery, {"database_sha256": "backup-sha"})
    for changed in (
        {**recovery, "restore_passed": False},
        {**recovery, "cleanup_passed": False},
        {**recovery, "database_sha256": "different"},
        {**recovery, "restored_row_counts": {"questions": 519}},
    ):
        with pytest.raises(ValueError):
            verify_inputs(before, changed, {"database_sha256": "backup-sha"})


def _empty():
    return MasterySnapshot(MasteryState.UNSEEN, (), 0, None, None, None, 0, None)


def test_verified_online_exam_answers_do_not_satisfy_external_record_quota():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    window = tuple(classify_objective_evidence(result="right", verified=True,
        assisted=False, question_id=f"online-{i}", is_variant=False,
        occurred_at=start + timedelta(days=i), question_type="single_choice",
        skill_tags=("tree",)) for i in range(3))
    policy = MasteryPolicy(min_confirmations=3, min_real_questions=3,
        required_question_types={"external_exam": 3}, required_variant_count=0,
        required_skill_tags=frozenset({"tree"}), min_day_span=2)
    result = graduation_check(window, manual_credit_count=0,
        manual_confirmed_at=None, policy=policy)
    assert result == (False, "missing_question_type:external_exam")
    assert all(e.question_type == "single_choice" and e.source == "objective_final" for e in window)


def test_new_paper_reference_self_report_never_grants_external_confirmation():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    evidence = classify_evidence(self_grade=SelfGrade.MASTERED, question_id="reference",
        is_variant=False, occurred_at=now, question_type="external_exam")
    result = transition(_empty(), DomainLearningEvent(EventType.PRACTICE_SELF_REPORTED,
        now, SelfGrade.MASTERED, evidence), MasteryPolicy())
    assert result.reason_code == "self_feedback_only"
    assert result.snapshot.evidence_window == ()
    assert result.snapshot.manual_credit_count == 0


@pytest.mark.parametrize("verified,assisted,reliability", [
    (True, True, "verified_objective"), (False, False, "ai_consistent_objective"),
])
def test_assisted_and_ai_consistent_paths_cannot_produce_confirmation(verified, assisted, reliability):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    evidence = classify_objective_evidence(result="right", verified=verified,
        assisted=assisted, question_id="test", is_variant=False, occurred_at=now,
        question_type="single_choice", evidence_reliability=reliability)
    result = transition(_empty(), DomainLearningEvent(EventType.ANSWER_SUBMITTED,
        now, evidence=evidence, payload={"assisted": assisted}), MasteryPolicy())
    assert result.snapshot.evidence_window == ()

