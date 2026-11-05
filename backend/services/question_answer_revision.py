"""Audited answer enrichment for unverified source transcriptions only."""
from copy import deepcopy
from datetime import datetime, timezone
from sqlalchemy import select
from backend.models.learning import KnowledgePoint, Question
from backend.services.question_pack import QuestionPack, _source_dump


def revise_transcription_content(db, question_id, expected_snapshot_sha256, changes, *, basis,
                                 proposed_source_pack_sha256, proposed_pack_version, apply=False,
                                 allow_unverified_grader=False):
    """Explicit correction, NOT approval. Caller owns backup and transaction.

    Only stem/options/answer/explanation may change; stale/repeated commands fail closed.
    Source-bound edits invalidate the current source attestation and require review.
    Full prior content is retained, without regrading attempts or changing nodes.
    """
    from uuid import UUID
    from backend.models.learning import KnowledgePoint
    from backend.services.golden_learning_slice import digest
    from backend.services.question_pack import QuestionContent
    from backend.services.question_verification_upgrade import snapshot
    allowed_fields = {"stem", "options", "correct_answer", "explanation"}
    if not changes or not set(changes) <= allowed_fields:
        raise ValueError("Only nonempty stem/options/correct_answer/explanation corrections are allowed")
    if not isinstance(basis, str) or not 10 <= len(basis.strip()) <= 2000:
        raise ValueError("Explicit bounded correction basis required")
    import re
    if not isinstance(proposed_source_pack_sha256, str) or not re.fullmatch(r"[a-f0-9]{64}", proposed_source_pack_sha256):
        raise ValueError("A new content-bound source-pack fingerprint is required")
    if not isinstance(proposed_pack_version, str) or not 1 <= len(proposed_pack_version) <= 40:
        raise ValueError("A new correction pack version is required")
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
    if row.bank_scope!='public' or row.generation_batch_id:
        raise ValueError('Personal questions cannot enter public transcription correction')
    before = snapshot(row)
    if digest(before) != expected_snapshot_sha256:
        raise ValueError("Question snapshot changed; inspect before any new correction")
    config = deepcopy(row.grading_config or {})
    provenance = config.get("provenance", {})
    method = config.get("method")
    allowed_unverified_method = False
    if allow_unverified_grader and config.get("verified") is False and isinstance(method, str):
        from backend.services.answer_grading import available_grading_method
        allowed_unverified_method = available_grading_method(
            question_type=row.question_type,
            config={"verified": True, "method": method},
            expected=row.correct_answer,
            options=row.options,
        )
    if (config.get("verified") is not False
            or (method is not None and not allowed_unverified_method)
            or row.grading_mode != "self_assessed"
            or provenance.get("content_status") != "source_transcribed"
            or provenance.get("source", {}).get("source_type") not in {"exam", "mock"}):
        raise ValueError("Only unverified self-assessed exam/mock transcriptions may be corrected")
    if row.answer_verification_event_id is not None:
        raise ValueError("A question with an answer-verification pointer requires the dedicated revision/revocation workflow")
    old_source_pack_sha256 = provenance.get("sha256")
    old_pack_version = config.get("version")
    if not isinstance(old_source_pack_sha256, str) or not re.fullmatch(r"[a-f0-9]{64}", old_source_pack_sha256):
        raise ValueError("Existing source-pack fingerprint missing; manual review required")
    fields = ("question_type", "stem", "options", "correct_answer", "explanation", "question_role",
              "difficulty", "skill_tags", "estimated_minutes", "is_variant")
    validated = QuestionContent.model_validate({
        "source_id": "maintenance-correction", "kp_code": node.code,
        **{field: deepcopy(getattr(row, field)) for field in fields}, **changes,
    })
    normalized = {field: getattr(validated, field) for field in changes}
    changed = any(getattr(row, field) != value for field, value in normalized.items())
    if changed and proposed_source_pack_sha256 == old_source_pack_sha256:
        raise ValueError("Changed content requires a fresh source-pack fingerprint")
    source_content_changed = changed and bool({"stem", "options"} & set(normalized))
    answer_content_changed = changed and bool(source_content_changed or "correct_answer" in normalized)
    preview = deepcopy(row)
    for field, value in normalized.items():
        setattr(preview, field, deepcopy(value))
    source_attestation_invalidated = source_content_changed and bool(
        row.source_attestation_key or row.source_attestation_sha256
    )
    answer_attestation_invalidated = answer_content_changed and bool(
        row.answer_attestation_key or row.answer_attestation_sha256
    )
    if source_content_changed:
        preview.content_trust = "needs_review"
        preview.source_status = "needs_review"
        preview.source_attestation_key = None
        preview.source_attestation_sha256 = None
    if answer_content_changed:
        preview.answer_attestation_key = None
        preview.answer_attestation_sha256 = None
        if preview.answer_provenance == "ai_generated":
            preview.answer_reliability = "unverified"
    from backend.services.answer_verification import answer_version_sha256
    from backend.services.question_attestation import question_content_sha256, has_current_source_attestation
    from backend.services.answer_consistency import has_current_answer_attestation
    # Capture report-only "before" facts before the apply branch mutates `row`.
    # The row remains the same ORM instance, so reading these fields at return
    # time would incorrectly report the downgraded post-correction state.
    before_answer_attestation_current = has_current_answer_attestation(row)
    before_answer_reliability = row.answer_reliability
    proposed_config = deepcopy(config)
    proposed_provenance = deepcopy(provenance)
    proposed_provenance["sha256"] = proposed_source_pack_sha256
    proposed_config["provenance"] = proposed_provenance
    proposed_config["version"] = proposed_pack_version
    preview.grading_config = proposed_config
    before_content_sha256 = question_content_sha256(row)
    after_content_sha256 = question_content_sha256(preview)
    before_answer_sha256 = answer_version_sha256(row)
    after_answer_sha256 = answer_version_sha256(preview)
    if apply and changed:
        config.setdefault("content_revisions", []).append({
            "before": before, "before_snapshot_sha256": expected_snapshot_sha256,
            "changes": deepcopy(normalized), "basis": basis.strip(),
            "source_attestation_invalidated": bool(source_attestation_invalidated),
            "answer_attestation_invalidated": bool(answer_attestation_invalidated),
            "before_question_content_sha256": before_content_sha256,
            "after_question_content_sha256": after_content_sha256,
            "before_answer_version_sha256": before_answer_sha256,
            "after_answer_version_sha256": after_answer_sha256,
            "before_source_pack_sha256": old_source_pack_sha256,
            "after_source_pack_sha256": proposed_source_pack_sha256,
            "before_pack_version": old_pack_version,
            "after_pack_version": proposed_pack_version,
            "review_status": "PENDING_HUMAN_VERIFICATION",
            "at": datetime.now(timezone.utc).isoformat(),
        })
        for field, value in normalized.items():
            setattr(row, field, value)
        if source_content_changed:
            # Preserve the old attestation in its append-only audit row and in
            # the before snapshot, but do not let a changed stem/options inherit it.
            row.content_trust = "needs_review"
            row.source_status = "needs_review"
            row.source_attestation_key = None
            row.source_attestation_sha256 = None
            # Old A/B/C consistency is bound to the previous options. Keep its
            # append-only run rows, but clear the current pointer and downgrade
            # derived AI consistency so stale results cannot describe new text.
        if answer_content_changed:
            # Answer consistency is bound to the current answer as well as the
            # stem/options. An answer-only correction therefore keeps the
            # source attestation but must not retain a current answer stamp.
            row.answer_attestation_key = None
            row.answer_attestation_sha256 = None
            if row.answer_provenance == "ai_generated":
                row.answer_reliability = "unverified"
        config["provenance"] = proposed_provenance
        config["version"] = proposed_pack_version
        row.grading_config = config
        db.flush()
    return {"mode": "apply" if apply else "dry_run", "corrected": int(changed),
            "question_id": str(qid), "verified_upgrades": 0, "history_regraded": False,
            "before_snapshot_sha256": expected_snapshot_sha256,
            "source_content_changed": bool(source_content_changed),
            "source_attestation_invalidated": bool(source_attestation_invalidated),
            "answer_attestation_invalidated": bool(answer_attestation_invalidated),
            "before_question_content_sha256": before_content_sha256,
            "proposed_question_content_sha256": question_content_sha256(preview),
            "before_answer_version_sha256": before_answer_sha256,
            "proposed_answer_version_sha256": answer_version_sha256(preview),
            "before_source_pack_sha256": old_source_pack_sha256,
            "proposed_source_pack_sha256": proposed_source_pack_sha256,
            "before_pack_version": old_pack_version,
            "proposed_pack_version": proposed_pack_version,
            "proposed_source_attestation_current": has_current_source_attestation(preview),
            "before_answer_attestation_current": before_answer_attestation_current,
            "proposed_answer_attestation_current": has_current_answer_attestation(preview),
            "before_answer_reliability": before_answer_reliability,
            "proposed_answer_reliability": preview.answer_reliability}


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
        if row.bank_scope!='public' or row.generation_batch_id:
            raise ValueError('Personal questions cannot enter public answer enrichment')
        config = deepcopy(row.grading_config or {})
        if config.get("verified") or config.get("provenance", {}).get("content_status") != "source_transcribed":
            raise ValueError("only unverified source transcriptions may be enriched")
        if config.get("method") is not None or config["provenance"].get("source") != _source_dump(original.source):
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


def revise_qualified_public_stem(db, question_id, expected_snapshot_sha256,
        expected_auto_review_event_id, changes, *, basis, source_pack_key,
        source_pack_sha256, source_pack_version, revision_key, apply=False):
    """Withdraw a current auto-review before a source-bound public stem fix.

    This is intentionally narrower than a general editor: only a qualified
    public exam transcription with no learner Attempts can be revised, and
    only its stem may change. The old auto-review is revoked append-only; the
    caller must independently review and requalify the corrected snapshot.
    """
    import re
    from copy import deepcopy
    from datetime import datetime, timezone
    from uuid import UUID
    from sqlalchemy import select, func, text
    from backend.models.learning import KnowledgePoint, Question, QuestionAttempt
    from backend.services.auto_question_review import (
        current_auto_review, question_snapshot_sha256, revoke_auto_qualification,
    )
    from backend.services.golden_learning_slice import digest
    from backend.services.question_pack import QuestionContent

    if (not isinstance(changes, dict) or "stem" not in changes
            or not set(changes) <= {"stem", "explanation"}
            or any(not isinstance(value, str) for value in changes.values())):
        raise ValueError("qualified_public_revision_only_allows_stem_and_explanation")
    if not isinstance(basis, str) or len(basis.strip()) < 20:
        raise ValueError("qualified_public_revision_basis_required")
    if (not isinstance(source_pack_key, str) or ":" not in source_pack_key
            or not re.fullmatch(r"[a-f0-9]{64}", source_pack_sha256)
            or not isinstance(source_pack_version, str) or not source_pack_version.strip()
            or not isinstance(revision_key, str) or len(revision_key.strip()) < 12):
        raise ValueError("qualified_public_revision_lineage_required")

    qid = UUID(str(question_id))
    from backend.services.question_identity import PUBLIC_BANK_LOCK
    db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": PUBLIC_BANK_LOCK})
    row = db.scalar(select(Question).where(Question.id == qid).with_for_update()
                    .execution_options(populate_existing=True))
    if row is None:
        raise ValueError("question_not_found")
    node = db.scalar(select(KnowledgePoint).where(KnowledgePoint.id == row.kp_id).with_for_update())
    if (row.bank_scope != "public" or row.generation_batch_id is not None
            or row.question_provenance != "real_exam" or not row.is_active
            or node is None or not node.is_active or not node.is_assessable or node.children):
        raise ValueError("qualified_public_exam_question_required")
    config = deepcopy(row.grading_config or {})
    revisions = list(config.get("content_revisions", [])) if isinstance(config.get("content_revisions"), list) else []
    if any(item.get("revision_key") == revision_key for item in revisions if isinstance(item, dict)):
        existing_provenance = config.get("provenance") if isinstance(config.get("provenance"), dict) else {}
        if all(getattr(row, field) == value for field, value in changes.items()) and existing_provenance.get("key") == source_pack_key:
            return {"status": "NOOP", "question_id": str(qid),
                    "snapshot_sha256": question_snapshot_sha256(row),
                    "current_auto_review": bool(current_auto_review(row, node))}
        raise ValueError("qualified_public_revision_key_conflict")
    current = current_auto_review(row, node)
    if (current is None or str(current.id) != str(expected_auto_review_event_id)
            or current.qualification_class != "exam_curated"):
        raise ValueError("expected_current_exam_auto_review_mismatch")
    from backend.services.auto_question_review import question_snapshot_payload
    before_snapshot = question_snapshot_payload(row)
    if question_snapshot_sha256(row) != expected_snapshot_sha256:
        raise ValueError("question_snapshot_changed")
    if row.answer_verification_event_id is not None:
        raise ValueError("human_answer_verification_requires_dedicated_revision_flow")
    attempts = db.scalar(select(func.count()).select_from(QuestionAttempt)
                         .where(QuestionAttempt.question_id == qid)) or 0
    if attempts:
        raise ValueError("stem_revision_refused_after_learner_attempts")
    provenance = config.get("provenance") if isinstance(config.get("provenance"), dict) else {}
    old_key, old_pack_sha = provenance.get("key"), provenance.get("sha256")
    if source_pack_key == old_key and source_pack_sha256 == old_pack_sha:
        raise ValueError("corrected_source_pack_must_have_new_identity_and_fingerprint")
    validated = QuestionContent.model_validate({
        "source_id": "protected-source-correction", "kp_code": node.code,
        "question_type": row.question_type, "stem": changes["stem"], "options": deepcopy(row.options),
        "correct_answer": row.correct_answer, "explanation": changes.get("explanation", row.explanation),
        "question_role": row.question_role, "difficulty": row.difficulty,
        "skill_tags": deepcopy(row.skill_tags), "estimated_minutes": row.estimated_minutes,
        "is_variant": row.is_variant, "grading_method": None,
    })
    proposed_stem = validated.stem
    normalized_changes = {"stem": proposed_stem}
    if "explanation" in changes:
        normalized_changes["explanation"] = validated.explanation
    if all(getattr(row, field) == value for field, value in normalized_changes.items()):
        raise ValueError("qualified_public_revision_is_noop")
    from backend.services.question_attestation import question_content_sha256
    from backend.services.answer_verification import answer_version_sha256
    before = {"snapshot": before_snapshot, "snapshot_sha256": expected_snapshot_sha256,
        "content_sha256": question_content_sha256(row), "answer_sha256": answer_version_sha256(row),
        "auto_review_event_id": str(current.id), "source_pack_key": old_key,
        "source_pack_sha256": old_pack_sha, "source_pack_version": config.get("version")}
    proposed_snapshot = deepcopy(before_snapshot)
    proposed_snapshot.update(normalized_changes)
    result = {"status": "DRY_RUN" if not apply else "APPLIED_NEEDS_REVIEW",
        "question_id": str(qid), "node_code": node.code, "revision_key": revision_key,
        "before": before, "proposed_stem": proposed_stem, "proposed_changes": normalized_changes,
        "proposed_snapshot_sha256": digest(proposed_snapshot),
        "old_source_pack_sha256": old_pack_sha, "new_source_pack_sha256": source_pack_sha256,
        "learner_attempts": attempts, "qualification_revoked": bool(apply),
        "requalification_performed": False, "human_verified": False}
    if not apply:
        return result

    revoked = revoke_auto_qualification(db, question_id=qid, expected_event_id=current.id,
        expected_snapshot_sha256=expected_snapshot_sha256,
        idempotency_key=f"public-stem-revision:{revision_key}:revoke:{current.id}")
    for field, value in normalized_changes.items():
        setattr(row, field, value)
    config = deepcopy(row.grading_config or {})
    provenance = deepcopy(config.get("provenance", {}))
    provenance["key"] = source_pack_key
    provenance["sha256"] = source_pack_sha256
    config["provenance"] = provenance
    config["version"] = source_pack_version
    config.setdefault("content_revisions", []).append({
        "version": "phase45z5-qualified-source-stem-v1", "revision_key": revision_key,
        "before": before, "changes": normalized_changes, "basis": basis.strip(),
        "source_pack_key": source_pack_key, "source_pack_sha256": source_pack_sha256,
        "source_pack_version": source_pack_version, "revoked_auto_review_event_id": str(revoked.id),
        "source_attestation_invalidated": True, "answer_attestation_invalidated": True,
        "human_verified": False, "at": datetime.now(timezone.utc).isoformat(),
    })
    row.grading_config = config
    row.content_trust = "needs_review"
    row.source_status = "needs_review"
    row.source_attestation_key = None
    row.source_attestation_sha256 = None
    row.answer_attestation_key = None
    row.answer_attestation_sha256 = None
    row.answer_reliability = "unverified"
    db.flush()
    from backend.services.question_attestation import question_content_sha256
    from backend.services.answer_verification import answer_version_sha256
    result.update(revoked_event_id=str(revoked.id), after_snapshot_sha256=question_snapshot_sha256(row),
        after_content_sha256=question_content_sha256(row), after_answer_sha256=answer_version_sha256(row),
        current_auto_review=False)
    return result
