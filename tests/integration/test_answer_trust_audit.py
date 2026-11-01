"""Golden slice inventory report uses aggregate, read-only facts only."""
import json

from sqlalchemy import text

from backend.models.learning import KnowledgePoint
from scripts.audit_answer_trust_slice import build_report
from tests.integration.test_learning_loop import clean_database, session_factory


def test_answer_trust_slice_report_is_read_only_and_does_not_emit_content(session_factory, clean_database):
    codes = (
        "math.exam.fd2f9e3739d9", "math.exam.f37948c82a05",
        "cs408.ds.topic.1efaf3d00b50", "cs408.os.topic.cb972030e503",
    )
    with session_factory.begin() as db:
        for ordinal, code in enumerate(codes):
            db.add(KnowledgePoint(code=code, name=f"Synthetic node {ordinal}",
                subject="数学二" if code.startswith("math.") else "408",
                ordinal=ordinal, is_assessable=True, is_reference_only=False, is_active=True))
    with session_factory() as db:
        db.execute(text("SET TRANSACTION READ ONLY"))
        report = build_report(db)
        before = db.scalar(text("SELECT count(*) FROM questions"))
        db.rollback()

    assert report["read_only"] is True and report["model_calls"] == 0
    assert {row["code"] for row in report["golden_slice"]} == set(codes)
    assert before == report["counts"]["questions"]
    rendered = json.dumps(report, ensure_ascii=False)
    assert '"stem"' not in rendered and '"correct_answer"' not in rendered
    assert all("learner_mastery_claim" in row for row in report["golden_slice"]), report["golden_slice"]
    assert all(row["source_availability"] == "NOT_AUDITED" for row in report["golden_slice"])
    assert all(row["answer_verification_status"] == "UNVERIFIED_ANSWER" for row in report["golden_slice"])
