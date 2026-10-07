from copy import deepcopy
import pytest
from sqlalchemy import select, func
from backend.models.learning import Question, KnowledgePoint
from backend.services.question_pack import QuestionPack, import_pack, replace_demo_questions, retire_demo_questions
from tests.integration.test_learning_loop import session_factory, clean_database
from tests.integration.test_learning_loop import client, clock, leaf_codes, generate_plan
from tests.unit.test_question_pack import payload


def pack_data():
    data = payload()
    data["questions"][0]["kp_code"] = "math.calculus.limit.lhopital"
    return data


def test_dry_run_apply_and_idempotency(session_factory, clean_database):
    pack = QuestionPack.model_validate(pack_data())
    with session_factory() as db:
        before = db.scalar(select(func.count(Question.id)))
        assert import_pack(db, pack)["new"] == 1
        assert db.scalar(select(func.count(Question.id))) == before
        assert import_pack(db, pack, apply=True)["new"] == 1
        assert import_pack(db, pack, apply=True)["unchanged"] == 1
        assert db.scalar(select(func.count(Question.id))) == before + 1
        db.rollback()


def test_manual_edit_and_source_remap_are_conflicts(session_factory, clean_database):
    data = pack_data()
    pack = QuestionPack.model_validate(data)
    with session_factory() as db:
        import_pack(db, pack, apply=True)
        q = db.scalar(select(Question).where(Question.stem == data["questions"][0]["stem"]))
        q.correct_answer = "B"
        db.flush()
        with pytest.raises(ValueError, match="conflicts"):
            import_pack(db, pack, apply=True)
        assert q.correct_answer == "B"
        remapped = deepcopy(data)
        remapped["questions"][0]["kp_code"] = "math.calculus.differential.implicit"
        with pytest.raises(ValueError, match="conflicts"):
            import_pack(db, QuestionPack.model_validate(remapped), apply=True)
        db.rollback()


def test_reimport_does_not_trust_cached_question_after_external_edit(session_factory, clean_database):
    pack = QuestionPack.model_validate(pack_data())
    with session_factory() as stale:
        import_pack(stale, pack, apply=True)
        row = stale.scalar(select(Question).where(Question.stem == pack.questions[0].stem))
        stale.commit()
        with session_factory.begin() as other:
            other.get(Question, row.id).explanation = "Separate transaction content must not be hidden by identity map"
        with pytest.raises(ValueError, match="conflicts"):
            import_pack(stale, pack, apply=True)
        stale.rollback()


@pytest.mark.parametrize("field", ["verified", "method", "grading_mode", "source", "content_status", "answer_reviewer"])
def test_idempotent_import_detects_grading_or_provenance_drift(session_factory, clean_database, field):
    """Do not trust an unchanged saved hash when mutable DB fields drifted."""
    data = pack_data()
    pack = QuestionPack.model_validate(data)
    with session_factory() as db:
        import_pack(db, pack, apply=True)
        q = db.scalar(select(Question).where(Question.stem == data["questions"][0]["stem"]))
        config = deepcopy(q.grading_config)
        if field == "verified": config["verified"] = False
        elif field == "method": config["method"] = "numeric_final"
        elif field == "grading_mode": q.grading_mode = "self_assessed"
        elif field == "source": config["provenance"]["source"]["citation"] = "Changed source, stale saved hash"
        elif field == "content_status": config["provenance"]["content_status"] = "source_transcribed"
        elif field == "answer_reviewer": config["provenance"]["answer_reviewed_by"] = "Changed reviewer"
        q.grading_config = config
        db.flush()
        before = db.scalar(select(func.count(Question.id)))
        with pytest.raises(ValueError, match="conflicts"):
            import_pack(db, pack, apply=True)
        assert db.scalar(select(func.count(Question.id))) == before
        assert q.grading_config == config  # No silent repair/re-approval.
        db.rollback()


def test_invalid_second_node_leaves_no_partial_batch(session_factory, clean_database):
    data = pack_data()
    second = deepcopy(data["questions"][0])
    second.update(source_id="q2", kp_code="unknown.node", stem="另一道不应落库的合成题目")
    data["questions"].append(second)
    with session_factory() as db:
        before = db.scalar(select(func.count(Question.id)))
        with pytest.raises(ValueError, match="missing node"):
            import_pack(db, QuestionPack.model_validate(data), apply=True)
        assert db.scalar(select(func.count(Question.id))) == before
        db.rollback()


def test_reference_only_node_requires_explicit_policy_review(session_factory, clean_database):
    with session_factory() as db:
        node = db.scalar(select(KnowledgePoint).where(KnowledgePoint.code == "math.calculus.limit.lhopital"))
        node.is_reference_only = True
        for existing in db.scalars(select(Question).where(Question.kp_id == node.id)):
            existing.is_active = False
        db.flush()
        result = import_pack(db, QuestionPack.model_validate(pack_data()), apply=True)
        assert result["requires_online_policy_review"] == [node.code]
        assert node.is_reference_only is True
        db.rollback()


def test_real_pack_replacement_is_scoped_soft_and_idempotent(session_factory, clean_database):
    import json
    from pathlib import Path
    from scripts.seed import upsert_questions
    demo = json.loads((Path(__file__).resolve().parents[2] / "seed/questions.json").read_text(encoding="utf-8"))
    data = pack_data()
    data["questions"][0]["source"].update(kind="user_provided", source_type="exam", year=2024,
        question_number=8, subject="数学二", paper_title="合成隔离测试身份（非真实试卷）")
    pack = QuestionPack.model_validate(data)
    with session_factory() as db:
        count = db.scalar(select(func.count(Question.id)))
        active = db.scalar(select(func.count(Question.id)).where(Question.is_active.is_(True)))
        preview = replace_demo_questions(db, pack, demo)
        assert preview["retired_demo_count"] == 5
        assert db.scalar(select(func.count(Question.id))) == count
        result = replace_demo_questions(db, pack, demo, apply=True)
        assert result["retired_demo_count"] == 5
        assert db.scalar(select(func.count(Question.id))) == count + 1
        assert db.scalar(select(func.count(Question.id)).where(Question.is_active.is_(True))) == active - 4
        assert replace_demo_questions(db, pack, demo, apply=True)["retired_demo_count"] == 0
        upsert_questions(db, demo)
        assert db.scalar(select(func.count(Question.id)).where(Question.is_active.is_(True))) == active - 4
        db.rollback()


def test_original_pack_cannot_replace_demo_bank(session_factory, clean_database):
    with session_factory() as db:
        with pytest.raises(ValueError, match="complete reviewed exam/mock"):
            replace_demo_questions(db, QuestionPack.model_validate(pack_data()), {"questions": []}, apply=True)
        db.rollback()


def test_sources_flow_to_node_and_today_without_answer_or_review_leaks(client, session_factory):
    data = pack_data()
    data["questions"][0]["source"].update(kind="user_provided", source_type="mock", year=2025,
        question_number=3, subject="数学二", paper_title="合成隔离模拟卷")
    with session_factory() as db:
        import_pack(db, QuestionPack.model_validate(data), apply=True)
        db.commit()
    kp_id = leaf_codes(session_factory)["math.calculus.limit.lhopital"]
    detail = client.get(f"/api/knowledge/{kp_id}").json()
    question = next(q for q in detail["questions"] if q["stem"] == data["questions"][0]["stem"])
    source = question["question_source"]
    assert question["options"] == data["questions"][0]["options"]
    assert "correct_answer" not in question and "explanation" not in question
    assert source["source_type"] == "mock" and source["year"] == 2025
    assert "reviewed_by" not in source and "rights_basis" not in source
    generated = generate_plan(client, [kp_id])
    plan = generated.json()
    if not any(i["question_id"] == question["id"] for i in plan["items"]):
        response = client.post(f'/api/plans/{plan["plan_id"]}/questions', json={"question_ids": [question["id"]]})
        assert response.status_code == 200
        plan = response.json()
    item = next(i for i in plan["items"] if i["question_id"] == question["id"])
    assert item["question_source"] == source
    assert "correct_answer" not in item and "explanation" not in item


def test_retired_question_keeps_today_answers_and_attempt_history(client, session_factory):
    import json
    from pathlib import Path
    kp_id = leaf_codes(session_factory)["math.calculus.limit.lhopital"]
    old_plan = generate_plan(client, [kp_id]).json()
    old_item = old_plan["items"][0]
    submitted = client.post(f'/api/practice-items/{old_item["id"]}/answer-submissions',
                            json={"idempotency_key": "source-retirement-history", "raw_answer": ""})
    assert submitted.status_code == 200
    data = pack_data()
    data["questions"][0]["source"].update(kind="user_provided", source_type="exam", year=2024,
        question_number=8, subject="数学二", paper_title="合成隔离测试身份（非真实试卷）")
    demo = json.loads((Path(__file__).resolve().parents[2] / "seed/questions.json").read_text(encoding="utf-8"))
    with session_factory() as db:
        replace_demo_questions(db, QuestionPack.model_validate(data), demo, apply=True)
        db.commit()
    assert client.get(f'/api/practice-items/{old_item["id"]}/answer').status_code == 200
    history = client.get(f'/api/practice-items/{old_item["id"]}/answer-submissions').json()
    assert history["items"][0]["attempt_id"] == submitted.json()["attempt_id"]
    detail = client.get(f"/api/knowledge/{kp_id}").json()
    assert old_item["question_id"] not in {q["id"] for q in detail["questions"]}
    assert len(detail["questions"]) == 1


def test_explicit_all_demo_retirement_preserves_rows_and_seed_does_not_revive(session_factory, clean_database):
    import json
    from pathlib import Path
    from scripts.seed import upsert_questions
    demo = json.loads((Path(__file__).resolve().parents[2] / "seed/questions.json").read_text(encoding="utf-8"))
    with session_factory() as db:
        before = db.scalar(select(func.count(Question.id)))
        assert retire_demo_questions(db, demo)["retired_demo_count"] == 22
        result = retire_demo_questions(db, demo, apply=True)
        assert result["retired_demo_count"] == 22
        assert db.scalar(select(func.count(Question.id))) == before
        upsert_questions(db, demo)
        assert db.scalar(select(func.count(Question.id)).where(Question.is_active.is_(True))) == 0
        assert retire_demo_questions(db, demo, apply=True)["retired_demo_count"] == 0
        db.rollback()


def test_demo_retirement_preserves_externally_revised_question(session_factory, clean_database):
    import json
    from pathlib import Path
    demo = json.loads((Path(__file__).resolve().parents[2] / "seed/questions.json").read_text(encoding="utf-8"))
    item = demo["questions"][0]
    with session_factory() as first:
        node = first.scalar(select(KnowledgePoint).where(KnowledgePoint.code == item["kp_code"]))
        cached = first.scalar(select(Question).where(Question.kp_id == node.id, Question.stem == item["stem"]))
        first.commit()
        with session_factory() as second:
            changed = second.get(Question, cached.id)
            changed.explanation += "\n外部修订，不能再按旧演示内容停用。"
            second.commit()
        result = retire_demo_questions(first, {"questions": [item]}, apply=True)
        assert result["retired_demo_count"] == 0
        assert cached.is_active
        assert "外部修订" in cached.explanation
        first.rollback()


def test_unreviewed_transcription_is_not_eligible_on_reference_only_mapping(client, session_factory):
    data = pack_data()
    q = data["questions"][0]
    q.update(content_status="source_transcribed", answer_reviewed_by=None, grading_method=None)
    q["source"].update(kind="user_provided", source_type="exam", year=2026,
        question_number=8, subject="数学二", paper_title="合成隔离测试原卷", edition="回忆版")
    with session_factory() as db:
        node = db.scalar(select(KnowledgePoint).where(KnowledgePoint.code == q["kp_code"]))
        node.is_reference_only = True
        import_pack(db, QuestionPack.model_validate(data), apply=True)
        db.commit()
    kp_id = leaf_codes(session_factory)[q["kp_code"]]
    detail = client.get(f"/api/knowledge/{kp_id}").json()
    imported = next(item for item in detail["questions"] if item["stem"] == q["stem"])
    assert imported["trust"]["content_trust"] == "needs_review"
    assert imported["trust"]["answer_provenance"] == "legacy_transcription"
    assert imported["trust"]["practice_eligible"] is False
    generated = generate_plan(client, [kp_id])
    assert generated.status_code == 409
    assert generated.json()["error"]["code"] == "question_pool_incomplete"
    with session_factory() as db:
        assert db.get(KnowledgePoint, kp_id).is_reference_only
