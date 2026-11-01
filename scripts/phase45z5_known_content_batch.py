"""Source-bound fixes and ambiguity holds for Phase 4.5Z-5 on the owned isolated DB."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from copy import deepcopy
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DB_NAME = "phase45z5_work_20261013_test"
PORT = 59227
SYSTEM_ID = "7694698872540080852"
BACKUP = ROOT / "storage/quality-audits/phase45z5-20261013/z5-batch1/work-before-content-batch.dump"
BACKUP_SHA256 = "F67B18FCDECB5FCFC813F9B5AE0969ED37AF31B2A1A98D78B0B47389FCFAFAA2"
OLD_PACK_PATH = ROOT / "storage/question-intake/past-exam-import-20261005-v3-160318/question-pack.json"
NEW_PACK_PATH = ROOT / "storage/question-intake/phase45z5-20261013/curated-source-fixes-pack-v2.json"
AUDIT_DIR = ROOT / "storage/quality-audits/phase45z5-20261013/known-content"
Q019 = UUID("08090ad7-5265-49d8-a3d0-f7e3caff1ef0")
Q116 = UUID("a4b1ebc7-8a41-4bac-b442-7a7e283fa78b")
Q117 = UUID("711b6fee-6e56-4b42-934f-a1102c65f584")
AMBIGUOUS = {
    UUID("d2873296-3bb2-439d-83fe-94e38d434c3e"): "2017 Q39 omits initial congestion-window model; answer A requires cwnd=1 MSS and classic doubling assumption.",
    UUID("a46ccd63-1eca-44b6-a7be-9269d48280de"): "2018 Q23 statement I says concurrency and parallelism without qualifying single-CPU versus multiprocessor execution.",
    UUID("43f8ca19-ac3e-470c-a79a-40fe9082d06b"): "2026 recall Q4 does not fix the given forest-tree shapes; sizes alone may not determine the intended LCRS-height answer.",
    UUID("ec5c4bcf-0018-4a6a-8436-68b415ab8278"): "2026 recall Q11 does not state the initial-run generation model; replacement-selection assumptions can change the answer.",
}
PDFS = {
    "2021": (Path(r"C:\Users\ZBT\Desktop\考研知识点\408\2021\2021年计算机408统考真题.pdf"),
             "D932A05D911745CFB531DAFA044FA97FA00F336864C72E9982316334AF95F85F"),
    "2017": (Path(r"C:\Users\ZBT\Desktop\考研知识点\408\2017\2017年计算机408统考真题.pdf"),
             "16F9C9AFAC663BC64E4057FE666D4563091349F71BA4113C26F58A66EA449883"),
}


def file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def table_fingerprint(db: Session, model) -> tuple[int, str]:
    rows = []
    columns = list(model.__table__.columns)
    primary = [column.key for column in model.__table__.primary_key.columns]
    for row in db.scalars(select(model)).all():
        rows.append({column.key: getattr(row, column.key) for column in columns})
    rows.sort(key=lambda item: json.dumps([item.get(key) for key in primary], default=str))
    payload = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return len(rows), hashlib.sha256(payload.encode("utf-8")).hexdigest()


def policy_rule_fingerprint(db: Session) -> str:
    from backend.models.learning import KpMasteryPolicy
    rule_fields = ["min_confirmations", "min_real_questions", "required_question_types",
        "policy_version", "required_question_origins", "excluded_question_types",
        "required_skill_tags", "required_variant_count", "min_day_span",
        "manual_mastered_credit", "review_intervals_days"]
    rows = [{"kp_id": str(row.kp_id), **{field: getattr(row, field) for field in rule_fields}}
            for row in db.scalars(select(KpMasteryPolicy).order_by(KpMasteryPolicy.kp_id)).all()]
    payload = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_pack():
    from backend.services.question_pack import QuestionPack
    source_pack = QuestionPack.model_validate_json(OLD_PACK_PATH.read_text(encoding="utf-8"))
    by_source = {item.source_id: item for item in source_pack.questions}
    q19 = by_source["cs408-2021-q13"]
    q116 = by_source["cs408-2017-q33"]
    corrected_19 = q19.model_copy(update={
        "stem": "已知带符号整数 x、y、z 用 16 位补码表示，其机器数分别为 FFFDH、FFDFH、7FFCH，下列结论中正确的是（）。",
        "explanation": "先按无符号数读取：x=65533，y=65503，z=32764；因此 z<y<x，与 A、B 所写次序均不符。再按 16 位补码解码：x=−3，y=−33，z=32764，故 y<x<z，只有 D 正确。题干明确补码约定后，带符号比较不再依赖编码解释假设。",
    })
    corrected_116 = q116.model_copy(update={
        "stem": "假设 OSI 参考模型的应用层欲发送 400B 的数据（无拆分），除物理层和应用层之外，其他各层在封装 PDU 时均引入 20B 的额外开销，则应用层数据传输效率约为____。",
        "explanation": "OSI 七层中排除物理层与应用层后，还有数据链路、网络、传输、会话、表示五层；合计开销为 5×20=100B。无拆分时总传输量为 400+100=500B，应用数据效率为 400/500=80%，选 A。",
    })
    pack = QuestionPack(pack_id="phase45z5-curated-corrections-20261013-v2",
        version="2026-10-13-source-fix-v2", questions=[corrected_19, corrected_116])
    NEW_PACK_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(pack.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"
    if NEW_PACK_PATH.exists():
        existing = QuestionPack.model_validate_json(NEW_PACK_PATH.read_text(encoding="utf-8"))
        if existing.model_dump(mode="json") != pack.model_dump(mode="json"):
            raise ValueError("corrected_source_pack_path_exists_with_different_content")
    else:
        NEW_PACK_PATH.write_text(payload, encoding="utf-8", newline="\n")
    # Fingerprints must be computed from the exact serialized artifact that the
    # local registry will load; Pydantic's fields_set differs before/after IO.
    return QuestionPack.model_validate_json(NEW_PACK_PATH.read_text(encoding="utf-8"))


def write_obsolescence_overlay() -> dict:
    paths = [ROOT / "storage/question-intake/recent-two-years-20261003/math2025-completion.json",
        ROOT / "storage/question-intake/recent-two-years-20261003/math2025-completion-pack-v1.json",
        ROOT / "storage/question-intake/recent-two-years-20261003/math2025-before-correction-pack-v1.json"]
    evidence = []
    for path in paths:
        if path.is_file():
            evidence.append({"path": path.relative_to(ROOT).as_posix(), "sha256": file_sha(path),
                "classification": "OBSOLETE_CONFLICTING_COMPLETION_DRAFT",
                "conflict": "2025 数学二 Q11 原卷为分子 a、答案 2；该旧草稿误记分子 3、答案 6。原文件未修改。"})
    if not evidence:
        raise ValueError("legacy_math2025_completion_drafts_not_found")
    overlay = {"phase": "Phase 4.5Z-5", "created_at": datetime.now(timezone.utc).isoformat(),
        "question_id": str(Q117), "source": "2025 数学二 PDF 第 3 页 Q11；SHA-256 " + "2957F10B801898EFEAC9755F9DCACF2D8D347710CCE15B6D79F3DEDE7A2EC2DD",
        "current_question_action": "KEEP_UNCHANGED; existing stem numerator a and answer 2 are source-consistent",
        "obsolete_artifacts": evidence, "historical_files_modified": False}
    path = AUDIT_DIR / "obsolete-q117-completion-draft-overlay.json"
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(overlay, ensure_ascii=False, indent=2) + "\n"
    if path.exists():
        previous = json.loads(path.read_text(encoding="utf-8"))
        # Hash-bound paths remain stable; creation timestamps are intentionally ignored.
        old = [{"path": item["path"], "sha256": item["sha256"]} for item in previous.get("obsolete_artifacts", [])]
        new = [{"path": item["path"], "sha256": item["sha256"]} for item in evidence]
        if old != new:
            raise ValueError("obsolete_override_overlay_conflict")
        return previous
    path.write_text(encoded, encoding="utf-8", newline="\n")
    return overlay


def _source_review(question, node, *, source_pack_evidence, registry):
    from scripts.audit_phase45h_completion_archive import source_pack_evidence as make_evidence
    evidence = make_evidence(question, registry, node)
    if evidence is None or evidence.get("mapped_node_code") != node.code:
        provenance = (question.grading_config or {}).get("provenance", {})
        raise ValueError(f"corrected_source_evidence_missing:{question.id}:"
            f"node={node.code}:key={provenance.get('key')}:sha={provenance.get('sha256')}:"
            f"registry={[(item.get('fingerprint'), item.get('path')) for item in registry.get(provenance.get('key'), [])]}")
    return evidence


def _review_methods(question_id: UUID):
    if question_id == Q019:
        return {
            "derived_answer": "D",
            "methods": [
                {"method": "signed_twos_complement_decode", "result": "按 16 位补码减去 65536：FFFDH=-3、FFDFH=-33、7FFCH=32764，故 D 的 y<x<z 成立。"},
                {"method": "unsigned_hex_order_crosscheck", "result": "按十六进制/无符号换算为65533、65503、32764，确认 A/B 均错；逐项代入带符号次序后仅 D 为真。"},
            ],
            "steps": ["先区分无符号与带符号解释；16 位补码负数的真值等于编码值减 2^16。", "得到 x=-3、y=-33、z=32764，按数轴排列 y<x<z，故选 D。"],
            "truth": {"A": False, "B": False, "C": False, "D": True},
        }
    return {
        "derived_answer": "A",
        "methods": [
            {"method": "osi_layer_count", "result": "七层中扣除物理层和应用层，恰有数据链路、网络、传输、会话、表示五层，每层20B，合计100B额外封装。"},
            {"method": "exact_byte_ratio", "result": "原应用数据400B，总传输量500B；用整数计算400/500=4/5=80%，与选项A一致。"},
        ],
        "steps": ["数清题目指定产生开销的五层，开销总量为5×20=100B。", "总量为500B，应用数据占比400/500=80%，因此选A。"],
        "truth": {"A": True, "B": False, "C": False, "D": False},
    }


def _requalify(db, question, node, evidence, all_questions, revision_key):
    from backend.services.auto_question_review import (
        assess_auto_qualification, attach_codex_independent_review,
        current_auto_review, qualify_public_question, question_snapshot_sha256,
    )
    from backend.services.question_eligibility import question_eligibility
    review = _review_methods(question.id)
    attach_codex_independent_review(question, node, derived_answer=review["derived_answer"],
        method_evidence=review["methods"], explanation_key_steps=review["steps"],
        option_truth_table=review["truth"], reviewed_on="2026-10-13")
    db.flush()
    assessment = assess_auto_qualification(db, question, node, source_evidence=evidence,
        all_questions=all_questions)
    if assessment.get("status") != "AUTO_VERIFIED":
        raise ValueError("corrected_question_did_not_pass_current_auto_review:" + json.dumps(assessment, ensure_ascii=False, default=str))
    snap = question_snapshot_sha256(question)
    event, final = qualify_public_question(db, question_id=question.id, node_id=node.id,
        expected_snapshot_sha256=snap,
        idempotency_key=f"phase45z5-known-fix:{revision_key}:{snap}", source_evidence=evidence)
    if event is None or current_auto_review(question, node) is None:
        raise ValueError("corrected_question_requalification_failed")
    eligibility = question_eligibility(question, node)
    if not (eligibility.practice_eligible and eligibility.evidence_capability == "verified_objective"
            and eligibility.grading_capability == "deterministic"):
        raise ValueError("corrected_question_not_formal_after_requalification")
    return {"question_id": str(question.id), "node_code": node.code,
        "new_auto_review_event_id": str(event.id), "status": final.get("status"),
        "snapshot_sha256": question_snapshot_sha256(question),
        "answer_sha256": event.answer_sha256,
        "source_pack": evidence["source_pack_id"], "source_pack_file_sha256": evidence["source_archive_sha256"],
        "verbatim_verified": evidence.get("verbatim_verified"), "human_verified": False}


def _formal_question_ids(db, node):
    from backend.models.learning import Question
    from backend.services.question_eligibility import question_eligibility
    rows = list(db.scalars(select(Question).where(Question.kp_id == node.id,
        Question.bank_scope == "public", Question.generation_batch_id.is_(None)).order_by(Question.id)))
    ids = [row.id for row in rows if question_eligibility(row, node).practice_eligible
        and question_eligibility(row, node).evidence_capability == "verified_objective"
        and question_eligibility(row, node).grading_capability == "deterministic"]
    return ids


def execute(db: Session, pack, pack_sha: str) -> dict:
    from backend.models.learning import (KpGraduationQuestionSetVersion, KpMasteryPolicy,
        KpState, KnowledgePoint, LearningEvent, Question, QuestionAnswerVerificationEvent,
        QuestionAttempt, QuestionAutoReviewEvent)
    from backend.services.auto_question_review import current_auto_review, revoke_auto_qualification, question_snapshot_sha256
    from backend.services.answer_verification import answer_version_sha256, revoke_answer_verification
    from backend.services.graduation_question_set import publish_all_public_question_set_version, question_set_sha256
    from backend.services.question_answer_revision import revise_qualified_public_stem
    from backend.services.question_pack import fingerprint
    from backend.services.question_repair import local_pack_registry
    from backend.services.question_attestation import question_content_sha256

    identity = db.execute(text("SELECT current_database(), inet_server_port(), system_identifier FROM (SELECT current_database() current_database, inet_server_port() inet_server_port, system_identifier FROM pg_control_system()) s" )).one()
    if identity.current_database != DB_NAME or identity.inet_server_port != PORT or str(identity.system_identifier) != SYSTEM_ID:
        raise ValueError("isolated_database_identity_mismatch")
    question_count_before = db.query(Question).count()
    event_count_before = db.query(QuestionAutoReviewEvent).count()
    set_count_before = db.query(KpGraduationQuestionSetVersion).count()
    protected_before = {"attempts": table_fingerprint(db, QuestionAttempt),
        "learning_events": table_fingerprint(db, LearningEvent), "kp_states": table_fingerprint(db, KpState)}
    rules_before = policy_rule_fingerprint(db)
    registry, _ = local_pack_registry(ROOT)
    all_questions = list(db.scalars(select(Question).where(Question.bank_scope == "public",
        Question.generation_batch_id.is_(None))).all())

    results = {"corrections": [], "holds": [], "publications": []}
    for qid in (Q019, Q116):
        q = db.scalar(select(Question).where(Question.id == qid).with_for_update())
        if q is None or q.question_provenance != "real_exam" or q.bank_scope != "public":
            raise ValueError(f"curated_question_missing_or_origin_changed:{qid}")
        if db.scalar(select(QuestionAttempt.id).where(QuestionAttempt.question_id == qid).limit(1)):
            raise ValueError(f"cannot_correct_question_after_learner_attempt:{qid}")
        node = db.get(KnowledgePoint, q.kp_id)
        current = current_auto_review(q, node)
        if current is None or current.qualification_class != "exam_curated":
            raise ValueError(f"curated_question_current_auto_review_missing:{qid}")
        if qid == Q019:
            if q.correct_answer != "D" or q.options != {"A": "无符号 z<x<y", "B": "无符号 x<y<z", "C": "带符号 x<y<z", "D": "带符号 y<x<z"}:
                raise ValueError("Q019_live_options_or_answer_drifted")
            new_stem = "已知带符号整数 x、y、z 用 16 位补码表示，其机器数分别为 FFFDH、FFDFH、7FFCH，下列结论中正确的是（）。"
            changes = {"stem": new_stem}
            revision_key = "phase45z5-q019-restore-twos-complement-v1"
        else:
            if q.correct_answer != "A" or "数据链路层发送的数据部分" not in q.stem:
                raise ValueError("Q116_live_content_drifted")
            new_stem = "假设 OSI 参考模型的应用层欲发送 400B 的数据（无拆分），除物理层和应用层之外，其他各层在封装 PDU 时均引入 20B 的额外开销，则应用层数据传输效率约为____。"
            explanation = ("OSI 七层中排除物理层与应用层后，还有数据链路、网络、传输、会话、表示五层；"
                "合计开销为 5×20=100B。无拆分时总传输量为 400+100=500B，"
                "应用数据效率为 400/500=80%，选 A。")
            changes = {"stem": new_stem, "explanation": explanation}
            revision_key = "phase45z5-q116-source-wording-and-explanation-v1"
        evidence_item = next(item for item in pack.questions if item.source_id ==
            ("cs408-2021-q13" if qid == Q019 else "cs408-2017-q33"))
        source_key = f"{pack.pack_id}:{evidence_item.source_id}"
        source_question_fingerprint = fingerprint(evidence_item)
        preview = revise_qualified_public_stem(db, qid, question_snapshot_sha256(q), current.id,
            changes, basis=("按本机原卷 PDF 页面核对并恢复转录遗漏。该来源是本地扫描件线索，"
                "不声称官方来源认证或公开再分发许可。题面、解析变化均留版本记录。"),
            source_pack_key=source_key, source_pack_sha256=source_question_fingerprint,
            source_pack_version=pack.version, revision_key=revision_key, apply=False)
        applied = revise_qualified_public_stem(db, qid, question_snapshot_sha256(q), current.id,
            changes, basis=("按本机原卷 PDF 页面核对并恢复转录遗漏。该来源是本地扫描件线索，"
                "不声称官方来源认证或公开再分发许可。题面、解析变化均留版本记录。"),
            source_pack_key=source_key, source_pack_sha256=source_question_fingerprint,
            source_pack_version=pack.version, revision_key=revision_key, apply=True)
        db.flush()
        q = db.get(Question, qid)
        source_evidence = _source_review(q, node, source_pack_evidence=None, registry=registry)
        # The correction service deliberately downgrades trust on mutation.
        # Restore only the weaker source-identity state after a new local pack
        # binding is present; answer trust remains unverified until the new
        # content-bound review event is accepted below.
        q.source_status = "traceable"
        review = _review_methods(qid)
        attach_args = {"derived_answer": review["derived_answer"], "method_evidence": review["methods"],
            "explanation_key_steps": review["steps"], "option_truth_table": review["truth"],
            "reviewed_on": "2026-10-13"}
        from backend.services.auto_question_review import attach_codex_independent_review
        attach_codex_independent_review(q, node, **attach_args)
        db.flush()
        assessment = __import__("backend.services.auto_question_review", fromlist=["assess_auto_qualification"]).assess_auto_qualification(
            db, q, node, source_evidence=source_evidence, all_questions=all_questions)
        if assessment.get("status") != "AUTO_VERIFIED":
            stages = assessment.get("stages", {})
            concise = {name: {key: value for key, value in stage.items()
                              if key in {"status", "reason", "issues", "blockers"}}
                       for name, stage in stages.items() if isinstance(stage, dict)}
            raise ValueError("corrected_question_quality_check_failed:" + json.dumps(
                {"status": assessment.get("status"), "stages": concise}, ensure_ascii=False, default=str))
        event, qualified = __import__("backend.services.auto_question_review", fromlist=["qualify_public_question"]).qualify_public_question(
            db, question_id=q.id, node_id=node.id, expected_snapshot_sha256=question_snapshot_sha256(q),
            idempotency_key=f"phase45z5-requalified:{revision_key}:{question_snapshot_sha256(q)}",
            source_evidence=source_evidence)
        if event is None or qualified.get("status") != "AUTO_VERIFIED" or current_auto_review(q, node) is None:
            raise ValueError("corrected_question_requalification_failed")
        results["corrections"].append({"preview": preview, "applied": applied,
            "source_pdf_sha256": PDFS["2021" if qid == Q019 else "2017"][1],
            "source_pack_question_fingerprint": fingerprint(evidence_item),
            "requalification": {"event_id": str(event.id), "status": qualified["status"],
                "question_content_sha256": question_content_sha256(q),
                "answer_sha256": answer_version_sha256(q), "current": True}})

    for qid, reason in AMBIGUOUS.items():
        q = db.scalar(select(Question).where(Question.id == qid).with_for_update())
        if q is None or q.question_provenance != "real_exam" or q.bank_scope != "public":
            raise ValueError(f"ambiguous_item_missing_or_origin_changed:{qid}")
        if db.scalar(select(QuestionAttempt.id).where(QuestionAttempt.question_id == qid).limit(1)):
            raise ValueError(f"risk_hold_refused_after_attempt:{qid}")
        node = db.get(KnowledgePoint, q.kp_id)
        state = db.get(KpState, node.id)
        if state is not None and (state.state != "unseen" or state.graduation_set_version is not None or state.mastered_at is not None):
            raise ValueError(f"risk_hold_requires_started_learner_pinning_review:{qid}")
        current = current_auto_review(q, node)
        if current is None:
            results["holds"].append({"question_id": str(qid), "status": "ALREADY_WITHDRAWN"})
            continue
        revoked = revoke_auto_qualification(db, question_id=qid, expected_event_id=current.id,
            expected_snapshot_sha256=question_snapshot_sha256(q),
            idempotency_key=f"phase45z5-risk-hold:auto-revoke:{qid}:{current.id}")
        verification_revoked = None
        if q.answer_verification_event_id is not None:
            verification_revoked = revoke_answer_verification(db, question_id=qid,
                expected_event_id=q.answer_verification_event_id, verifier="system-risk-triage",
                method="source-assumption-risk-hold-v1", note=reason,
                idempotency_key=f"phase45z5-risk-hold:answer-revoke:{qid}:{q.answer_verification_event_id}",
                expected_answer_sha256=answer_version_sha256(q))
        q.content_trust = "needs_review"
        q.source_status = "needs_review"
        q.source_attestation_key = None
        q.source_attestation_sha256 = None
        q.answer_attestation_key = None
        q.answer_attestation_sha256 = None
        q.answer_reliability = "unverified"
        config = deepcopy(q.grading_config or {})
        config["verified"] = False
        config["method"] = None
        holds = list(config.get("quality_holds", [])) if isinstance(config.get("quality_holds"), list) else []
        hold_id = f"phase45z5-source-risk:{qid}"
        if not any(isinstance(item, dict) and item.get("id") == hold_id for item in holds):
            holds.append({"version": "question-quality-hold-v1", "id": hold_id, "status": "OPEN",
                "reason": reason, "source_review": "storage/quality-audits/phase45z-20261012/legacy-source-findings-019-116-117-137-195.json plus 2026 recall-source review",
                "created_at": datetime.now(timezone.utc).isoformat(), "human_verified": False})
        config["quality_holds"] = holds
        q.grading_config = config
        db.flush()
        results["holds"].append({"question_id": str(qid), "node_code": node.code,
            "revoked_auto_event_id": str(revoked.id),
            "revoked_answer_verification_event_id": str(verification_revoked.id) if verification_revoked else None,
            "hold_id": hold_id, "reason": reason, "current_auto_review": False,
            "learner_attempts": 0, "history_rewritten": False})

    affected = {UUID(item["node_code_id"]) if item.get("node_code_id") else None for item in []}
    affected_nodes = {db.get(Question, qid).kp_id for qid in [Q019, Q116, *AMBIGUOUS.keys()]}
    for kp_id in sorted(affected_nodes, key=str):
        node = db.get(KnowledgePoint, kp_id)
        policy = db.scalar(select(KpMasteryPolicy).where(KpMasteryPolicy.kp_id == kp_id).with_for_update())
        if policy is None or policy.policy_version != 3 or not policy.graduation_set_version:
            raise ValueError(f"v3_policy_or_current_set_missing:{node.code}")
        previous = db.get(KpGraduationQuestionSetVersion, (kp_id, policy.graduation_set_version))
        if previous is None:
            raise ValueError(f"current_set_version_row_missing:{node.code}")
        ids = _formal_question_ids(db, node)
        if not ids:
            raise ValueError(f"refusing_empty_graduation_set:{node.code}")
        _, publication = publish_all_public_question_set_version(db, kp_id=kp_id,
            question_ids=ids, expected_set_version=policy.graduation_set_version,
            expected_set_sha256=previous.question_ids_sha256,
            publication_key=f"phase45z5-known-content-{node.code}-v1",
            reason="Source-bound Q019/Q116 transcription corrections and/or open source-assumption risk holds; old frozen set retained.")
        results["publications"].append({"node_code": node.code,
            "old_version": publication.get("old_set_version", policy.graduation_set_version),
            "new_version": publication.get("set_version", policy.graduation_set_version),
            "formal_question_count": len(ids), "status": publication["status"],
            "learner_history_modified": publication.get("learner_history_modified", False)})

    q253 = db.get(Question, UUID("6d6ae0e5-e765-4acb-9c32-a824cd35bd84"))
    if q253 is None or q253.correct_answer != "D" or current_auto_review(q253, q253.kp) is None:
        raise ValueError("previously_fixed_Q253_not_stable")
    results["q253"] = {"status": "UNCHANGED_ALREADY_FIXED", "answer": q253.correct_answer,
        "question_id": str(q253.id), "current_auto_review": True}

    after_question_count = db.query(Question).count()
    protected_after = {"attempts": table_fingerprint(db, QuestionAttempt),
        "learning_events": table_fingerprint(db, LearningEvent), "kp_states": table_fingerprint(db, KpState)}
    rules_after = policy_rule_fingerprint(db)
    if after_question_count != question_count_before or protected_after != protected_before or rules_after != rules_before:
        raise ValueError("protected_history_or_graduation_algorithm_changed")
    if db.query(QuestionAutoReviewEvent).count() < event_count_before:
        raise ValueError("auto_review_event_history_shrank")
    results["before"] = {"questions": question_count_before, "auto_review_events": event_count_before,
        "set_versions": set_count_before, "policy_rule_fingerprint": rules_before,
        "protected_history": protected_before}
    results["after"] = {"questions": after_question_count,
        "auto_review_events": db.query(QuestionAutoReviewEvent).count(),
        "set_versions": db.query(KpGraduationQuestionSetVersion).count(),
        "policy_rule_fingerprint": rules_after, "protected_history": protected_after}
    results["database"] = {"name": DB_NAME, "port": PORT, "system_identifier": SYSTEM_ID}
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices={"dry-run", "apply"}, required=True)
    args = parser.parse_args()
    from backend.models.learning import Question
    from backend.services.question_pack import fingerprint
    from backend.services.question_repair import local_pack_registry
    from backend.services.auto_question_review import current_auto_review
    from backend.models.learning import KnowledgePoint
    from sqlalchemy import create_engine

    for key, (path, expected) in PDFS.items():
        if not path.is_file() or file_sha(path) != expected:
            raise SystemExit(f"source_pdf_missing_or_sha_mismatch:{key}")
    if not BACKUP.is_file() or file_sha(BACKUP) != BACKUP_SHA256:
        raise SystemExit("required_prechange_backup_missing_or_sha_mismatch")
    import subprocess
    pg_restore = Path(r"C:\Program Files\PostgreSQL\18\bin\pg_restore.exe")
    toc = subprocess.run([str(pg_restore), "--list", str(BACKUP)], capture_output=True, timeout=30)
    if toc.returncode != 0 or b"TABLE DATA public questions" not in toc.stdout:
        raise SystemExit("prechange_backup_toc_invalid")
    pack = build_pack()
    # The protected revision service expects lowercase hexadecimal SHA-256.
    pack_sha = file_sha(NEW_PACK_PATH).lower()
    registry, _ = local_pack_registry(ROOT)
    for item in pack.questions:
        if len(registry.get(f"{pack.pack_id}:{item.source_id}", [])) != 1:
            raise SystemExit(f"corrected_pack_registry_binding_invalid:{item.source_id}")
    obsolescence_overlay = write_obsolescence_overlay()
    engine = create_engine(URL.create("postgresql+psycopg", username="postgres", host="127.0.0.1",
        port=PORT, database=DB_NAME), pool_pre_ping=True)
    report = None
    try:
        with Session(engine, expire_on_commit=False) as db:
            db.begin()
            try:
                report = execute(db, pack, pack_sha)
                report["source_pack"] = {"path": NEW_PACK_PATH.relative_to(ROOT).as_posix(),
                    "sha256": pack_sha, "version": pack.version,
                    "question_fingerprints": {item.source_id: fingerprint(item) for item in pack.questions}}
                report["q117_obsolescence_overlay"] = obsolescence_overlay
                if args.mode == "dry-run":
                    db.rollback()
                    report["status"] = "DRY_RUN_ROLLED_BACK"
                else:
                    db.commit()
                    report["status"] = "APPLIED"
            except Exception:
                db.rollback()
                raise
        report["backup"] = {"path": BACKUP.relative_to(ROOT).as_posix(), "sha256": BACKUP_SHA256,
            "toc_entries": len(toc.stdout.splitlines()), "prechange_backup_valid": True}
        filename = "preview-2.json" if args.mode == "dry-run" else "checkpoint.json"
        output = AUDIT_DIR / filename
        if output.exists():
            raise SystemExit(f"refusing_to_overwrite_existing_report:{output}")
        AUDIT_DIR.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8", newline="\n")
        print(json.dumps({"status": report["status"], "corrections": report["corrections"],
            "holds": report["holds"], "publications": report["publications"],
            "q253": report["q253"], "question_count": report["after"]["questions"],
            "report": output.relative_to(ROOT).as_posix()}, ensure_ascii=True, default=str))
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
