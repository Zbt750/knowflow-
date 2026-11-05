"""Snapshot-bound repair/requalification of curated 408 item #253 on owned Z-5 test DBs."""
from __future__ import annotations

import argparse
import heapq
import json
import sys
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session
from sqlalchemy import create_engine

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.models.learning import (
    KpGraduationQuestionSetVersion,
    KpMasteryPolicy,
    KpState,
    LearningEvent,
    Question,
    QuestionAttempt,
    QuestionAutoReviewEvent,
)
from backend.services.auto_question_review import (
    assess_auto_qualification,
    attach_codex_independent_review,
    current_auto_review,
    qualify_public_question,
    revoke_auto_qualification,
    question_snapshot_sha256,
)
from backend.services.golden_learning_slice import digest
from backend.services.question_answer_revision import revise_transcription_content
from backend.services.question_attestation import question_content_sha256
from backend.services.question_eligibility import question_eligibility
from backend.services.question_pack import QuestionPack, fingerprint
from backend.services.question_verification_upgrade import snapshot


QUESTION_ID = UUID("6d6ae0e5-e765-4acb-9c32-a824cd35bd84")
OLD_EVENT_ID = UUID("d70a15b8-49e0-43da-8bff-985df12b9dc6")
EXPECTED_OLD_ANSWER_SHA = "45554c8c637956e0714a50d2c8a3d47146af9eaf138273a0ab24b02efe41c49f"
EXPECTED_CONTENT_SHA = "c52f9460941bf59224a5f7337a9cd1007b676f29ea1ee5e1c2ee3a51626b75a6"
EXPECTED_PDF_SHA = "f57dfb5e961f50969837026c43c7c0634831a5874cd51d0474e0771526fd584a"
SOURCE_PACK = ROOT / "storage/question-intake/recent-two-years-20261003/practice-pack-v1.json"
CORRECTION_PACK = ROOT / "storage/question-intake/phase45z5-20261013/curated-253-correction-pack-v2.json"
SOURCE_CONFIRMATION = ROOT / "storage/quality-audits/phase45z-20261013/curated-review-253-source-confirmation.json"
PDF_PATH = Path(r"C:\Users\ZBT\Desktop\考研知识点\408\2026\2026年计算机408统考真题_回忆版.pdf")
EXPECTED_OWNER_SYSTEM_ID = "7694698872540080852"
ALLOWED_DATABASES = {
    "phase45z5_work_20261013_test",
    "phase45z5_dryrun_20261013_test",
}
EXPLANATION = (
    "按 Huffman 算法每次合并当前权值最小的两棵树：1+2=3，3+4=7，5+7=12，"
    "8+10=18，12+12=24，最后合并18和24。权值8的e与权值10的f在权值18子树中，"
    "深度均为2；权值12的g在权值24子树中，深度也为2。权值5的d位于权值12的"
    "合并子树中，深度为3。因此与e同层的字符为f、g，选D。"
)


def _sha_file(path: Path) -> str:
    state = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            state.update(block)
    return state.hexdigest()


def _huffman_depths() -> dict[str, int]:
    weights = {"a": 1, "b": 2, "c": 4, "d": 5, "e": 8, "f": 10, "g": 12}
    queue = [(weight, index, symbol) for index, (symbol, weight) in enumerate(weights.items())]
    heapq.heapify(queue)
    sequence = len(queue)
    while len(queue) > 1:
        left_weight, _, left = heapq.heappop(queue)
        right_weight, _, right = heapq.heappop(queue)
        heapq.heappush(queue, (left_weight + right_weight, sequence, (left, right)))
        sequence += 1
    depths: dict[str, int] = {}

    def visit(node, depth):
        if isinstance(node, str):
            depths[node] = depth
            return
        visit(node[0], depth + 1)
        visit(node[1], depth + 1)

    visit(queue[0][2], 0)
    return depths


def _table_fingerprint(db: Session, model) -> str:
    primary = [column.key for column in model.__table__.primary_key.columns]
    values = []
    for row in db.scalars(select(model)).all():
        item = {column.key: getattr(row, column.key) for column in model.__table__.columns}
        values.append(item)
    values.sort(key=lambda row: json.dumps([row.get(key) for key in primary], ensure_ascii=False, default=str))
    payload = json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(payload.encode("utf-8")).hexdigest()


def _history_fingerprints(db: Session) -> dict[str, str]:
    return {
        "question_attempts": _table_fingerprint(db, QuestionAttempt),
        "learning_events": _table_fingerprint(db, LearningEvent),
        "kp_states": _table_fingerprint(db, KpState),
        "kp_mastery_policies": _table_fingerprint(db, KpMasteryPolicy),
        "graduation_set_versions": _table_fingerprint(db, KpGraduationQuestionSetVersion),
    }


def _read_packs():
    source_data = json.loads(SOURCE_PACK.read_text(encoding="utf-8"))
    source_pack = QuestionPack.model_validate(source_data)
    original = next(q for q in source_pack.questions if q.source_id == "408-2026-q005")
    if fingerprint(original) != "e46fb37def938cfc5761b5e6d155ba453d858cac5eee054dfe573924bdff281d":
        raise ValueError("original_source_pack_fingerprint_changed")
    correction_data = json.loads(CORRECTION_PACK.read_text(encoding="utf-8"))
    correction_pack = QuestionPack.model_validate(correction_data)
    corrected = correction_pack.questions[0]
    if (correction_pack.pack_id != source_pack.pack_id
            or correction_pack.version != "2-q253-correction-20261013"
            or corrected.source_id != original.source_id
            or corrected.correct_answer != "D"
            or corrected.explanation != EXPLANATION
            or corrected.stem != original.stem or corrected.options != original.options):
        raise ValueError("correction_pack_does_not_match_approved_content")
    return source_pack, original, correction_pack, corrected


def _source_evidence(*, question, node, pack, item, pack_sha: str) -> dict:
    return {
        "status": "TRACEABLE",
        "method": "curated_source_trace_v1",
        "question_content_sha256": question_content_sha256(question),
        "source_archive_sha256": pack_sha,
        "source_asset_path": "phase45z5-20261013/curated-253-correction-pack-v2.json",
        "source_pack_id": pack.pack_id,
        "source_pack_version": pack.version,
        "source_pack_question_fingerprint": fingerprint(item),
        "source_pack_content_comparison": {
            key: {"current_matches_pack": True, "retained_revision_matches_pack": True}
            for key in ("question_type", "stem", "options", "correct_answer", "explanation")
        },
        "source_pack_content_diff_fields": [],
        "source_locator": item.source.citation,
        "source_identity": {"subject": "408", "year": 2026, "question_number": 5},
        "verbatim_verified": False,
        "uncertainties": [
            "出处为用户提供的回忆版试卷，不是官方来源认证，也未确认公开再分发许可。",
            "原题源包答案与原页转录不一致；本次答案依据 Huffman 合并过程及独立最小堆深度计算更正。",
        ],
        "reconstruction_notes": "保留原题干、选项和节点映射；只纠正原页所示同层节点的答案及教学解析。",
        "mapped_node_code": node.code,
    }


def _assert_source_assets(pack_sha: str) -> None:
    if not PDF_PATH.is_file() or _sha_file(PDF_PATH) != EXPECTED_PDF_SHA:
        raise ValueError("reviewed_pdf_missing_or_hash_changed")
    if _sha_file(CORRECTION_PACK) != pack_sha:
        raise ValueError("correction_pack_hash_changed")
    confirmation = json.loads(SOURCE_CONFIRMATION.read_text(encoding="utf-8"))
    if (confirmation.get("question_id") != str(QUESTION_ID)
            or confirmation.get("before", {}).get("answer") != "C"
            or confirmation.get("proposed_after", {}).get("answer") != "D"
            or confirmation.get("local_source", {}).get("sha256") != EXPECTED_PDF_SHA):
        raise ValueError("source_confirmation_report_does_not_match")


def _apply(db: Session, *, apply: bool) -> dict:
    source_pack, original, correction_pack, corrected_pack_question = _read_packs()
    correction_sha = fingerprint(corrected_pack_question)
    pack_sha = _sha_file(CORRECTION_PACK)
    _assert_source_assets(pack_sha)
    depths = _huffman_depths()
    if depths != {"a": 5, "b": 5, "c": 4, "d": 3, "e": 2, "f": 2, "g": 2}:
        raise ValueError("independent_huffman_heap_check_failed")
    same_level_peers = {node for node, depth in depths.items()
                        if node != "e" and depth == depths["e"]}
    truth_table = {
        "A": {"d"} == same_level_peers,
        "B": {"g"} == same_level_peers,
        "C": {"d", "f"} == same_level_peers,
        "D": {"f", "g"} == same_level_peers,
    }
    if truth_table != {"A": False, "B": False, "C": False, "D": True}:
        raise ValueError("single_choice_option_crosscheck_failed")

    row = db.scalar(select(Question).where(Question.id == QUESTION_ID).with_for_update())
    if row is None:
        raise ValueError("question_missing")
    node = row.kp
    before_hashes = _history_fingerprints(db)
    before_counts = {
        "questions": db.query(Question).count(),
        "auto_review_events": db.query(QuestionAutoReviewEvent).count(),
        "set_versions": db.query(KpGraduationQuestionSetVersion).count(),
    }
    current = current_auto_review(row, node)
    provenance = (row.grading_config or {}).get("provenance", {})
    if (row.correct_answer == "D" and provenance.get("sha256") == correction_sha
            and current is not None and current.answer_sha256 == EXPECTED_NEW_ANSWER_SHA):
        return {"status": "NOOP", "question_id": str(row.id), "answer": row.correct_answer,
                "auto_review_event_id": str(current.id), "before_counts": before_counts,
                "history_fingerprints_unchanged": True}
    if (row.correct_answer != "C" or row.auto_review_event_id != OLD_EVENT_ID
            or row.answer_verification_event_id is not None
            or provenance.get("sha256") != "e46fb37def938cfc5761b5e6d155ba453d858cac5eee054dfe573924bdff281d"
            or row.question_provenance != "real_exam"
            or current is None or current.id != OLD_EVENT_ID
            or current.qualification_class != "exam_curated"
            or question_content_sha256(row) != EXPECTED_CONTENT_SHA):
        raise ValueError("live_question_snapshot_does_not_match_reviewed_baseline")
    if node.code != "cs408.ds.topic.c8089470af79" or row.question_type != "single_choice":
        raise ValueError("question_mapping_or_type_changed")
    before = snapshot(row)
    before_snapshot_sha = digest(before)
    old_event = current
    source_evidence = _source_evidence(question=row, node=node, pack=correction_pack,
                                       item=corrected_pack_question, pack_sha=pack_sha)

    revoke_auto_qualification(db, question_id=row.id, expected_event_id=old_event.id,
        expected_snapshot_sha256=question_snapshot_sha256(row),
        idempotency_key=f"phase45z5-q253-revoke:{old_event.id}:{before_snapshot_sha}")

    from backend.services.answer_verification import answer_version_sha256
    from backend.services.auto_question_review import attach_codex_independent_review

    updated_snapshot = snapshot(row)
    correction = revise_transcription_content(
        db, row.id, digest(updated_snapshot),
        {"correct_answer": "D", "explanation": EXPLANATION},
        basis=("2026年408回忆版 PDF 第1–2页（SHA-256 " + EXPECTED_PDF_SHA + "); "
               "逐步 Huffman 合并为 3、7、12、18、24，最小堆实现得到叶深度 "
               "a=5,b=5,c=4,d=3,e=2,f=2,g=2，故与 e 同层的完整集合为 {f,g}，选 D。"),
        proposed_source_pack_sha256=correction_sha,
        proposed_pack_version=correction_pack.version,
        allow_unverified_grader=True,
        apply=True,
    )
    config = deepcopy(row.grading_config or {})
    old_receipt = config.pop("codex_independent_review", None)
    if isinstance(old_receipt, dict):
        history = list(config.get("superseded_codex_independent_reviews", []))
        history.append({**old_receipt, "superseded_reason": "answer_and_explanation_corrected_from_source_page",
                        "superseded_by_pack_version": correction_pack.version})
        config["superseded_codex_independent_reviews"] = history
    row.grading_config = config
    attach_codex_independent_review(
        row, node,
        derived_answer="D",
        method_evidence=[
            {"method": "manual_huffman_merge_and_level_analysis",
             "result": "按最小权值逐次合并：1+2=3，3+4=7，5+7=12，8+10=18，12+12=24，18+24=42；由树的左右层次直接看出e、f、g深度均为2，d深度3。"},
            {"method": "independent_heap_simulation_leaf_depths",
             "result": "独立使用Python heapq构造Huffman树并递归统计叶深度，得到a5、b5、c4、d3、e2、f2、g2；同层完整集合与手算一致为f、g。"},
        ],
        explanation_key_steps=[
            "每次取最小的两棵树合并，并更新其父结点权值。",
            "最终根的18子树包含e、f；24子树包含g及其余较深叶子。",
            "按根深度为0统计，e、f、g深度为2，d深度为3；故答案D。",
        ],
        option_truth_table=truth_table,
        reviewed_on="2026-10-13",
    )
    evidence = _source_evidence(question=row, node=node, pack=correction_pack,
                                item=corrected_pack_question, pack_sha=pack_sha)
    answer_sha = answer_version_sha256(row)
    if answer_sha != EXPECTED_NEW_ANSWER_SHA:
        raise ValueError("corrected_answer_version_sha_does_not_match_review_record")
    assessment = assess_auto_qualification(db, row, node, source_evidence=evidence,
        all_questions=list(db.scalars(select(Question)).all()))
    if assessment.get("status") != "AUTO_VERIFIED":
        raise ValueError("corrected_question_failed_current_auto_review: " +
                         json.dumps(assessment, ensure_ascii=False, default=str))
    new_snapshot_sha = question_snapshot_sha256(row)
    event, final_assessment = qualify_public_question(
        db, question_id=row.id, node_id=node.id, expected_snapshot_sha256=new_snapshot_sha,
        idempotency_key=f"phase45z5-q253-corrected:{correction_pack.version}:{new_snapshot_sha}",
        source_evidence=evidence,
    )
    if event is None or current_auto_review(row, node) is None:
        raise ValueError("corrected_question_was_not_requalified")
    eligible = question_eligibility(row, node)
    if not (eligible.practice_eligible and eligible.evidence_capability == "verified_objective"
            and eligible.grading_capability == "deterministic"):
        raise ValueError("corrected_question_not_formal_after_requalification")
    if (row.correct_answer != "D" or row.stem != before["stem"] or row.options != before["options"]
            or row.kp_id != UUID(before["kp_id"]) or answer_version_sha256(row) != EXPECTED_NEW_ANSWER_SHA
            or question_content_sha256(row) != EXPECTED_CONTENT_SHA):
        raise ValueError("postcondition_failed")
    after_hashes = _history_fingerprints(db)
    if after_hashes != before_hashes:
        raise ValueError("learner_history_or_graduation_sets_changed")
    after_counts = {
        "questions": db.query(Question).count(),
        "auto_review_events": db.query(QuestionAutoReviewEvent).count(),
        "set_versions": db.query(KpGraduationQuestionSetVersion).count(),
    }
    if (after_counts["questions"] != before_counts["questions"]
            or after_counts["auto_review_events"] != before_counts["auto_review_events"] + 2
            or after_counts["set_versions"] != before_counts["set_versions"]):
        raise ValueError("unexpected_row_count_delta")
    return {
        "status": "APPLIED_IN_TRANSACTION" if apply else "DRY_RUN_ROLLBACK_REQUIRED",
        "question_id": str(row.id),
        "node_code": node.code,
        "before_snapshot_sha256": before_snapshot_sha,
        "after_snapshot_sha256": new_snapshot_sha,
        "before_answer_sha256": EXPECTED_OLD_ANSWER_SHA,
        "after_answer_sha256": answer_sha,
        "question_content_sha256_unchanged": question_content_sha256(row),
        "old_auto_review_event_id": str(old_event.id),
        "new_auto_review_event_id": str(event.id),
        "revocation_event_appended": True,
        "correction": correction,
        "source_pack_fingerprint": correction_sha,
        "source_pack_file_sha256": pack_sha,
        "source_pdf_sha256": EXPECTED_PDF_SHA,
        "huffman_leaf_depths": depths,
        "single_choice_truth_table": truth_table,
        "auto_review_status": final_assessment["status"],
        "formal_eligibility": {"practice": eligible.practice_eligible,
            "evidence": eligible.evidence_capability, "grading": eligible.grading_capability},
        "before_counts": before_counts,
        "after_counts": after_counts,
        "history_fingerprints_unchanged": True,
        "history_fingerprints": after_hashes,
        "graduation_sets_or_policies_changed": False,
        "human_verified": False,
    }


EXPECTED_NEW_ANSWER_SHA = "b57e38779b5010a097b7c180e81281045288b242e0968a06b757cafa79bed1ca"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True, choices=sorted(ALLOWED_DATABASES))
    parser.add_argument("--mode", choices={"dry-run", "apply"}, required=True)
    args = parser.parse_args()
    if args.database not in ALLOWED_DATABASES:
        raise SystemExit("database_not_in_explicit_isolated_allowlist")
    url = URL.create("postgresql+psycopg", username="postgres", host="127.0.0.1",
                     port=59227, database=args.database)
    engine = create_engine(url, pool_pre_ping=True)
    output = None
    try:
        with Session(engine, expire_on_commit=False) as db:
            db.begin()
            try:
                system_id = str(db.execute(text("SELECT system_identifier FROM pg_control_system()" )).scalar_one())
                if system_id != EXPECTED_OWNER_SYSTEM_ID:
                    raise ValueError("isolated_postgres_system_identifier_mismatch")
                output = _apply(db, apply=args.mode == "apply")
                if args.mode == "dry-run":
                    db.rollback()
                else:
                    db.commit()
            except Exception:
                db.rollback()
                raise
        if args.mode == "dry-run":
            output["status"] = "DRY_RUN_ROLLED_BACK"
        else:
            with Session(engine) as verify_db:
                row = verify_db.get(Question, QUESTION_ID)
                node = row.kp
                if (row.correct_answer != "D" or not current_auto_review(row, node)
                        or row.auto_review_event_id is None):
                    raise ValueError("post_commit_verification_failed")
                output["post_commit_recheck"] = "PASS"
        print(json.dumps(output, ensure_ascii=False, indent=2, default=str))
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
