"""Reviewed question-pack import; no scraping, replacement or graduation writes."""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, time, timezone
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select, func

from backend.models.learning import KnowledgePoint, Question
from uuid import uuid4
from backend.services.answer_grading import available_grading_method
from backend.services.answer_verification import AnswerReferenceMetadata, answer_version_sha256, current_answer_verification, verify_answer


class SourceReview(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    kind: Literal["original", "licensed", "user_provided"]
    citation: str = Field(min_length=3, max_length=1000)
    rights_basis: str = Field(min_length=3, max_length=1000)
    reviewed_by: str = Field(min_length=1, max_length=100)
    reviewed_on: date
    year: int | None = Field(default=None, ge=2000, le=2100)
    question_number: int | None = Field(default=None, ge=1, le=200)
    source_type: Literal["exam", "mock", "original", "unknown"] = "unknown"
    content_origin: Literal["AI_GENERATED", "USER_PROVIDED", "LEGACY"] | None = None
    paper_title: str | None = Field(default=None, min_length=1, max_length=300)
    subject: str | None = Field(default=None, min_length=1, max_length=100)
    edition: str | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def require_exam_identity(self):
        if self.content_origin == "AI_GENERATED" and self.source_type in ("exam", "mock"):
            raise ValueError("AI-generated content cannot claim exam/mock authenticity")
        if self.source_type in ("exam", "mock"):
            if self.kind == "original":
                raise ValueError("original generated content cannot be declared an exam/mock source")
            if not all((self.year, self.question_number, self.paper_title, self.subject)):
                raise ValueError("exam/mock sources require year, question_number, paper_title and subject")
        return self


class QuestionContent(BaseModel):
    """Shared content/applicability checks, NOT a certificate of correctness."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    source_id: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,100}$")
    kp_code: str = Field(min_length=1, max_length=120)
    question_type: Literal["single_choice", "fill_blank", "calculation", "proof", "subjective"]
    stem: str = Field(min_length=5, max_length=30000)
    options: dict[str, str] | None = None
    correct_answer: str = Field(min_length=1, max_length=10000)
    explanation: str = Field(min_length=5, max_length=30000)
    question_role: Literal["basic", "typical", "variant", "comprehensive"] = "basic"
    difficulty: Literal["basic", "medium", "advanced"] = "basic"
    estimated_minutes: int = Field(ge=1, le=180)
    skill_tags: list[str] = Field(min_length=1, max_length=20)
    is_variant: bool = False
    grading_method: Literal["single_choice", "numeric_final", "logarithm_final", "constant_final"] | None = None

    @model_validator(mode="after")
    def validate_answer(self):
        if any(not tag.strip() or len(tag) > 100 for tag in self.skill_tags):
            raise ValueError("skill_tags must be nonempty and at most 100 characters")
        if self.question_type == "single_choice":
            if not self.options or len(self.options) < 2 or self.correct_answer not in self.options:
                raise ValueError("choice answer must name an existing option")
            if any(not key.strip() or not value.strip() for key, value in self.options.items()):
                raise ValueError("choice options must not be empty")
        elif self.options is not None:
            raise ValueError("non-choice questions must not contain options")
        if self.grading_method and not available_grading_method(
            question_type=self.question_type,
            config={"verified": True, "method": self.grading_method},
            expected=self.correct_answer, options=self.options,
        ):
            raise ValueError("unsupported verified grading configuration")
        return self


class PackQuestion(QuestionContent):
    source: SourceReview
    content_status: Literal["reviewed", "source_transcribed"] = "reviewed"
    answer_reviewed_by: str | None = Field(default=None, min_length=1, max_length=100)
    content_reviewed_by: str | None = Field(default=None, min_length=1, max_length=100)
    answer_reviewed_on: date | None = None
    content_reviewed_on: date | None = None
    answer_provenance: Literal["verified_reference", "human_verified", "ai_generated", "legacy_transcription", "unknown"] | None = None
    answer_reliability: Literal["verified", "ai_generated_consistent", "model_generated", "unverified", "unknown"] | None = None
    answer_review_method: str | None = Field(default=None, min_length=3, max_length=120)
    answer_review_note: str | None = Field(default=None, min_length=5, max_length=2000)
    answer_reference: AnswerReferenceMetadata | None = None
    practice_grading_method: Literal["single_choice", "numeric_final", "logarithm_final", "constant_final"] | None = None

    @model_validator(mode="after")
    def separate_transcription_from_grading(self):
        if self.content_status == "reviewed" and not (self.content_reviewed_by and self.content_reviewed_on):
            raise ValueError("reviewed question content requires its own reviewer and review date")
        answer_provenance = self.answer_provenance or (
            "legacy_transcription" if self.content_status == "source_transcribed" else "unknown")
        if answer_provenance in {"verified_reference", "human_verified"}:
            if self.content_status != "reviewed" or not (self.answer_reviewed_by and self.answer_reviewed_on):
                raise ValueError("verified answer requires its own reviewer and review date")
            if not self.answer_review_method or not self.answer_review_note:
                raise ValueError("verified answer requires an explicit method and review note")
            if self.answer_reliability not in (None, "verified"):
                raise ValueError("verified answer must have verified reliability")
            if answer_provenance == "verified_reference" and self.answer_reference is None:
                raise ValueError("verified reference answer requires authoritative source metadata")
            if answer_provenance == "human_verified" and self.answer_reference is not None:
                raise ValueError("human-only verification cannot claim reference provenance")
        elif answer_provenance == "ai_generated":
            if (self.answer_reviewed_by is not None or self.answer_reviewed_on is not None
                    or self.answer_review_method is not None or self.answer_review_note is not None
                    or self.answer_reference is not None or self.grading_method is not None):
                raise ValueError("AI generated answers cannot claim human answer review or verified grading")
            if self.answer_reliability == "verified":
                raise ValueError("AI answer reliability cannot be declared authoritative")
            if self.practice_grading_method and not available_grading_method(
                question_type=self.question_type,
                config={"verified": True, "method": self.practice_grading_method},
                expected=self.correct_answer, options=self.options,
            ):
                raise ValueError("unsupported AI answer practice comparator")
        elif answer_provenance in {"legacy_transcription", "unknown"} and self.content_status == "reviewed":
            raise ValueError("reviewed content must declare a verified-reference or AI-generated answer")
        if self.content_status == "source_transcribed":
            if self.source.source_type not in ("exam", "mock") or self.source.kind == "original":
                raise ValueError("transcribed practice must come from an actual exam/mock source")
            if (self.grading_method is not None or self.answer_reviewed_by is not None
                    or self.answer_review_method is not None or self.answer_review_note is not None
                    or self.answer_reference is not None or self.practice_grading_method is not None):
                raise ValueError("unverified transcription cannot claim verified grading or answer review")
        return self


class QuestionPack(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    pack_id: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,100}$")
    version: str = Field(min_length=1, max_length=40)
    questions: list[PackQuestion] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def reject_duplicates(self):
        ids = [q.source_id for q in self.questions]
        stems = [(q.kp_code, q.stem) for q in self.questions]
        if len(ids) != len(set(ids)) or len(stems) != len(set(stems)):
            raise ValueError("duplicate source_id or node/stem in pack")
        return self


def fingerprint(question: PackQuestion) -> str:
    content = question.model_dump(mode="json")
    # Optional provenance attributes stay absent for older reviewed packs so
    # their stable content fingerprints remain compatible.
    for field in ("content_reviewed_by", "content_reviewed_on", "answer_reviewed_on", "answer_provenance", "answer_reliability", "answer_review_method", "answer_review_note", "answer_reference", "practice_grading_method"):
        if field not in question.model_fields_set:
            content.pop(field, None)
    for field in ("content_origin",):
        if field not in question.source.model_fields_set:
            content["source"].pop(field, None)
    if content.get("content_status") == "reviewed":
        content.pop("content_status", None)
    # Keep legacy reviewed packs idempotent when optional source fields are absent.
    source = content["source"]
    for key, default in (("source_type", "unknown"), ("paper_title", None), ("subject", None), ("edition", None)):
        if source.get(key) == default:
            source.pop(key, None)
    canonical = json.dumps(content, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def import_pack(db, pack: QuestionPack, *, apply: bool = False) -> dict:
    """Caller owns commit/rollback. Validate whole pack before adding any rows."""
    # Preserve the caller's pending edits before refreshing locked objects.
    # This flush is not a commit and does not add any pack questions in preview.
    db.flush()
    from backend.services.question_identity import PUBLIC_BANK_LOCK,duplicate_findings,digest as identity_digest
    db.execute(select(func.pg_advisory_xact_lock(PUBLIC_BANK_LOCK)))
    # Serialize cooperating importers for one pack, including node remapping.
    lock_id = int.from_bytes(hashlib.sha256(pack.pack_id.encode()).digest()[:8], "big", signed=True)
    db.execute(select(func.pg_advisory_xact_lock(lock_id)))
    pending: list[tuple[Question, PackQuestion, str]] = []
    skipped, policy_review = [], set()
    duplicate_links=[]
    for question in sorted(pack.questions, key=lambda q: (q.kp_code, q.source_id)):
        node = db.scalar(select(KnowledgePoint).where(KnowledgePoint.code == question.kp_code).with_for_update()
                         .execution_options(populate_existing=True))
        if node is None or not node.is_active or not node.is_assessable:
            raise ValueError(f"inactive, parent or missing node: {question.kp_code}")
        key = f"{pack.pack_id}:{question.source_id}"
        digest = fingerprint(question)
        rows = db.scalars(select(Question).where(Question.kp_id == node.id)).all()
        existing = db.scalars(select(Question).where(
            Question.grading_config["provenance"]["key"].as_string() == key).with_for_update()
            .execution_options(populate_existing=True)).all()
        if existing:
            # Saved fingerprints are not enough: mutable grading/source fields
            # can drift without recomputing the old hash. Never silently repair
            # them or declare a damaged import idempotently unchanged.
            saved_config = existing[0].grading_config or {}
            provenance = saved_config.get("provenance", {}) if isinstance(saved_config, dict) else {}
            expected_answer_provenance = _answer_provenance(question)
            current_verification = current_answer_verification(existing[0])
            verification_metadata_matches = (
                expected_answer_provenance not in {"human_verified", "verified_reference"}
                or current_verification is not None
                    and current_verification.verification_type == expected_answer_provenance
                    and current_verification.verification_method == question.answer_review_method
                    and current_verification.note == question.answer_review_note
                    and current_verification.source_metadata == _answer_source_metadata(question)
            )
            metadata_matches = (isinstance(saved_config, dict) and isinstance(provenance, dict)
                and saved_config.get("verified") is bool(question.grading_method)
                and saved_config.get("method") == question.grading_method
                and existing[0].grading_mode == ("auto" if question.grading_method else "self_assessed")
                and provenance.get("sha256") == digest
                and provenance.get("source") == _source_dump(question.source)
                and provenance.get("content_status", "reviewed") == question.content_status
                and provenance.get("answer_reviewed_by") == question.answer_reviewed_by
                and provenance.get("question_provenance", "legacy_unknown") == _question_provenance(question)
                and provenance.get("content_trust", "unreviewed") == _content_trust(question)
                and provenance.get("answer_provenance", _answer_provenance(question)) == _answer_provenance(question)
                and provenance.get("answer_reliability", _answer_reliability(question)) == _answer_reliability(question)
                and provenance.get("content_reviewed_on") == (question.content_reviewed_on.isoformat() if question.content_reviewed_on else None)
                and provenance.get("answer_reviewed_on") == (question.answer_reviewed_on.isoformat() if question.answer_reviewed_on else None)
                and provenance.get("answer_review_method") == question.answer_review_method
                and provenance.get("answer_review_note") == question.answer_review_note
                and provenance.get("answer_reference") == (question.answer_reference.model_dump(mode="json") if question.answer_reference else None)
                and existing[0].question_provenance == _question_provenance(question)
                and existing[0].content_trust == _content_trust(question)
                and existing[0].source_status == _source_status(question)
                and existing[0].answer_provenance == _answer_provenance(question)
                and existing[0].answer_reliability == _answer_reliability(question)
                and verification_metadata_matches
                and existing[0].content_reviewed_by == _content_reviewer(question)
                and (existing[0].content_reviewed_at.date() if existing[0].content_reviewed_at else None) == question.content_reviewed_on
                and (existing[0].answer_reviewed_at.date() if existing[0].answer_reviewed_at else None)
                    == (question.answer_reviewed_on if _answer_provenance(question) in {"human_verified", "verified_reference"} else None)
                and existing[0].answer_reviewed_by == (question.answer_reviewed_by if _answer_provenance(question) in {"human_verified", "verified_reference"} else None))
            fields = ("stem", "question_type", "options", "correct_answer", "explanation", "question_role",
                      "difficulty", "skill_tags", "estimated_minutes", "is_variant")
            if (len(existing) != 1 or existing[0].kp_id != node.id or not existing[0].is_active
                    or any(getattr(existing[0], field) != getattr(question, field) for field in fields)
                    or not metadata_matches):
                raise ValueError(f"existing reviewed item conflicts: {key}")
            skipped.append(key)
            continue
        if any(row.stem == question.stem and not (row.grading_config or {}).get('provenance',{}).get('key') for row in rows):
            raise ValueError(f"existing unversioned stem conflicts: {key}")
        candidate=Question(id=uuid4(),kp_id=node.id,stem=question.stem,options=question.options,
            question_type=question.question_type,correct_answer=question.correct_answer,is_variant=question.is_variant,
            bank_scope='public',grading_config={'provenance':{'source':_source_dump(question.source)}})
        public=list(db.scalars(select(Question).where(Question.bank_scope=='public',Question.generation_batch_id.is_(None))))
        found=duplicate_findings(candidate,[*public,*[row for row,_,_ in pending]])
        if found['matches']:
            by_id={str(q.id):q for q in [*public,*[row for row,_,_ in pending]]}
            match=sorted(found['matches'],key=lambda row:row['question_id'])[0];canonical=by_id[match['question_id']]
            relation='duplicate' if any(r!='same_exam_identity' for r in match['reasons']) else 'identity_conflict'
            duplicate_links.append((canonical,question,key,relation,match['reasons']))
            continue
        config = {
            "verified": bool(question.grading_method), "method": question.grading_method,
            "practice_method": question.practice_grading_method or question.grading_method,
            "version": pack.version,
            "provenance": {"key": key, "sha256": digest, "source": _source_dump(question.source),
                           "content_status": question.content_status,
                           "answer_reviewed_by": question.answer_reviewed_by,
                           "answer_review_method": question.answer_review_method,
                           "answer_review_note": question.answer_review_note,
                           "answer_reference": question.answer_reference.model_dump(mode="json") if question.answer_reference else None,
                           "content_reviewed_on": question.content_reviewed_on.isoformat() if question.content_reviewed_on else None,
                           "answer_reviewed_on": question.answer_reviewed_on.isoformat() if question.answer_reviewed_on else None,
                           "content_reviewed_by": _content_reviewer(question),
                           "question_provenance": _question_provenance(question),
                           "content_trust": _content_trust(question),
                           "source_status": _source_status(question),
                           "answer_provenance": _answer_provenance(question),
                           "answer_reliability": _answer_reliability(question)},
        }
        row = Question(
            id=candidate.id,
            kp_id=node.id, question_type=question.question_type,
            grading_mode="auto" if question.grading_method else "self_assessed", grading_config=config,
            stem=question.stem, options=question.options, correct_answer=question.correct_answer,
            explanation=question.explanation, question_role=question.question_role,
            difficulty=question.difficulty, skill_tags=question.skill_tags,
            estimated_minutes=question.estimated_minutes, is_variant=question.is_variant, is_active=True,
            question_provenance=_question_provenance(question), content_trust=_content_trust(question),
            source_status=_source_status(question),
            # A verified state is written only by the append-only event service
            # below. Keep the untrusted baseline in the new row so a later
            # revoke restores an actually unverified state rather than replaying
            # the manifest's claim without its event.
            answer_provenance=("unknown" if _answer_provenance(question) in {"human_verified", "verified_reference"}
                               else _answer_provenance(question)),
            answer_reliability=("unknown" if _answer_provenance(question) in {"human_verified", "verified_reference"}
                                else _answer_reliability(question)),
            content_reviewed_by=_content_reviewer(question),
            content_reviewed_at=_review_timestamp(question.content_reviewed_on) if _content_trust(question) == "verified" else None,
            answer_reviewed_by=None,
            answer_reviewed_at=None,
        )
        pending.append((row, question, key))
        if node.is_reference_only:
            policy_review.add(node.code)
    if apply:
        db.add_all(row for row, _, _ in pending)
        db.flush()
        for row, question, key in pending:
            answer_provenance = _answer_provenance(question)
            if answer_provenance in {"human_verified", "verified_reference"}:
                verify_answer(db, question_id=row.id, verification_type=answer_provenance,
                    verifier=question.answer_reviewed_by or "", method=question.answer_review_method or "",
                    note=question.answer_review_note or "", source_metadata=_answer_source_metadata(question),
                    expected_answer_sha256=answer_version_sha256(row),
                    idempotency_key="pack:" + hashlib.sha256(f"{key}:{digest}".encode()).hexdigest(),
                    now=_review_timestamp(question.answer_reviewed_on))
        db.flush()
        from backend.models.learning import QuestionSourceAttestation
        from backend.services.question_attestation import question_content_sha256
        for canonical,item,key,relation,reasons in duplicate_links:
            alias_key=identity_digest({'question_id':str(canonical.id),'key':key,'fingerprint':fingerprint(item)})
            if db.scalar(select(QuestionSourceAttestation).where(QuestionSourceAttestation.attestation_key==alias_key)) is None:
                db.add(QuestionSourceAttestation(attestation_key=alias_key,question_id=canonical.id,
                    candidate_id=item.source_id,pack_id=pack.pack_id,pack_version=pack.version,
                    candidate_archive_sha256=identity_digest(pack.model_dump(mode='json')),
                    source_content_sha256=fingerprint(item),question_content_sha256=question_content_sha256(canonical),
                    source_locator=item.source.citation,mapping_type='duplicate_import_alias',
                    attestation_method='duplicate-import-link-v1',attestation_source='public-pack-import-not-source-certification',
                    source_identity={**_source_dump(item.source),'candidate_payload':item.model_dump(mode='json'),'relation':relation},
                    detected_issues=reasons,status='conflict' if relation=='identity_conflict' else 'needs_review',
                    pipeline_version='public-pack-duplicate-v1'))
        db.flush()
    return {"mode": "apply" if apply else "dry_run", "new": len(pending), "unchanged": len(skipped),
            "duplicates":sum(relation=='duplicate' for _,_,_,relation,_ in duplicate_links),
            "identity_conflicts":sum(relation=='identity_conflict' for _,_,_,relation,_ in duplicate_links),
            "source_associations":[{'question_id':str(q.id),'import_key':key,'relation':relation,'reasons':reasons}
                for q,_,key,relation,reasons in duplicate_links],
            "requires_online_policy_review": sorted(policy_review)}


def _source_status(question: PackQuestion) -> str:
    # AI authorship cannot be an authenticated exam source. This normalization
    # does not change canonical origin or grant objective confirmation capacity.
    return "not_applicable" if _question_provenance(question)=="ai_generated_practice" else "verified"


def _question_provenance(question: PackQuestion) -> str:
    if question.source.content_origin == "AI_GENERATED":
        return "ai_generated_practice"
    if question.source.source_type == "exam":
        return "real_exam"
    if question.source.source_type == "mock" or question.source.kind == "original":
        return "trusted_practice"
    return "legacy_unknown"


def _content_trust(question: PackQuestion) -> str:
    return "verified" if question.content_status == "reviewed" else "needs_review"


def _content_reviewer(question: PackQuestion) -> str | None:
    return question.content_reviewed_by


def _review_timestamp(value: date | None) -> datetime | None:
    return datetime.combine(value, time.min, tzinfo=timezone.utc) if value else None


def _answer_provenance(question: PackQuestion) -> str:
    return question.answer_provenance or (
        "legacy_transcription" if question.content_status == "source_transcribed" else "unknown")


def _answer_reliability(question: PackQuestion) -> str:
    if question.answer_reliability:
        return question.answer_reliability
    provenance = _answer_provenance(question)
    return {"verified_reference": "verified", "human_verified": "verified", "ai_generated": "model_generated",
            "legacy_transcription": "unverified"}.get(provenance, "unknown")


def _answer_source_metadata(question: PackQuestion) -> dict:
    return (question.answer_reference.model_dump(mode="json")
        if question.answer_provenance == "verified_reference" and question.answer_reference
        else {"kind": "human_review"})


def _source_dump(source: SourceReview) -> dict:
    result = source.model_dump(mode="json")
    if "content_origin" not in source.model_fields_set:
        result.pop("content_origin", None)
    return result


def replace_demo_questions(db, pack: QuestionPack, demo_payload: dict, *, apply: bool = False) -> dict:
    """Retire exact seed fixtures only in replaced nodes; caller owns transaction.

    Never delete attempts/plans or relabel references as complete questions. Do not
    retire reviewed imports or modified content based merely on a matching title.
    """
    if any(q.source.source_type not in ("exam", "mock") for q in pack.questions):
        raise ValueError("replacement requires complete reviewed exam/mock questions")
    result = import_pack(db, pack, apply=False)
    if result["requires_online_policy_review"]:
        raise ValueError("review online node policy before replacing demo questions")
    if apply:
        result = import_pack(db, pack, apply=True)
    retired = retire_demo_questions(db, demo_payload, codes={q.kp_code for q in pack.questions}, apply=apply)
    return {**result, **retired}


def retire_demo_questions(db, demo_payload: dict, *, codes: set[str] | None = None, apply: bool = False) -> dict:
    """Explicit retirement without replacements; may leave an empty practice bank."""
    db.flush()  # Preserve pending edits before refreshing maintenance locks.
    retired = []
    fields = ("question_type", "stem", "options", "correct_answer", "explanation")
    for item in sorted(demo_payload.get("questions", []), key=lambda q: q["kp_code"]):
        if codes is not None and item.get("kp_code") not in codes:
            continue
        # Several demo items share one node. Make the previous retirement visible
        # before the next populate_existing query can reload that same object.
        db.flush()
        node = db.scalar(select(KnowledgePoint).where(KnowledgePoint.code == item["kp_code"])
                         .with_for_update().execution_options(populate_existing=True))
        if node is None:
            continue
        rows = db.scalars(select(Question).where(Question.kp_id == node.id, Question.is_active.is_(True))
                          .order_by(Question.id).with_for_update()
                          .execution_options(populate_existing=True)).all()
        for row in rows:
            config = row.grading_config or {}
            if isinstance(config, dict) and config.get("provenance"):
                continue
            if all(getattr(row, field) == item.get(field) for field in fields):
                retired.append(str(row.id))
                if apply:
                    row.is_active = False
    if apply:
        db.flush()
    return {"mode": "apply" if apply else "dry_run", "retired_demo_count": len(retired), "retired_demo_ids": retired,
            "history_preserved": True}
