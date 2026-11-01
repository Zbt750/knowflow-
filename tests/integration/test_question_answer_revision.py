from copy import deepcopy
import pytest
from sqlalchemy import select
from backend.models.learning import Question
from backend.services.question_pack import QuestionPack, fingerprint, import_pack
from backend.services.question_answer_revision import revise_answers
from backend.services.question_answer_revision import revise_transcription_content
from tests.integration.test_question_pack_import import pack_data
from tests.integration.test_learning_loop import session_factory, clean_database
from tests.integration.test_learning_loop import client, clock


def transcribed():
    data = pack_data()
    q = data["questions"][0]
    q.update(content_status="source_transcribed", grading_method=None, answer_reviewed_by=None,
        answer_reviewed_on=None, answer_provenance="legacy_transcription", answer_reliability="unverified",
        answer_review_method=None, answer_review_note=None, answer_reference=None)
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
        source_pack_sha256 = fingerprint(pack.questions[0].model_copy(update=changes))
        args = (db, row.id, digest(before), changes)
        kwargs = {"basis": "SIMULATED source comparison", "proposed_source_pack_sha256": source_pack_sha256,
                  "proposed_pack_version": "synthetic-correction-v2"}
        assert revise_transcription_content(*args, **kwargs)['corrected'] == 1
        assert snapshot(row) == before
        assert revise_transcription_content(*args, **kwargs, apply=True)['corrected'] == 1
        journal = row.grading_config['content_revisions'][0]
        assert journal['before'] == before
        assert journal['before_source_pack_sha256'] == before['grading_config']['provenance']['sha256']
        assert journal['after_source_pack_sha256'] == source_pack_sha256
        assert row.grading_config['provenance']['sha256'] == source_pack_sha256
        assert row.grading_config['verified'] is False and row.grading_config['method'] is None
        assert row.grading_mode == 'self_assessed' and str(row.id) == before['question_id']
        with pytest.raises(ValueError, match="snapshot changed"):
            revise_transcription_content(*args, **kwargs, apply=True)
        assert len(row.grading_config['content_revisions']) == 1
        db.rollback()


def test_qualified_exam_stem_revision_is_snapshot_bound_and_downgrades_until_requalification(
        session_factory, clean_database, monkeypatch):
    from types import SimpleNamespace
    from uuid import uuid4
    from backend.services.auto_question_review import question_snapshot_sha256
    from backend.services.question_answer_revision import revise_qualified_public_stem
    pack = transcribed()
    with session_factory() as db:
        import_pack(db, pack, apply=True)
        row = db.scalar(select(Question).where(Question.stem == pack.questions[0].stem))
        row.question_provenance = "real_exam"
        row.content_trust = "auto_verified"
        row.source_status = "traceable"
        row.answer_reliability = "verified"
        db.flush()
        fake_event = SimpleNamespace(id=uuid4(), qualification_class="exam_curated")
        calls = []
        monkeypatch.setattr("backend.services.auto_question_review.current_auto_review",
            lambda question, node=None: fake_event)
        def revoke(db_arg, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(id=uuid4())
        monkeypatch.setattr("backend.services.auto_question_review.revoke_auto_qualification", revoke)
        before = question_snapshot_sha256(row)
        new_stem = row.stem + "（按本地原卷恢复缺失限定条件）"
        new_explanation = row.explanation + "\n\n修正版本：补回原卷限定条件后按题意比较。"
        args = (db, row.id, before, fake_event.id,
                {"stem": new_stem, "explanation": new_explanation})
        kwargs = {"basis": "本地原卷页逐字核对；修复前题干遗漏了表示约定。",
            "source_pack_key": "corrected-pack:source-1", "source_pack_sha256": "a" * 64,
            "source_pack_version": "corrected-source-v2", "revision_key": "phase45z5-test-correction-001"}
        preview = revise_qualified_public_stem(*args, **kwargs)
        assert preview["status"] == "DRY_RUN"
        assert row.stem == pack.questions[0].stem and not calls
        result = revise_qualified_public_stem(*args, **kwargs, apply=True)
        assert result["status"] == "APPLIED_NEEDS_REVIEW"
        assert calls and row.stem == new_stem and row.explanation == new_explanation
        assert row.grading_config["provenance"]["key"] == "corrected-pack:source-1"
        assert row.grading_config["provenance"]["sha256"] == "a" * 64
        assert row.content_trust == "needs_review" and row.source_status == "needs_review"
        assert row.answer_reliability == "unverified"
        journal = row.grading_config["content_revisions"][-1]
        assert journal["revision_key"] == kwargs["revision_key"]
        assert journal["before"]["snapshot_sha256"] == before
        assert journal["human_verified"] is False
        assert journal["changes"] == {"stem": new_stem, "explanation": new_explanation}
        db.rollback()


def test_option_transcription_correction_is_versioned_and_invalidates_source_attestation(session_factory, clean_database):
    from copy import deepcopy
    from backend.services.answer_verification import answer_version_sha256
    from backend.services.question_attestation import question_content_sha256, has_current_source_attestation
    from backend.services.answer_consistency import answer_attestation_result_hash, has_current_answer_attestation
    from backend.services.question_verification_upgrade import snapshot
    from backend.services.golden_learning_slice import digest
    pack = transcribed()
    with session_factory() as db:
        import_pack(db, pack, apply=True)
        row = db.scalar(select(Question).where(Question.stem == pack.questions[0].stem))
        row.content_trust = "source_attested"
        row.source_status = "traceable"
        row.source_attestation_key = "SIMULATED-source-attestation"
        row.source_attestation_sha256 = question_content_sha256(row)
        row.answer_provenance = "ai_generated"
        row.answer_reliability = "ai_generated_consistent"
        row.answer_attestation_key = "SIMULATED-answer-attestation"
        row.answer_attestation_sha256 = answer_attestation_result_hash(row)
        db.flush()
        before = snapshot(row)
        old_options = deepcopy(row.options)
        old_answer_hash = answer_version_sha256(row)
        new_options = deepcopy(row.options)
        new_options["C"] = "$-1/\\ln2$"
        changes = {"options": new_options}
        source_pack_sha256 = fingerprint(pack.questions[0].model_copy(update=changes))
        args = (db, row.id, digest(before), changes)
        kwargs = {"basis": "SIMULATED source-page correction", "proposed_source_pack_sha256": source_pack_sha256,
                  "proposed_pack_version": "synthetic-correction-v2"}
        preview = revise_transcription_content(*args, **kwargs)
        assert preview["corrected"] == 1 and preview["source_content_changed"] is True
        assert preview["source_attestation_invalidated"] is True
        assert preview["answer_attestation_invalidated"] is True
        assert preview["before_answer_attestation_current"] is True
        assert preview["proposed_answer_attestation_current"] is False
        assert preview["proposed_answer_reliability"] == "unverified"
        assert preview["proposed_answer_version_sha256"] != old_answer_hash
        assert snapshot(row) == before and row.options == old_options
        result = revise_transcription_content(*args, **kwargs, apply=True)
        assert result["before_answer_attestation_current"] is True
        assert result["before_answer_reliability"] == "ai_generated_consistent"
        assert result["proposed_answer_attestation_current"] is False
        assert result["proposed_answer_reliability"] == "unverified"
        journal = row.grading_config["content_revisions"][0]
        assert result["corrected"] == 1 and result["verified_upgrades"] == 0
        assert journal["before"] == before and journal["changes"] == changes
        assert journal["before_source_pack_sha256"] == before["grading_config"]["provenance"]["sha256"]
        assert journal["after_source_pack_sha256"] == source_pack_sha256
        assert row.options["C"] == "$-1/\\ln2$"
        assert {key: value for key, value in row.options.items() if key != "C"} == {
            key: value for key, value in old_options.items() if key != "C"
        }
        assert row.correct_answer == "A" and str(row.kp_id) == before["kp_id"]
        assert row.grading_config["provenance"]["sha256"] == source_pack_sha256
        assert row.content_trust == "needs_review" and row.source_status == "needs_review"
        assert row.source_attestation_key is None and row.source_attestation_sha256 is None
        assert not has_current_source_attestation(row)
        assert row.answer_attestation_key is None and row.answer_attestation_sha256 is None
        assert not has_current_answer_attestation(row)
        assert row.answer_reliability == "unverified"
        assert answer_version_sha256(row) != old_answer_hash
        with pytest.raises(ValueError, match="snapshot changed"):
            revise_transcription_content(*args, **{**kwargs, "basis": "SIMULATED stale replay"}, apply=True)
        db.rollback()


def test_answer_only_correction_invalidates_answer_attestation_but_keeps_source_attestation(session_factory, clean_database):
    from backend.services.question_attestation import question_content_sha256, has_current_source_attestation
    from backend.services.answer_consistency import answer_attestation_result_hash, has_current_answer_attestation
    from backend.services.question_verification_upgrade import snapshot
    from backend.services.golden_learning_slice import digest
    pack = transcribed()
    with session_factory() as db:
        import_pack(db, pack, apply=True)
        row = db.scalar(select(Question).where(Question.stem == pack.questions[0].stem))
        row.content_trust = "source_attested"
        row.source_status = "traceable"
        row.source_attestation_key = "SIMULATED-source-attestation"
        row.source_attestation_sha256 = question_content_sha256(row)
        row.answer_provenance = "ai_generated"
        row.answer_reliability = "ai_generated_consistent"
        row.answer_attestation_key = "SIMULATED-answer-attestation"
        row.answer_attestation_sha256 = answer_attestation_result_hash(row)
        db.flush()
        before = snapshot(row)
        changes = {"correct_answer": "B", "explanation": "合成隔离题更正答案的逐步推导，仅用于测试。"}
        source_pack_sha256 = fingerprint(pack.questions[0].model_copy(update=changes))
        kwargs = {"basis": "SIMULATED answer correction test", "proposed_source_pack_sha256": source_pack_sha256,
                  "proposed_pack_version": "synthetic-answer-correction-v2"}
        preview = revise_transcription_content(db, row.id, digest(before), changes, **kwargs)
        assert preview["corrected"] == 1
        assert preview["source_content_changed"] is False
        assert preview["source_attestation_invalidated"] is False
        assert preview["answer_attestation_invalidated"] is True
        assert preview["proposed_answer_attestation_current"] is False
        assert snapshot(row) == before
        result = revise_transcription_content(db, row.id, digest(before), changes, **kwargs, apply=True)
        assert result["source_attestation_invalidated"] is False
        assert result["answer_attestation_invalidated"] is True
        assert has_current_source_attestation(row)
        assert not has_current_answer_attestation(row)
        assert row.source_attestation_key == "SIMULATED-source-attestation"
        assert row.answer_attestation_key is None and row.answer_attestation_sha256 is None
        assert row.answer_reliability == "unverified"
        assert row.content_trust == "source_attested" and row.source_status == "traceable"
        db.rollback()


def test_explicit_correction_can_recheck_an_unverified_supported_grader(session_factory, clean_database):
    from backend.services.question_verification_upgrade import snapshot
    from backend.services.golden_learning_slice import digest
    pack = transcribed()
    with session_factory() as db:
        import_pack(db, pack, apply=True)
        row = db.scalar(select(Question).where(Question.stem == pack.questions[0].stem))
        row.grading_config = {**row.grading_config, "verified": False, "method": "single_choice"}
        db.flush()
        before = snapshot(row)
        changes = {"correct_answer": "B", "explanation": "合成题更正答案的完整推导，用于测试未验证比较器复审。"}
        kwargs = {"basis": "SIMULATED explicit unverified-grader review", "proposed_source_pack_sha256":
                  fingerprint(pack.questions[0].model_copy(update=changes)),
                  "proposed_pack_version": "synthetic-recheck-v2", "allow_unverified_grader": True}
        result = revise_transcription_content(db, row.id, digest(before), changes, **kwargs, apply=True)
        assert result["corrected"] == 1 and result["verified_upgrades"] == 0
        assert row.correct_answer == "B"
        assert row.grading_config["verified"] is False
        assert row.grading_config["method"] == "single_choice"
        assert row.grading_mode == "self_assessed"
        db.rollback()


@pytest.mark.parametrize("change", ["verified", "method", "mode", "inactive", "parent", "mapping_field", "bad_choice", "bad_options", "stale"])
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
        if change == 'bad_options': changes['options'] = {"C": "incomplete option set"}
        with pytest.raises(ValueError):
            revise_transcription_content(db, row.id, '0'*64 if change == 'stale' else digest(before), changes,
                                         basis="SIMULATED source comparison",
                                         proposed_source_pack_sha256=fingerprint(pack.questions[0]),
                                         proposed_pack_version="synthetic-correction-v2", apply=True)
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
