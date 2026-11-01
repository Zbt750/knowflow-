from datetime import date
from uuid import uuid4
import json

from backend.models.learning import KnowledgePoint, Question
from backend.services.answer_consistency import (
    answer_attestation_check_key,
    answer_attestation_result_hash,
)
from backend.services.question_attestation import (
    assess_source_attestation,
    has_current_source_attestation,
    question_content_sha256,
    _subject,
)
from backend.services.question_production_pipeline import _norm_subject
from backend.services.question_pack import PackQuestion, fingerprint


ARCHIVE_SHA = "a" * 64
PACK_ID = "synthetic-phase3b"
PACK_VERSION = "test-v1"


def test_official_408_paper_title_with_parenthesized_code_maps_to_408():
    title = "计算机学科专业基础（408）"
    assert _subject(title) == "408"
    assert _norm_subject(title) == "408"


def attested_fixture():
    node = KnowledgePoint(id=uuid4(), code="math.exam.synthetic", name="隔离测试节点",
        subject="math2", is_active=True, is_assessable=True, is_reference_only=True)
    item = PackQuestion.model_validate({
        "source_id": "q2024_01",
        "kp_code": node.code,
        "question_type": "single_choice",
        "stem": "设函数在区间上连续，判断以下选项中正确的一项。",
        "options": {"A": "甲命题", "B": "乙命题", "C": "丙命题", "D": "丁命题"},
        "correct_answer": "A",
        "explanation": "逐项检查定义条件后，只有 A 符合题设。",
        "question_role": "basic",
        "difficulty": "basic",
        "estimated_minutes": 4,
        "skill_tags": ["连续性"],
        "is_variant": False,
        "source": {
            "kind": "user_provided",
            "citation": "隔离合成测试来源记录",
            "rights_basis": "仅用于本地测试，不表示已获公开分发许可",
            "reviewed_by": "test-importer",
            "reviewed_on": date(2026, 10, 1),
            "year": 2024,
            "question_number": 1,
            "source_type": "exam",
            "paper_title": "隔离合成数学试卷",
            "subject": "数学二",
        },
        "content_status": "source_transcribed",
        "answer_provenance": "legacy_transcription",
        "answer_reliability": "unverified",
    })
    key = f"{PACK_ID}:{item.source_id}"
    q = Question(id=uuid4(), kp_id=node.id, question_type=item.question_type,
        grading_mode="self_assessed", grading_config={"verified": False,
            "provenance": {"key": key, "sha256": fingerprint(item),
                "source": item.source.model_dump(mode="json"),
                "content_status": "source_transcribed"}},
        stem=item.stem, options=item.options, correct_answer=item.correct_answer,
        explanation=item.explanation, question_role=item.question_role,
        difficulty=item.difficulty, skill_tags=item.skill_tags,
        estimated_minutes=item.estimated_minutes, is_variant=item.is_variant,
        is_active=True, question_provenance="legacy_unknown", content_trust="unreviewed",
        source_status="unknown", answer_provenance="legacy_transcription",
        answer_reliability="unverified")
    row = {"candidate_id": "math2:2024:Q01", "candidate_path": "数学二/2024/Q01.md",
        "mapping_status": "EXACT", "match_count": "1",
        "matched_question_ids": json.dumps([str(q.id)])}
    assessment = assess_source_attestation(question=q, node=node, pack_question=item,
        pack_id=PACK_ID, pack_version=PACK_VERSION,
        candidate_archive_sha256=ARCHIVE_SHA, candidate_map_row=row)
    return q, node, item, row, assessment


def test_exact_source_identity_and_pack_fingerprint_attest_full_question_not_answer():
    q, node, item, row, assessment = attested_fixture()

    assert assessment.status == "source_attested"
    assert assessment.mapping_type == "exact_full_question_on_assessable_reference_topic"
    assert assessment.source_identity["rights_basis_status"] == "local_use_only_redistribution_not_cleared"
    q.source_attestation_key = assessment.attestation_key
    q.source_attestation_sha256 = assessment.question_content_sha256
    assert has_current_source_attestation(q)

    q.stem += "（被修改）"
    assert not has_current_source_attestation(q)
    changed = assess_source_attestation(question=q, node=node, pack_question=item,
        pack_id=PACK_ID, pack_version=PACK_VERSION,
        candidate_archive_sha256=ARCHIVE_SHA, candidate_map_row=row)
    assert changed.status == "needs_review"
    assert "database_pack_content_mismatch:stem" in changed.issues


def test_non_exact_or_conflicting_mapping_never_attests():
    q, node, item, row, _ = attested_fixture()
    for status, matches, count in (("POSSIBLE", [str(q.id)], 1), ("EXACT", [str(q.id), "other"], 2)):
        candidate_row = {**row, "mapping_status": status, "matched_question_ids": json.dumps(matches),
            "match_count": str(count)}
        result = assess_source_attestation(question=q, node=node, pack_question=item,
            pack_id=PACK_ID, pack_version=PACK_VERSION,
            candidate_archive_sha256=ARCHIVE_SHA, candidate_map_row=candidate_row)
        assert result.status == "needs_review"
        assert "candidate_mapping_not_unique_exact" in result.issues


def test_ai_answer_replacement_does_not_break_question_source_attestation():
    q, node, item, row, assessment = attested_fixture()
    q.source_attestation_key = assessment.attestation_key
    q.source_attestation_sha256 = question_content_sha256(q)
    q.content_trust = "source_attested"
    q.correct_answer = "B"
    q.answer_provenance = "ai_generated"
    q.answer_reliability = "ai_generated_consistent"
    q.answer_attestation_key = answer_attestation_check_key(q, model="offline-fixture")
    q.answer_attestation_sha256 = answer_attestation_result_hash(q)

    result = assess_source_attestation(question=q, node=node, pack_question=item,
        pack_id=PACK_ID, pack_version=PACK_VERSION,
        candidate_archive_sha256=ARCHIVE_SHA, candidate_map_row=row)

    assert result.status == "source_attested"
    assert result.question_content_sha256 == q.source_attestation_sha256
    assert has_current_source_attestation(q)
