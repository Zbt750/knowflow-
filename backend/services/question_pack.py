"""Reviewed question-pack import; no scraping, replacement or graduation writes."""
from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select, func

from backend.models.learning import KnowledgePoint, Question
from backend.services.answer_grading import available_grading_method


class SourceReview(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    kind: Literal["original", "licensed", "user_provided"]
    citation: str = Field(min_length=3, max_length=1000)
    rights_basis: str = Field(min_length=3, max_length=1000)
    reviewed_by: str = Field(min_length=1, max_length=100)
    reviewed_on: date
    year: int | None = Field(default=None, ge=2000, le=2100)
    question_number: int | None = Field(default=None, ge=1, le=200)


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
    grading_method: Literal["single_choice", "numeric_final", "logarithm_final"] | None = None

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
    answer_reviewed_by: str = Field(min_length=1, max_length=100)


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
    canonical = json.dumps(question.model_dump(mode="json"), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def import_pack(db, pack: QuestionPack, *, apply: bool = False) -> dict:
    """Caller owns commit/rollback. Validate whole pack before adding any rows."""
    # Serialize cooperating importers for one pack, including node remapping.
    lock_id = int.from_bytes(hashlib.sha256(pack.pack_id.encode()).digest()[:8], "big", signed=True)
    db.execute(select(func.pg_advisory_xact_lock(lock_id)))
    pending, skipped, policy_review = [], [], set()
    for question in sorted(pack.questions, key=lambda q: (q.kp_code, q.source_id)):
        node = db.scalar(select(KnowledgePoint).where(KnowledgePoint.code == question.kp_code).with_for_update())
        if node is None or not node.is_active or not node.is_assessable:
            raise ValueError(f"inactive, parent or missing node: {question.kp_code}")
        key = f"{pack.pack_id}:{question.source_id}"
        digest = fingerprint(question)
        rows = db.scalars(select(Question).where(Question.kp_id == node.id)).all()
        existing = db.scalars(select(Question).where(Question.grading_config["provenance"]["key"].as_string() == key)).all()
        if existing:
            fields = ("stem", "question_type", "options", "correct_answer", "explanation", "question_role",
                      "difficulty", "skill_tags", "estimated_minutes", "is_variant")
            if (len(existing) != 1 or existing[0].kp_id != node.id or not existing[0].is_active
                    or any(getattr(existing[0], field) != getattr(question, field) for field in fields)
                    or (existing[0].grading_config or {})["provenance"].get("sha256") != digest):
                raise ValueError(f"existing reviewed item conflicts: {key}")
            skipped.append(key)
            continue
        if any(row.stem == question.stem for row in rows):
            raise ValueError(f"existing unversioned stem conflicts: {key}")
        config = {
            "verified": bool(question.grading_method), "method": question.grading_method,
            "version": pack.version,
            "provenance": {"key": key, "sha256": digest, "source": question.source.model_dump(mode="json"),
                           "answer_reviewed_by": question.answer_reviewed_by},
        }
        pending.append(Question(
            kp_id=node.id, question_type=question.question_type,
            grading_mode="auto" if question.grading_method else "self_assessed", grading_config=config,
            stem=question.stem, options=question.options, correct_answer=question.correct_answer,
            explanation=question.explanation, question_role=question.question_role,
            difficulty=question.difficulty, skill_tags=question.skill_tags,
            estimated_minutes=question.estimated_minutes, is_variant=question.is_variant, is_active=True,
        ))
        if node.is_reference_only:
            policy_review.add(node.code)
    if apply:
        db.add_all(pending)
        db.flush()
    return {"mode": "apply" if apply else "dry_run", "new": len(pending), "unchanged": len(skipped),
            "requires_online_policy_review": sorted(policy_review)}
