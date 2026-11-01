"""Activation/source-audit checks use only the isolated test database."""
from sqlalchemy import func, select, text

from backend.models.learning import KnowledgePoint, KpMasteryPolicy, Question, QuestionAnswerVerificationEvent
from scripts.activate_answer_trust_migration import probe_append_only_function
from scripts.answer_trust_migration_preflight import compare_fingerprints, fingerprint_database
from scripts.prepare_verified_slice_candidates import build_worklist
from tests.integration.test_learning_loop import clean_database, session_factory


def test_installed_trigger_probe_preserves_all_existing_business_rows(session_factory, clean_database):
    with session_factory() as db:
        connection = db.connection()
        before = {"tables": fingerprint_database(connection)}
        event_count = db.scalar(select(func.count()).select_from(QuestionAnswerVerificationEvent))
        result = probe_append_only_function(connection)
        after = {"tables": fingerprint_database(connection)}
        assert result["passed"] and result["verification_data_written"] is False
        assert compare_fingerprints(before, after)["passed"]
        assert db.scalar(select(func.count()).select_from(QuestionAnswerVerificationEvent)) == event_count
        db.rollback()


def test_slice_preparation_keeps_questions_answers_and_policies_unverified_and_unchanged(
        session_factory, clean_database, tmp_path):
    with session_factory.begin() as db:
        for subject in ("math2", "408"):
            for i in range(2):
                code = f"synthetic.activation.{subject}.{i}"
                node = KnowledgePoint(code=code, name=f"Synthetic {subject} {i}",
                    subject=subject, ordinal=i, is_assessable=True, is_active=True,
                    is_reference_only=True)
                db.add(node)
                db.flush()
                db.add(KpMasteryPolicy(kp_id=node.id, min_confirmations=3,
                    min_real_questions=3, required_question_types={"external_exam": 3},
                    required_variant_count=0, min_day_span=2))
                db.add(Question(kp_id=node.id, question_type="single_choice", stem="Synthetic isolated test question",
                    options={"A": "Synthetic option A", "B": "Synthetic option B"},
                    correct_answer="A", explanation="Synthetic isolated test explanation",
                    question_provenance="real_exam", content_trust="unreviewed",
                    source_status="traceable", answer_provenance="ai_generated", answer_reliability="unverified",
                    grading_config={"verified": False, "provenance": {"source": {
                        "source_type": "exam", "subject": subject, "year": 2021,
                        "question_number": i+1, "paper_title": "Synthetic source fixture, not real exam",
                        "citation": "Synthetic local metadata only"}}}))
    with session_factory() as db:
        db.execute(text("SET TRANSACTION READ ONLY"))
        before = {"tables": fingerprint_database(db.connection())}
        report = build_worklist(db, source_root=tmp_path)
        after = {"tables": fingerprint_database(db.connection())}
        assert compare_fingerprints(before, after)["passed"]
        assert report["node_count"] == 4
        assert report["subject_node_counts"] == {"math2": 2, "408": 2}
        assert report["source_status_counts_selected"] == {"SOURCE_METADATA_ONLY": 4}
        assert report["verification_data_written"] is False
        for node in report["nodes"]:
            assert node["policy_required_question_types"] == {"external_exam": 3}
            for question in node["questions"]:
                assert question["verification_type"] is None
                assert question["review_decision"] == "PENDING_HUMAN_REVIEW"
                assert question["current_eligibility"]["evidence_capability"] != "verified_objective"
        db.rollback()

