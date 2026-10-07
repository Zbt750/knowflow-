"""All human stamps here are SIMULATED; only isolated PG receives upgrades."""
from copy import deepcopy
from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy import select, func

from backend.models.learning import Question, PracticeItem, DailyPlan, QuestionAttempt, KpState
from backend.services.golden_learning_slice import ASPECTS, digest
from backend.services.question_pack import QuestionPack, fingerprint, import_pack
from backend.services.question_verification_upgrade import build_targets, snapshot, upgrade_transcriptions
from tests.integration.test_learning_loop import session_factory, clean_database, client, clock
from tests.integration.test_answer_submissions import cleanup_answer_records
from tests.integration.test_question_answer_revision import transcribed


def prepared(db):
    old = transcribed()
    import_pack(db, old, apply=True)
    row = db.scalar(select(Question).where(Question.stem == old.questions[0].stem))
    data = old.model_dump(mode="json")
    data["pack_id"] = "SIMULATED-reviewed-upgrade"
    q = data["questions"][0]
    q.update(content_status="reviewed", grading_method="single_choice", answer_reviewed_by="SIMULATED HUMAN ONLY",
             correct_answer="B", explanation="SIMULATED corrected reference; not actual exam certification")
    q["source"]["reviewed_by"] = "SIMULATED HUMAN ONLY"
    pack = QuestionPack.model_validate(data)
    sha = fingerprint(pack.questions[0])
    reviews = {q["source_id"]: {aspect: {"status": "VERIFIED", "reviewer_kind": "human",
        "reviewed_by": "SIMULATED HUMAN ONLY", "reviewed_on": q["source"]["reviewed_on"],
        "content_sha256": sha, "note": "SIMULATED isolated fixture, not a real human approval"} for aspect in ASPECTS}}
    targets = {q["source_id"]: {"question_id": str(row.id), "snapshot_sha256": digest(snapshot(row))}}
    return row, pack, targets, reviews


def test_upgrade_reloads_cached_question_after_external_change(session_factory, clean_database):
    with session_factory() as stale:
        row, pack, targets, reviews = prepared(stale)
        stale.commit()
        qid = row.id
        with session_factory.begin() as other:
            changed = other.get(Question, qid)
            changed.explanation = "Separate maintenance transaction: preserve this content"
        # The original Session intentionally retains its pre-change object.
        with pytest.raises(ValueError, match="changed after upgrade snapshot"):
            upgrade_transcriptions(stale, pack, targets, reviews, apply=True)
        stale.rollback()
    with session_factory() as check:
        saved = check.get(Question, qid)
        assert saved.explanation == "Separate maintenance transaction: preserve this content"
        assert saved.grading_config["verified"] is False


def test_upgrade_reloads_cached_node_after_external_retirement(session_factory, clean_database):
    from backend.models.learning import KnowledgePoint
    with session_factory() as stale:
        row, pack, targets, reviews = prepared(stale)
        node = stale.get(KnowledgePoint, row.kp_id)
        stale.commit()
        with session_factory.begin() as other:
            other.get(KnowledgePoint, node.id).is_active = False
        with pytest.raises(ValueError, match="Inactive"):
            upgrade_transcriptions(stale, pack, targets, reviews, apply=True)
        stale.rollback()


def test_dry_run_upgrade_and_replay_keep_identity(session_factory, clean_database):
    with session_factory() as db:
        row, pack, targets, reviews = prepared(db)
        before = snapshot(row)
        assert build_targets(db, pack) == targets
        count = db.scalar(select(func.count()).select_from(Question))
        preview = upgrade_transcriptions(db, pack, targets, reviews)
        assert preview["upgraded"] == 1 and snapshot(row) == before
        result = upgrade_transcriptions(db, pack, targets, reviews, apply=True)
        assert result["upgraded"] == 1 and not result["history_regraded"]
        assert row.id == UUID(targets["q1"]["question_id"])
        assert row.correct_answer == "B" and row.grading_config["verified"] is True
        assert row.grading_config["verification_revisions"][0]["before"] == before
        with pytest.raises(ValueError, match="Already reviewed"):
            build_targets(db, pack)
        assert db.scalar(select(func.count()).select_from(Question)) == count
        assert upgrade_transcriptions(db, pack, targets, reviews, apply=True)["unchanged"] == 1
        assert len(row.grading_config["verification_revisions"]) == 1
        db.rollback()


@pytest.mark.parametrize("change", ["snapshot", "review", "review_hash", "source_year", "stem", "node", "inactive", "already_verified"])
def test_unsafe_upgrade_rejected_without_partial_mutation(session_factory, clean_database, change):
    with session_factory() as db:
        row, pack, targets, reviews = prepared(db)
        data = pack.model_dump(mode="json")
        if change == "snapshot": targets["q1"]["snapshot_sha256"] = "0" * 64
        if change == "review": reviews["q1"].pop("grading")
        if change == "review_hash": reviews["q1"]["answer"]["content_sha256"] = "0" * 64
        if change == "source_year": data["questions"][0]["source"]["year"] += 1
        if change == "stem": data["questions"][0]["stem"] += " Content version changed"
        if change == "node": data["questions"][0]["kp_code"] = "unknown.node"
        if change in {"source_year", "stem", "node"}:
            pack = QuestionPack.model_validate(data)
            sha = fingerprint(pack.questions[0])
            for value in reviews["q1"].values(): value["content_sha256"] = sha
        if change == "inactive": row.is_active = False
        if change == "already_verified": row.grading_config = {**row.grading_config, "verified": True}
        db.flush()
        before = snapshot(row)
        with pytest.raises(ValueError): upgrade_transcriptions(db, pack, targets, reviews, apply=True)
        assert snapshot(row) == before
        db.rollback()


def test_old_unknown_receipt_never_becomes_verified_evidence(client, session_factory, clock):
    with session_factory.begin() as db:
        row, pack, targets, reviews = prepared(db)
        plan = DailyPlan(study_date="2026-01-01", status="active")
        db.add(plan); db.flush()
        item = PracticeItem(plan_id=plan.id, question_id=row.id, kp_id=row.kp_id, ordinal=1)
        db.add(item); db.flush()
        item_id, kp_id = str(item.id), row.kp_id
    body = {"selected_option": "B", "idempotency_key": "unverified-before-upgrade"}
    old = client.post(f"/api/practice-items/{item_id}/answer-submissions", json=body)
    assert old.status_code == 200 and old.json()["result"] == "unknown"
    with session_factory.begin() as db:
        before_state = deepcopy(db.get(KpState, kp_id).evidence_window)
        upgrade_transcriptions(db, pack, targets, reviews, apply=True)
        assert db.get(KpState, kp_id).evidence_window == before_state
    assert client.post(f"/api/practice-items/{item_id}/answer-submissions", json=body).json() == old.json()
    retry = client.post(f"/api/practice-items/{item_id}/answer-submissions", json={
        "selected_option": "B", "idempotency_key": "after-upgrade-new-request",
        "expected_previous_attempt_id": old.json()["attempt_id"]})
    assert retry.status_code == 409 and retry.json()["error"]["code"] == "answer_question_changed"
    with session_factory() as db:
        attempt = db.get(QuestionAttempt, UUID(old.json()["attempt_id"]))
        assert attempt.objective_result == "unknown"
        assert db.scalar(select(func.count()).select_from(QuestionAttempt)) == 1
        assert db.get(KpState, kp_id).state != "mastered"
    # A fresh practice item may be graded, but old incompatible history cannot
    # be invented into evidence of a known first independent success.
    clock.now += timedelta(days=1)
    with session_factory.begin() as db:
        next_plan = DailyPlan(study_date="2026-01-02", status="active")
        db.add(next_plan); db.flush()
        fresh = PracticeItem(plan_id=next_plan.id, question_id=row.id, kp_id=kp_id, ordinal=1)
        db.add(fresh); db.flush()
        fresh_id = str(fresh.id)
    correct = client.post(f"/api/practice-items/{fresh_id}/answer-submissions", json={
        "selected_option": "B", "idempotency_key": "new-item-after-upgrade"})
    assert correct.status_code == 200 and correct.json()["result"] == "right"
    assert correct.json()["sequence_category"] == "independent_correct_history_unknown"
    assert correct.json()["effective_confirmation_count"] == 0
    detail = client.get(f"/api/knowledge/{kp_id}").json()
    import json
    assert "verification_revisions" not in json.dumps(detail)


def test_batch_failure_does_not_upgrade_first_question(session_factory, clean_database):
    with session_factory() as db:
        row, pack, targets, reviews = prepared(db)
        old_second = transcribed().model_dump(mode="json")
        old_second["questions"][0].update(source_id="q2", stem="SYNTHETIC second question, not a real paper")
        old_second["questions"][0]["source"]["question_number"] = 2
        old_second = QuestionPack.model_validate(old_second)
        import_pack(db, old_second, apply=True)
        second = db.scalar(select(Question).where(Question.stem == old_second.questions[0].stem))
        data = pack.model_dump(mode="json")
        new_second = deepcopy(data["questions"][0])
        new_second.update(source_id="q2", stem=second.stem)
        new_second["source"]["question_number"] = 2
        data["questions"].append(new_second)
        expanded = QuestionPack.model_validate(data)
        reviews["q2"] = deepcopy(reviews["q1"])
        for stamp in reviews["q2"].values(): stamp["content_sha256"] = fingerprint(expanded.questions[1])
        targets["q2"] = {"question_id": str(second.id), "snapshot_sha256": "0" * 64}
        before = [snapshot(row), snapshot(second)]
        with pytest.raises(ValueError, match="changed after"):
            upgrade_transcriptions(db, expanded, targets, reviews, apply=True)
        assert [snapshot(row), snapshot(second)] == before
        db.rollback()


def test_concurrent_replay_applies_upgrade_once(session_factory, clean_database):
    from concurrent.futures import ThreadPoolExecutor
    with session_factory.begin() as db:
        row, pack, targets, reviews = prepared(db)
        qid = row.id
    def apply():
        with session_factory.begin() as db:
            return upgrade_transcriptions(db, pack, targets, reviews, apply=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: apply(), range(2)))
    assert sum(r["upgraded"] for r in results) == 1
    assert sum(r["unchanged"] for r in results) == 1
    with session_factory() as db:
        assert len(db.get(Question, qid).grading_config["verification_revisions"]) == 1


@pytest.mark.parametrize("change", ["old_snapshot", "source_key"])
def test_replay_rejects_corrupted_upgrade_journal(session_factory, clean_database, change):
    with session_factory() as db:
        row, pack, targets, reviews = prepared(db)
        upgrade_transcriptions(db, pack, targets, reviews, apply=True)
        config = deepcopy(row.grading_config)
        if change == "old_snapshot": config["verification_revisions"][0]["before"]["correct_answer"] = "tampered"
        else: config["provenance"]["key"] = "tampered:source"
        row.grading_config = config
        db.flush()
        before = snapshot(row)
        with pytest.raises(ValueError): upgrade_transcriptions(db, pack, targets, reviews, apply=True)
        assert snapshot(row) == before
        db.rollback()


def test_reviewed_content_without_supported_grader_does_not_enable_auto_confirmation(session_factory, clean_database):
    with session_factory() as db:
        row, pack, targets, reviews = prepared(db)
        data = pack.model_dump(mode="json")
        data["questions"][0]["grading_method"] = None
        pack = QuestionPack.model_validate(data)
        for stamp in reviews["q1"].values(): stamp["content_sha256"] = fingerprint(pack.questions[0])
        upgrade_transcriptions(db, pack, targets, reviews, apply=True)
        assert row.grading_config["provenance"]["content_status"] == "reviewed"
        assert row.grading_config["verified"] is False and row.grading_config["method"] is None
        assert row.grading_mode == "self_assessed"
        db.rollback()
