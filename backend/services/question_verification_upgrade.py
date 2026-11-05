"""Explicit hash-bound upgrade after human review, never retrospective grading.

Review declarations are not authentication. This is an offline maintainer
workflow; it is deliberately not exposed as a public HTTP endpoint.
"""
from copy import deepcopy
from datetime import datetime, timezone
from uuid import UUID
from uuid import UUID

from sqlalchemy import select

from backend.models.learning import KnowledgePoint, Question
from backend.services.golden_learning_slice import ASPECTS, Review, digest
from backend.services.question_pack import QuestionPack, fingerprint, _answer_provenance, _answer_reliability, _answer_source_metadata, _review_timestamp
from backend.services.answer_verification import answer_version_sha256, current_answer_verification, verify_answer


def snapshot(row):
    fields = ("question_type", "stem", "options", "correct_answer", "explanation",
              "question_role", "difficulty", "skill_tags", "estimated_minutes", "is_variant",
              "is_active", "grading_mode", "grading_config", "answer_provenance",
              "answer_reliability", "answer_reviewed_by", "answer_reviewed_at",
              "content_trust", "source_status", "content_reviewed_by", "content_reviewed_at",
              "question_provenance", "answer_verification_event_id",
              "source_attestation_key", "source_attestation_sha256",
              "answer_attestation_key", "answer_attestation_sha256")
    value = {field: deepcopy(getattr(row, field)) for field in fields}
    for field, item in value.items():
        if isinstance(item, datetime):
            value[field] = item.astimezone(timezone.utc).isoformat()
        elif isinstance(item, UUID):
            value[field] = str(item)
    return {"question_id": str(row.id), "kp_id": str(row.kp_id), **value}


def source_identity(source):
    subject = {"数学二": "math2", "math2": "math2", "408": "408"}.get(source.get("subject"))
    return (subject, source.get("source_type"), source.get("year"), source.get("question_number"))


def validate_reviews(question, reviews):
    if not isinstance(reviews, dict) or set(reviews) != ASPECTS:
        raise ValueError("All six exact-content human review aspects required")
    sha = fingerprint(question)
    validated = {name: Review.model_validate(value) for name, value in reviews.items()}
    if any(r.status != "VERIFIED" or r.content_sha256 != sha for r in validated.values()):
        raise ValueError("Six reviews must bind the approved question")
    if (validated["answer"].reviewed_by != question.answer_reviewed_by
            or validated["answer"].reviewed_on != question.answer_reviewed_on
            or validated["answer"].note != question.answer_review_note
            or validated["source"].reviewed_by != question.source.reviewed_by
            or validated["source"].reviewed_on != question.source.reviewed_on):
        raise ValueError("Source/answer declarations differ from human attestations")


def build_targets(db, pack):
    """Read-only maintainer template; concurrent edits invalidate its hashes."""
    result = {}
    for q in pack.questions:
        node = db.scalar(select(KnowledgePoint).where(KnowledgePoint.code == q.kp_code))
        if node is None or not node.is_active or not node.is_assessable:
            raise ValueError("Target knowledge node missing/inactive/not assessable")
        matches = [row for row in db.scalars(select(Question).where(Question.kp_id == node.id, Question.is_active.is_(True)))
            if source_identity((row.grading_config or {}).get("provenance", {}).get("source", {}))
                == source_identity(q.source.model_dump(mode="json"))]
        if len(matches) != 1:
            raise ValueError("Exactly one matching active transcription required; do not guess duplicate source versions")
        config = matches[0].grading_config or {}
        if (config.get("verified") is not False or config.get("method") is not None
                or config.get("provenance", {}).get("content_status") != "source_transcribed"):
            raise ValueError("Already reviewed or unsupported target; reuse original snapshot only for a valid replay")
        result[q.source_id] = {"question_id": str(matches[0].id), "snapshot_sha256": digest(snapshot(matches[0]))}
    return result


def upgrade_transcriptions(db, pack: QuestionPack, targets: dict, reviews: dict, *, apply=False):
    """Validate entire batch first; caller owns commit/rollback and backup.

    targets[source_id] = {question_id, snapshot_sha256}. Preserve row identity,
    attempts, plans, events and node policy. No regrading or mastery projection.
    """
    # Session factories disable autoflush; don't erase caller edits when the
    # locked DB objects are refreshed. Caller still owns commit/rollback.
    db.flush()
    ids = {q.source_id for q in pack.questions}
    if set(targets) != ids or set(reviews) != ids:
        raise ValueError("Targets and reviews must exactly match approved pack")
    parsed = {}
    for q in pack.questions:
        if q.content_status != "reviewed" or q.source.source_type != "exam":
            raise ValueError("Upgrade requires reviewed exam content")
        validate_reviews(q, reviews[q.source_id])
        target = targets[q.source_id]
        if set(target) != {"question_id", "snapshot_sha256"}:
            raise ValueError("Exact target ID and snapshot hash required")
        parsed[q.source_id] = UUID(target["question_id"])
    if len(set(parsed.values())) != len(parsed):
        raise ValueError("Multiple reviewed items cannot target one old question")
    identities = [source_identity(q.source.model_dump(mode="json")) for q in pack.questions]
    if any(i[0] is None for i in identities) or len(set(identities)) != len(identities):
        raise ValueError("Unknown subject or duplicate exam identity")
    # Same node-first order as importer; never lock old questions before nodes.
    nodes = {}
    for code in sorted({q.kp_code for q in pack.questions}):
        node = db.scalar(select(KnowledgePoint).where(KnowledgePoint.code == code).with_for_update()
                         .execution_options(populate_existing=True))
        if node is None or not node.is_active or not node.is_assessable:
            raise ValueError("Inactive, parent or missing target node")
        nodes[code] = node
    locked = {r.id: r for r in db.scalars(select(Question).where(Question.id.in_(parsed.values()))
        .order_by(Question.id).with_for_update().execution_options(populate_existing=True))}
    pending, unchanged, results = [], [], []
    for q in sorted(pack.questions, key=lambda q: q.source_id):
        row = locked.get(parsed[q.source_id])
        if row is None or not row.is_active or row.kp_id != nodes[q.kp_code].id:
            raise ValueError("Missing/inactive question or knowledge mapping changed")
        config = deepcopy(row.grading_config or {})
        provenance = config.get("provenance", {})
        after_sha = fingerprint(q)
        # Replay succeeds only if the exact previously applied transition still
        # matches every content/config field, not just a saved audit hash.
        prior = config.get("verification_revisions", [])
        fields = ("question_type", "stem", "options", "correct_answer", "explanation", "question_role",
                  "difficulty", "skill_tags", "estimated_minutes", "is_variant")
        expected_mode = "auto" if q.grading_method else "self_assessed"
        already = (prior and prior[-1].get("before_snapshot_sha256") == targets[q.source_id]["snapshot_sha256"]
            and prior[-1].get("after_content_sha256") == after_sha
            and all(getattr(row, field) == getattr(q, field) for field in fields)
            and config.get("verified") is bool(q.grading_method) and config.get("method") == q.grading_method
            and row.grading_mode == expected_mode and provenance.get("sha256") == after_sha
            and provenance.get("content_status") == "reviewed"
            and provenance.get("source") == q.source.model_dump(mode="json")
            and provenance.get("answer_reviewed_by") == q.answer_reviewed_by
            and provenance.get("answer_review_method") == q.answer_review_method
            and provenance.get("answer_review_note") == q.answer_review_note
            and provenance.get("answer_reference") == (q.answer_reference.model_dump(mode="json") if q.answer_reference else None)
            and prior[-1].get("reviews") == reviews[q.source_id]
            and prior[-1].get("approved_pack_id") == pack.pack_id
            and config.get("version") == pack.version
            and digest(prior[-1].get("before", {})) == targets[q.source_id]["snapshot_sha256"]
            and provenance.get("key") == prior[-1].get("before", {}).get("grading_config", {}).get("provenance", {}).get("key")
            and current_answer_verification(row) is not None
            and current_answer_verification(row).verification_type == _answer_provenance(q)
            and current_answer_verification(row).verification_method == q.answer_review_method
            and current_answer_verification(row).note == q.answer_review_note
            and current_answer_verification(row).source_metadata == _answer_source_metadata(q)
            and row.answer_provenance == _answer_provenance(q)
            and row.answer_reliability == _answer_reliability(q)
            and row.answer_reviewed_by == q.answer_reviewed_by
            and (row.answer_reviewed_at.date() if row.answer_reviewed_at else None) == q.answer_reviewed_on
            and row.content_trust == "verified" and row.source_status == "verified"
            and row.content_reviewed_by == q.content_reviewed_by
            and (row.content_reviewed_at.date() if row.content_reviewed_at else None) == q.content_reviewed_on)
        if already:
            unchanged.append(q.source_id)
            continue
        before = snapshot(row)
        if digest(before) != targets[q.source_id]["snapshot_sha256"]:
            raise ValueError("Question changed after upgrade snapshot")
        if (config.get("verified") is not False or config.get("method") is not None
                or row.grading_mode != "self_assessed" or provenance.get("content_status") != "source_transcribed"):
            raise ValueError("Only unverified transcriptions can be upgraded")
        old_identity = source_identity(provenance.get("source", {}))
        if old_identity[0] is None or old_identity != source_identity(q.source.model_dump(mode="json")):
            raise ValueError("Reviewed content has different exam identity")
        # Upgrading a source is not a disguised stem/options/node replacement.
        if any(getattr(row, f) != getattr(q, f) for f in ("stem", "options", "question_type")):
            raise ValueError("Stem/options/type correction needs a separate versioned content workflow")
        key = provenance.get("key")
        if not isinstance(key, str) or ":" not in key:
            raise ValueError("Old imported source key missing")
        config.update(verified=bool(q.grading_method), method=q.grading_method, version=pack.version)
        config["provenance"] = {**provenance, "sha256": after_sha, "content_status": "reviewed",
            "source": q.source.model_dump(mode="json"), "answer_reviewed_by": q.answer_reviewed_by,
            "answer_review_method": q.answer_review_method, "answer_review_note": q.answer_review_note,
            "answer_reference": q.answer_reference.model_dump(mode="json") if q.answer_reference else None}
        config.setdefault("verification_revisions", []).append({"before_snapshot_sha256": digest(before),
            "before": before, "after_content_sha256": after_sha, "reviews": deepcopy(reviews[q.source_id]),
            "approved_pack_id": pack.pack_id, "at": datetime.now(timezone.utc).isoformat()})
        pending.append((row, q, config))
        results.append({"source_id": q.source_id, "question_id": str(row.id),
            "before_snapshot_sha256": digest(before), "after_content_sha256": after_sha})
    if apply:
        for row, q, config in pending:
            content_fields = ("question_type", "stem", "options", "correct_answer", "explanation",
                "question_role", "difficulty", "skill_tags", "estimated_minutes", "is_variant")
            for field in content_fields:
                setattr(row, field, deepcopy(getattr(q, field)))
            row.grading_config, row.grading_mode = config, "auto" if q.grading_method else "self_assessed"
            row.content_trust = "verified"
            row.source_status = "verified"
            row.content_reviewed_by = q.content_reviewed_by
            row.content_reviewed_at = _review_timestamp(q.content_reviewed_on)
            verify_answer(db, question_id=row.id, verification_type=_answer_provenance(q),
                verifier=q.answer_reviewed_by or "", method=q.answer_review_method or "",
                note=q.answer_review_note or "", source_metadata=_answer_source_metadata(q),
                expected_answer_sha256=answer_version_sha256(row),
                idempotency_key="upgrade:" + digest({"pack": pack.pack_id, "version": pack.version,
                    "source_id": q.source_id, "answer_sha256": answer_version_sha256(row)}),
                now=_review_timestamp(q.answer_reviewed_on))
        db.flush()
    return {"mode": "apply" if apply else "dry_run", "upgraded": len(pending), "unchanged": len(unchanged),
        "changes": results, "history_regraded": False, "node_policy_changed": False,
        "requires_online_policy_review": sorted(n.code for n in nodes.values() if n.is_reference_only)}
