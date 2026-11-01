from uuid import UUID
from sqlalchemy import select, func
from backend.models.learning import Question, PracticeItem, DailyPlan, ExamQuestionReference
from backend.services.exam_reference_service import sync_exam_reference_index
from tests.integration.test_learning_loop import session_factory, clean_database, client, clock


def test_unreviewed_reference_candidate_is_not_appended_as_formal_online_practice(client, session_factory):
    with session_factory.begin() as db:
        sync_exam_reference_index(db)
        reference = db.scalar(select(ExamQuestionReference).order_by(ExamQuestionReference.id))
        question = db.scalar(select(Question).where(Question.is_active.is_(True)))
        # SYNTHETIC: use a seed question to simulate a complete source transcription.
        question.grading_config = {"verified": False, "method": None, "provenance": {
            "content_status": "source_transcribed", "source": {"source_type": "exam",
            "subject": reference.subject, "year": reference.year, "question_number": reference.question_number}}}
        question.answer_provenance="ai_generated";question.answer_reliability="model_generated"
        question.answer_verification_event_id=None;question.current_answer_verification=None
        reference_id, question_id, kp_id = str(reference.id), str(question.id), str(question.kp_id)
    response = client.post("/api/plans/today/exam-references", json={"reference_ids": [reference_id]})
    assert response.status_code == 409 and response.json()["error"]["code"] == "question_pool_incomplete"
    with session_factory() as db:
        assert db.scalar(select(func.count(DailyPlan.id))) == 0
        assert db.scalar(select(func.count(PracticeItem.id))) == 0
    # A source transcription and AI answer marker alone do not constitute the
    # formal review needed for this convenience route.


def test_mixed_missing_reference_cannot_create_partial_plan(client, session_factory):
    with session_factory.begin() as db:
        sync_exam_reference_index(db)
        references = list(db.scalars(select(ExamQuestionReference).order_by(ExamQuestionReference.id).limit(2)))
        question = db.scalar(select(Question).where(Question.is_active.is_(True)))
        first = references[0]
        question.grading_config = {"verified": False, "method": None, "provenance": {
            "content_status": "source_transcribed", "source": {"source_type": "exam",
            "subject": first.subject, "year": first.year, "question_number": first.question_number}}}
        question.answer_provenance="ai_generated";question.answer_reliability="model_generated"
        question.answer_verification_event_id=None;question.current_answer_verification=None
        ids = [str(r.id) for r in references]
        # Ensure the second pointer describes a different source identity.
        references[1].year = 2099
    response = client.post("/api/plans/today/exam-references", json={"reference_ids": ids})
    assert response.status_code == 409 and response.json()["error"]["code"] == "question_pool_incomplete"
    with session_factory() as db:
        assert db.scalar(select(func.count(DailyPlan.id))) == 0
        assert db.scalar(select(func.count(PracticeItem.id))) == 0


def test_tree_online_count_ignores_source_references(client, session_factory):
    with session_factory.begin() as db:
        sync_exam_reference_index(db)
        ref = db.scalar(select(ExamQuestionReference))
        empty_id = str(ref.knowledge_point_id)
        db.query(Question).filter(Question.kp_id == ref.knowledge_point_id).update({"is_active": False})
    nodes = client.get("/api/knowledge/tree").json()["nodes"]
    def flatten(nodes):
        for n in nodes:
            yield n
            yield from flatten(n["children"])
    by_id = {n["id"]: n for n in flatten(nodes)}
    assert by_id[empty_id]["online_question_count"] == 0
    assert any(n["online_question_count"] > 0 for n in by_id.values())
