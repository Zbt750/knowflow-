"""All sources/reviewers here are isolated TEST_FIXTURE data, never real signoffs."""
from copy import deepcopy

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from backend.models.learning import Question
from backend.services.question_pack import QuestionPack, import_pack
from backend.services.golden_learning_slice import digest
from backend.services.golden_review_session import load_views, new_draft, configure, ORDER, record_review, export_bundle
from backend.services.question_verification_upgrade import snapshot, upgrade_transcriptions
from tests.integration.test_question_answer_revision import transcribed
from tests.integration.test_learning_loop import session_factory, clean_database


def seed_three(db):
    data = transcribed().model_dump(mode="json")
    base = data["questions"][0]
    data["pack_id"] = "TEST-FIXTURE-human-review"
    qs = []
    for i in range(3):
        q = deepcopy(base)
        q["source_id"] = f"synthetic-{i}"
        q["stem"] = f"TEST_FIXTURE independent arithmetic review {i}"
        q["source"].update(year=2020 + i, question_number=i + 1)
        if i == 2:
            q.update(question_type="fill_blank", options=None, correct_answer="1")
        qs.append(q)
    data["questions"] = qs
    pack = QuestionPack.model_validate(data)
    import_pack(db, pack, apply=True)
    return list(db.scalars(select(Question).where(Question.stem.in_([q.stem for q in pack.questions]))).all())


def test_three_live_questions_and_complete_simulated_bundle_dry_run(session_factory, clean_database):
    with session_factory() as db:
        rows = seed_three(db)
        before = {str(r.id): snapshot(r) for r in rows}
        ids = list(before)
        views = load_views(db, ids)
        draft = new_draft(views)
        for row in draft["questions"]:
            configure(row, reviewer="SIMULATED TEST OPERATOR", citation="SIMULATED source inspected",
                rights_basis="SIMULATED test-only permission", answer_note="SIMULATED independent solution note",
                method="single_choice" if row["view"]["content"]["question_type"] == "single_choice" else "numeric_final")
            for aspect in ORDER:
                record_review(row, aspect, "VERIFIED", row["proposal"]["answer_review_note"] if aspect == "answer" else "SIMULATED review note only")
            row["resolutions"] = {issue: "SIMULATED specific resolution only" for issue in row["resolutions"]}
        bundle = export_bundle(draft, load_views(db, ids))
        pack = QuestionPack.model_validate(bundle["pack"])
        reviews = {r["candidate_id"]: r["reviews"] for r in bundle["decisions"]["questions"]}
        preview = upgrade_transcriptions(db, pack, bundle["targets"], reviews, apply=False)
        assert preview["upgraded"] == 3 and preview["history_regraded"] is False
        assert {str(r.id): snapshot(r) for r in rows} == before
        assert not any(r.answer_verification_event_id for r in rows)
        db.rollback()


def test_db_read_only_transaction_rejects_mutation(session_factory, clean_database):
    with session_factory() as seed:
        rows = seed_three(seed)
        ids = [str(q.id) for q in rows]
        before = {str(q.id): digest(snapshot(q)) for q in rows}
        seed.commit()
    with session_factory() as reader:
        reader.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        views = load_views(reader, ids)
        assert len(views) == 3 and reader.scalar(text("SHOW transaction_read_only")) == "on"
        # This rejected statement is deliberately confined to kaoyan_test.
        with pytest.raises(DBAPIError):
            reader.execute(text("UPDATE questions SET stem=stem WHERE id=:id"), {"id": ids[0]})
        reader.rollback()
    with session_factory() as check:
        assert {str(q.id): digest(snapshot(q)) for q in check.scalars(select(Question).where(Question.id.in_(ids)))} == before
