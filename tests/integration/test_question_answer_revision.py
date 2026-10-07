from copy import deepcopy
import pytest
from sqlalchemy import select
from backend.models.learning import Question
from backend.services.question_pack import QuestionPack, import_pack
from backend.services.question_answer_revision import revise_answers
from backend.services.question_answer_revision import revise_transcription_content
from tests.integration.test_question_pack_import import pack_data
from tests.integration.test_learning_loop import session_factory, clean_database
from tests.integration.test_learning_loop import client, clock


def transcribed():
    data = pack_data()
    q = data["questions"][0]
    q.update(content_status="source_transcribed", grading_method=None, answer_reviewed_by=None)
    q["source"].update(kind="user_provided", source_type="exam", year=2025,
                       question_number=1, subject="数学二", paper_title="合成隔离原卷")
    return QuestionPack.model_validate(data)


def test_content_correction_preserves_full_before_and_refuses_stale_replay(session_factory, clean_database):
    from backend.services.question_verification_upgrade import snapshot
    from backend.services.golden_learning_slice import digest
    pack = transcribed()
    with session_factory() as db:
        import_pack(db, pack, apply=True)
        row = db.scalar(select(Question).where(Question.stem == pack.questions[0].stem))
        before = snapshot(row)
        changes = {"stem": row.stem + "（合成内容纠错）", "correct_answer": "B",
                   "explanation": "合成隔离题纠错推导；非真实题审核。"}
        args = (db, row.id, digest(before), changes)
        assert revise_transcription_content(*args, basis="SIMULATED source comparison")['corrected'] == 1
        assert snapshot(row) == before
        assert revise_transcription_content(*args, basis="SIMULATED source comparison", apply=True)['corrected'] == 1
        journal = row.grading_config['content_revisions'][0]
        assert journal['before'] == before
        assert row.grading_config['provenance'] == before['grading_config']['provenance']
        assert row.grading_config['verified'] is False and row.grading_config['method'] is None
        assert row.grading_mode == 'self_assessed' and str(row.id) == before['question_id']
        with pytest.raises(ValueError, match="snapshot changed"):
            revise_transcription_content(*args, basis="SIMULATED source comparison", apply=True)
        assert len(row.grading_config['content_revisions']) == 1
        db.rollback()


@pytest.mark.parametrize("change", ["verified", "method", "mode", "inactive", "parent", "mapping_field", "bad_choice", "stale"])
def test_content_correction_rejects_unsafe_changes(session_factory, clean_database, change):
    from backend.services.question_verification_upgrade import snapshot
    from backend.services.golden_learning_slice import digest
    from backend.models.learning import KnowledgePoint
    pack = transcribed()
    with session_factory() as db:
        import_pack(db, pack, apply=True)
        row = db.scalar(select(Question).where(Question.stem == pack.questions[0].stem))
        if change == 'verified': row.grading_config = {**row.grading_config, 'verified': True}
        if change == 'method': row.grading_config = {**row.grading_config, 'method': 'single_choice'}
        if change == 'mode': row.grading_mode = 'auto'
        if change == 'inactive': row.is_active = False
        if change == 'parent': db.get(KnowledgePoint, row.kp_id).is_assessable = False
        db.flush()
        before = snapshot(row)
        changes = {"stem": row.stem + "（纠错）", "correct_answer": "B", "explanation": "合成隔离纠错说明，未审核。"}
        if change == 'mapping_field': changes['kp_code'] = 'other'
        if change == 'bad_choice': changes['correct_answer'] = 'Z'
        with pytest.raises(ValueError):
            revise_transcription_content(db, row.id, '0'*64 if change == 'stale' else digest(before), changes,
                                         basis="SIMULATED source comparison", apply=True)
        assert snapshot(row) == before
        db.rollback()


def test_answer_enrichment_is_audited_idempotent_and_not_verification(session_factory, clean_database):
    pack = transcribed()
    revision = {"q1": {"answer": "B", "explanation": "AI独立推导的详细过程，待核验。"}}
    with session_factory() as db:
        import_pack(db, pack, apply=True)
        row = db.scalar(select(Question).where(Question.stem == pack.questions[0].stem))
        previous_config = deepcopy(row.grading_config)
        assert revise_answers(db, pack, revision)["enriched"] == 1
        assert row.correct_answer == "A"
        assert revise_answers(db, pack, revision, apply=True)["enriched"] == 1
        assert row.correct_answer == "B"
        assert row.grading_config["verified"] is False
        assert row.grading_config["method"] is None
        assert row.grading_config["provenance"] == previous_config["provenance"]
        assert row.grading_config["answer_revisions"][0]["previous_answer"] == "A"
        assert revise_answers(db, pack, revision, apply=True)["enriched"] == 0
        db.rollback()


def test_answer_enrichment_reloads_external_revision(session_factory, clean_database):
    pack = transcribed()
    with session_factory() as stale:
        import_pack(stale, pack, apply=True)
        row = stale.scalar(select(Question).where(Question.stem == pack.questions[0].stem))
        stale.commit()
        with session_factory.begin() as other:
            other.get(Question, row.id).explanation = "External transaction correction to preserve"
        with pytest.raises(ValueError, match="answer changed since source pack"):
            revise_answers(stale, pack, {"q1": {"answer": "B", "explanation": "AI new draft, not reviewed"}}, apply=True)
        stale.rollback()


@pytest.mark.parametrize("change", ["verified", "manual_edit", "stem", "unknown", "fields"])
def test_answer_enrichment_fails_closed(session_factory, clean_database, change):
    pack = transcribed()
    revision = {"q1": {"answer": "B", "explanation": "AI独立推导的详细过程，待核验。"}}
    with session_factory() as db:
        import_pack(db, pack, apply=True)
        row = db.scalar(select(Question).where(Question.stem == pack.questions[0].stem))
        if change == "verified": row.grading_config = {**row.grading_config, "verified": True}
        if change == "manual_edit": row.explanation = "用户自己修改的解析，应当保护。"
        if change == "stem": row.stem += "修改内容"
        if change == "unknown": revision = {"unknown": revision["q1"]}
        if change == "fields": revision["q1"]["stem"] = "不得借答案修订覆盖题干"
        db.flush()
        with pytest.raises(ValueError):
            revise_answers(db, pack, revision, apply=True)
        assert row.correct_answer == "A"
        db.rollback()


def test_family_displays_related_question_without_remapping_evidence(client, session_factory):
    from backend.models.learning import KnowledgePoint, ExamQuestionReference
    pack = transcribed()
    with session_factory() as db:
        import_pack(db, pack, apply=True)
        family = KnowledgePoint(code="math.family.synthetic", name="合成专题", subject="数学二",
                                is_assessable=True, is_reference_only=True)
        db.add(family)
        db.flush()
        db.add(ExamQuestionReference(knowledge_point_id=family.id, subject="数学二", year=2025,
                                    question_number=1, topic_label="合成专题", source_topic_label="合成专题",
                                    local_folder="合成测试", source_note="仅隔离测试"))
        family_id = str(family.id)
        row = db.scalar(select(Question).where(Question.stem == pack.questions[0].stem))
        original_kp = row.kp_id
        question_id = str(row.id)
        db.commit()
    detail = client.get(f"/api/knowledge/{family_id}")
    assert detail.status_code == 200
    question = next(q for q in detail.json()["questions"] if q["id"] == question_id)
    assert question["kp_id"] == str(original_kp)
    assert question["options"] == pack.questions[0].options
    assert "correct_answer" not in question
