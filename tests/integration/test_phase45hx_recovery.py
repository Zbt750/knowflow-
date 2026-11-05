"""Local archived content replay; all learner data are isolated TEST_FIXTUREs."""
import json
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from backend.models.learning import DailyPlan, KnowledgePoint, Question, QuestionAttempt
from backend.services.auto_question_review import (
    AUTO_REVIEW_VERSION, prepare_exam_curated_repair, qualify_public_question, question_snapshot_sha256,
)
from backend.services.graduation_question_set import freeze_graduation_question_set
from backend.services.question_pack import QuestionPack, import_pack
from backend.services.question_eligibility import question_eligibility
from scripts.audit_phase45h_completion_archive import source_pack_evidence
from backend.services.question_repair import local_pack_registry
from tests.integration.test_learning_loop import clean_database, session_factory, client, clock, generate_plan

ROOT = Path(__file__).resolve().parents[2]
PACK_ROOT = ROOT / "storage/question-intake/phase45hx-20261010"


@pytest.mark.parametrize("pack_name,index", [("phase45hx-408-2016-v1.json", 0),
    ("phase45hx-math2-2016-v1.json", 0), ("phase45hx-math2-2016-v1.json", 1),
    ("phase45hx-math2-2016-v1.json", 2)])
def test_recovered_exam_runs_normal_review_today_answer_and_v3_completion(
        session_factory, clean_database, client, clock, pack_name, index):
    path = PACK_ROOT / pack_name
    if not path.exists():
        pytest.skip("Private historical source pack is not distributed")
    full_pack = QuestionPack.model_validate(json.loads(path.read_text(encoding="utf-8")))
    pack = QuestionPack(pack_id=full_pack.pack_id, version=full_pack.version, questions=[full_pack.questions[index]])
    registry, _ = local_pack_registry(ROOT)
    with session_factory() as db:
        # The ordinary seed fixture omits archived topic leaves. Reuse the
        # production index sync in this empty TEST_FIXTURE DB to materialize
        # the same real node code and its current compatible policy.
        from backend.services.exam_reference_service import sync_exam_reference_index
        sync_exam_reference_index(db)
        db.flush()
        preview = import_pack(db, pack, apply=False)
        assert preview["new"] == 1
        inserted = import_pack(db, pack, apply=True)
        assert inserted["new"] == 1
        question = db.scalar(select(Question).where(
            Question.grading_config["provenance"]["key"].as_string()
            == f"{pack.pack_id}:{pack.questions[0].source_id}"))
        node = db.get(KnowledgePoint, question.kp_id)
        assert node.code == pack.questions[0].kp_code
        assert not question_eligibility(question, node).auto_review_current
        source = source_pack_evidence(question, registry, node)
        assert source is not None
        prepare_exam_curated_repair(question, node, source)
        db.flush()
        source = source_pack_evidence(question, registry, node)
        expected = question_snapshot_sha256(question)
        key = f"TEST_FIXTURE-hx-review:{uuid4()}"
        event, reviewed = qualify_public_question(db, question_id=question.id, node_id=node.id,
            expected_snapshot_sha256=expected, idempotency_key=key,
            source_evidence=source, now=clock.now)
        assert event is not None and reviewed["status"] == "AUTO_VERIFIED", reviewed
        assert reviewed["human_verified"] is False
        replay_event, replay = qualify_public_question(db, question_id=question.id, node_id=node.id,
            expected_snapshot_sha256=expected, idempotency_key=key, source_evidence=source, now=clock.now)
        assert replay_event.id == event.id and replay["status"] == "NOOP"
        assert question.answer_verification_event_id is None
        assert question.content_reviewed_by is None
        freeze_graduation_question_set(db, kp_id=node.id, question_ids=[question.id],
            reason="TEST_FIXTURE: one recovered queue question exercises existing v3 set flow", now=clock.now)
        qid, kp_id = str(question.id), str(node.id)
        assert db.scalar(select(func.count(DailyPlan.id))) == 0
        db.commit()

    setup = client.get("/api/plans/today")
    assert setup.status_code == 200
    with session_factory() as db:
        assert db.scalar(select(func.count(DailyPlan.id))) == 0  # Read only recommendation; user confirms next.
    generated = generate_plan(client, [kp_id])
    assert generated.status_code == 201, generated.text
    plan = generated.json()
    item = next(row for row in plan["items"] if row["question_id"] == qid)
    assert item["options"] == pack.questions[0].options
    assert "correct_answer" not in item and "explanation" not in item
    submitted = client.post(f"/api/practice-items/{item['id']}/answer-submissions", json={
        "idempotency_key": f"TEST_FIXTURE-hx-answer:{uuid4()}", "selected_option": pack.questions[0].correct_answer})
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["result"] == "right"
    assert client.get("/api/plans/today").json()["plan_id"] == plan["plan_id"]
    answer = client.get(f"/api/practice-items/{item['id']}/answer")
    assert answer.status_code == 200 and answer.json()["correct_answer"] == pack.questions[0].correct_answer
    assert len(answer.json()["explanation"]) > 50
    detail = client.get(f"/api/knowledge/{kp_id}")
    assert detail.status_code == 200, detail.text
    progress = detail.json()["capability_profile"]["graduation_progress"]
    assert progress["required_question_count"] == progress["completed_question_count"] == 1
    assert progress["graduated"] is True
    with session_factory() as db:
        attempt = db.scalar(select(QuestionAttempt).where(QuestionAttempt.question_id == qid))
        assert attempt.grading_evidence["evidence_reliability"] == "verified_objective"
        assert attempt.grading_evidence["auto_review_version"] == AUTO_REVIEW_VERSION
        assert db.get(Question, qid).bank_scope == "public"
