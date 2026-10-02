from copy import deepcopy
import pytest
from sqlalchemy import select, func
from backend.models.learning import Question, KnowledgePoint
from backend.services.question_pack import QuestionPack, import_pack
from tests.integration.test_learning_loop import session_factory, clean_database
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
        db.flush()
        result = import_pack(db, QuestionPack.model_validate(pack_data()), apply=True)
        assert result["requires_online_policy_review"] == [node.code]
        assert node.is_reference_only is True
        db.rollback()
