"""Audited answer enrichment for unverified source transcriptions only."""
from copy import deepcopy
from datetime import datetime, timezone
from sqlalchemy import select
from backend.models.learning import KnowledgePoint, Question
from backend.services.question_pack import QuestionPack


def revise_transcription_content(db, question_id, expected_snapshot_sha256, changes, *, basis, apply=False):
    """Explicit correction, NOT approval. Caller owns backup and transaction.

    Only stem/answer/explanation may change; stale/repeated commands fail closed.
    Full prior content is retained, without regrading attempts or changing nodes.
    """
    from uuid import UUID
    from backend.models.learning import KnowledgePoint
    from backend.services.golden_learning_slice import digest
    from backend.services.question_pack import QuestionContent
    from backend.services.question_verification_upgrade import snapshot

    if set(changes) != {"stem", "correct_answer", "explanation"}:
        raise ValueError("Exactly stem, correct_answer and explanation required")
    if not isinstance(basis, str) or not 10 <= len(basis.strip()) <= 2000:
        raise ValueError("Explicit bounded correction basis required")
    qid = UUID(str(question_id))
    node_id = db.scalar(select(Question.kp_id).where(Question.id == qid))
    node = db.scalar(select(KnowledgePoint).where(KnowledgePoint.id == node_id).with_for_update()
                     .execution_options(populate_existing=True))
    if node is None or not node.is_active or not node.is_assessable:
        raise ValueError("Missing/inactive/non-assessable knowledge node")
    row = db.scalar(select(Question).where(Question.id == qid).with_for_update()
                    .execution_options(populate_existing=True))
    if row is None or row.kp_id != node_id or not row.is_active:
        raise ValueError("Missing/inactive question or concurrent mapping change")
    before = snapshot(row)
    if digest(before) != expected_snapshot_sha256:
        raise ValueError("Question snapshot changed; inspect before any new correction")
    config = deepcopy(row.grading_config or {})
    provenance = config.get("provenance", {})
    if (config.get("verified") is not False or config.get("method") is not None
            or row.grading_mode != "self_assessed"
            or provenance.get("content_status") != "source_transcribed"
            or provenance.get("source", {}).get("source_type") not in {"exam", "mock"}):
        raise ValueError("Only unverified self-assessed exam/mock transcriptions may be corrected")
    fields = ("question_type", "stem", "options", "correct_answer", "explanation", "question_role",
              "difficulty", "skill_tags", "estimated_minutes", "is_variant")
    validated = QuestionContent.model_validate({
        "source_id": "maintenance-correction", "kp_code": node.code,
        **{field: deepcopy(getattr(row, field)) for field in fields}, **changes,
    })
    normalized = {field: getattr(validated, field) for field in changes}
    changed = any(getattr(row, field) != value for field, value in normalized.items())
    if apply and changed:
        config.setdefault("content_revisions", []).append({
            "before": before, "before_snapshot_sha256": expected_snapshot_sha256,
            "changes": deepcopy(normalized), "basis": basis.strip(),
            "review_status": "AI_REVIEWED_PENDING_HUMAN",
            "at": datetime.now(timezone.utc).isoformat(),
        })
        for field, value in normalized.items():
            setattr(row, field, value)
        row.grading_config = config
        db.flush()
    return {"mode": "apply" if apply else "dry_run", "corrected": int(changed),
            "question_id": str(qid), "verified_upgrades": 0, "history_regraded": False,
            "before_snapshot_sha256": expected_snapshot_sha256}


def revise_answers(db, pack: QuestionPack, revisions: dict, *, apply=False):
    db.flush()  # Preserve caller edits before refreshing locked maintenance rows.
    originals = {q.source_id: q for q in pack.questions}
    if any(key not in originals or set(value) != {"answer", "explanation"}
           for key, value in revisions.items()):
        raise ValueError("unknown source or unexpected revision fields")
    nodes = {}
    for code in sorted({originals[key].kp_code for key in revisions}):
        node = db.scalar(select(KnowledgePoint).where(KnowledgePoint.code == code).with_for_update()
                         .execution_options(populate_existing=True))
        if node is None or not node.is_active or not node.is_assessable:
            raise ValueError("inactive, parent or missing node")
        nodes[code] = node
    pending = []
    for source_id, revision in revisions.items():
        if source_id not in originals or set(revision) != {"answer", "explanation"}:
            raise ValueError("unknown source or unexpected revision fields")
        original = originals[source_id]
        replacement = original.model_copy(update={"correct_answer": revision["answer"],
                                                  "explanation": revision["explanation"]})
        type(original).model_validate(replacement.model_dump())
        key = f"{pack.pack_id}:{source_id}"
        row = db.scalar(select(Question).where(
            Question.grading_config["provenance"]["key"].as_string() == key
        ).with_for_update().execution_options(populate_existing=True))
        if row is None or not row.is_active or row.kp_id != nodes[original.kp_code].id:
            raise ValueError(f"missing active question: {key}")
        config = deepcopy(row.grading_config or {})
        if config.get("verified") or config.get("provenance", {}).get("content_status") != "source_transcribed":
            raise ValueError("only unverified source transcriptions may be enriched")
        if config.get("method") is not None or config["provenance"].get("source") != original.source.model_dump(mode="json"):
            raise ValueError("grading or source changed since source pack")
        if any(getattr(row, field) != getattr(original, field) for field in ("stem", "options", "question_type")):
            raise ValueError("question content changed since source pack")
        if row.correct_answer == revision["answer"] and row.explanation == revision["explanation"]:
            continue
        if row.correct_answer != original.correct_answer or row.explanation != original.explanation:
            raise ValueError("answer changed since source pack; manual review required")
        config.setdefault("answer_revisions", []).append({
            "previous_answer": row.correct_answer, "previous_explanation": row.explanation,
            "answer": revision["answer"], "explanation": revision["explanation"],
            "basis": "AI independently derived; unverified", "at": datetime.now(timezone.utc).isoformat(),
        })
        pending.append((row, config, revision))
    if apply:
        for row, config, revision in pending:
            row.correct_answer = revision["answer"]
            row.explanation = revision["explanation"]
            row.grading_config = config
        db.flush()
    return {"mode": "apply" if apply else "dry_run", "enriched": len(pending),
            "verified_upgrades": 0, "history_preserved": True}
