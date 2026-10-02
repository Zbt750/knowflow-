"""Offline golden assets: generated content cannot self-certify or enter the DB.

Review attestations are human declarations tied to exact content, not authentication
or a proof of correctness. Only the existing reviewed-pack importer writes questions.
"""
from __future__ import annotations

from collections import Counter
from datetime import date
import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.services.answer_grading import grade_final_answer
from backend.services.question_pack import PackQuestion, QuestionContent, QuestionPack, SourceReview

ASPECTS = frozenset({"source", "stem", "answer", "explanation", "mapping", "grading"})


def digest(value: dict) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Review(StrictModel):
    status: Literal["GENERATED", "UNVERIFIED", "VERIFIED"]
    reviewer_kind: Literal["human"] | None = None
    reviewed_by: str | None = Field(default=None, min_length=1, max_length=100)
    reviewed_on: date | None = None
    content_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    note: str | None = Field(default=None, min_length=5, max_length=2000)

    @model_validator(mode="after")
    def require_attestation(self):
        if self.status == "VERIFIED" and not all((self.reviewer_kind, self.reviewed_by,
                self.reviewed_on, self.content_sha256, self.note)):
            raise ValueError("VERIFIED requires a human review attestation and exact content hash")
        if self.reviewed_on and self.reviewed_on > date.today():
            raise ValueError("review date cannot be in the future")
        return self


class DraftSource(StrictModel):
    kind: Literal["original", "licensed", "user_provided"]
    origin: Literal["AI_GENERATED", "USER_PROVIDED", "LEGACY"]
    citation: str = Field(min_length=3, max_length=1000)
    rights_basis: str = Field(min_length=3, max_length=1000)


class GradingProbe(StrictModel):
    raw_answer: str | None = None
    selected_option: str | None = None
    result: Literal["right", "wrong", "unknown"]
    reason: str = Field(min_length=1, max_length=100)


class GoldenQuestion(StrictModel):
    content: QuestionContent
    source: DraftSource
    reviews: dict[str, Review]
    probes: list[GradingProbe] = Field(min_length=1, max_length=20)

    def content_hash(self) -> str:
        # Test expectations are reviewed too; changing an answer, mapping, source,
        # explanation, grading method or expected probe invalidates every stamp.
        return digest(self.model_dump(mode="json", exclude={"reviews"}))

    @model_validator(mode="after")
    def validate_reviews(self):
        if set(self.reviews) != ASPECTS:
            raise ValueError("all six review aspects must be explicit")
        sha = self.content_hash()
        if any(r.status == "VERIFIED" and r.content_sha256 != sha for r in self.reviews.values()):
            raise ValueError("review hash does not match current content")
        return self

    @property
    def verified(self) -> bool:
        return all(r.status == "VERIFIED" for r in self.reviews.values())


class GoldenTopic(StrictModel):
    kp_code: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,119}$")
    name: str = Field(min_length=1, max_length=120)
    subject: Literal["math2", "408"]
    lesson_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    lesson_review: Review

    @model_validator(mode="after")
    def lesson_stamp(self):
        if self.lesson_review.status == "VERIFIED" and self.lesson_review.content_sha256 != self.lesson_sha256:
            raise ValueError("lesson review hash mismatch")
        return self


class GoldenSlice(StrictModel):
    schema_version: Literal["golden-learning-slice-v1"]
    slice_id: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,100}$")
    version: str = Field(min_length=1, max_length=40)
    topics: list[GoldenTopic] = Field(min_length=1, max_length=10)
    questions: list[GoldenQuestion] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def scope_and_duplicates(self):
        codes = [t.kp_code for t in self.topics]
        ids = [q.content.source_id for q in self.questions]
        stems = [(q.content.kp_code, q.content.stem) for q in self.questions]
        if len(codes) != len(set(codes)) or len(ids) != len(set(ids)) or len(stems) != len(set(stems)):
            raise ValueError("duplicate topic, question ID or node/stem")
        if any(q.content.kp_code not in codes for q in self.questions):
            raise ValueError("question outside golden topic scope")
        return self


def audit_slice(asset: GoldenSlice) -> dict:
    """Run proposed grading configs only as isolated probes; never certify them."""
    rows = []
    for q in asset.questions:
        c = q.content
        probes = []
        for probe in q.probes:
            verdict = grade_final_answer(question_type=c.question_type,
                config={"verified": True, "method": c.grading_method},
                answer=probe.raw_answer, selected_option=probe.selected_option,
                expected=c.correct_answer, options=c.options)
            probes.append({"expected": probe.model_dump(), "actual": {"result": verdict.result,
                "reason": verdict.reason}, "passed": verdict.result == probe.result and verdict.reason == probe.reason})
        # This is the real unreviewed gate, even when the proposed comparator works.
        actual = grade_final_answer(question_type=c.question_type,
            config={"verified": q.verified and bool(c.grading_method), "method": c.grading_method},
            answer=c.correct_answer if c.question_type != "single_choice" else None,
            selected_option=c.correct_answer if c.question_type == "single_choice" else None,
            expected=c.correct_answer, options=c.options)
        rows.append({"source_id": c.source_id, "kp_code": c.kp_code,
            "content_sha256": q.content_hash(), "reviews": {k: r.status for k, r in q.reviews.items()},
            "verified": q.verified, "proposed_grading_method": c.grading_method,
            "actual_gate_result": actual.result, "probes": probes})
    return {"slice_id": asset.slice_id, "version": asset.version,
        "asset_sha256": digest(asset.model_dump(mode="json")),
        "answerable_drafts": len(rows), "verified_questions": sum(q.verified for q in asset.questions),
        "exam_references_counted_as_questions": 0,
        "proposed_methods": dict(Counter(q.content.grading_method or "manual_only" for q in asset.questions)),
        "all_probes_passed": all(p["passed"] for r in rows for p in r["probes"]),
        "human_review_complete": all(q.verified for q in asset.questions)
            and all(t.lesson_review.status == "VERIFIED" for t in asset.topics),
        "automatic_checks_certify_content": False, "cases": rows}


def reviewed_pack(asset: GoldenSlice) -> QuestionPack:
    """All-or-nothing export. No DB writes, no automated VERIFIED promotion."""
    blocked = [q.content.source_id for q in asset.questions if not q.verified]
    if blocked:
        raise ValueError("human review incomplete: " + ", ".join(blocked))
    if not audit_slice(asset)["all_probes_passed"]:
        raise ValueError("proposed grading probes failed; reviewed pack export blocked")
    questions = []
    for q in asset.questions:
        source_review = q.reviews["source"]
        questions.append(PackQuestion(**q.content.model_dump(), source=SourceReview(
            kind=q.source.kind, citation=q.source.citation, rights_basis=q.source.rights_basis,
            reviewed_by=source_review.reviewed_by, reviewed_on=source_review.reviewed_on),
            answer_reviewed_by=q.reviews["answer"].reviewed_by))
    return QuestionPack(pack_id=asset.slice_id, version=asset.version, questions=questions)
