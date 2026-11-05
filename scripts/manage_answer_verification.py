"""List local answer-review candidates or apply a hash-bound review manifest.

No model or network calls are made. Review declarations are recorded as operator
assertions, not authenticated identities or proof that a cited source is genuine.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select, text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.config import get_settings
from backend.db import create_db_engine, create_session_factory
from backend.models.learning import KnowledgePoint, Question
from backend.services.answer_verification import (
    AnswerReferenceMetadata,
    answer_version_sha256,
    current_answer_verification,
    revoke_answer_verification,
    verify_answer,
)
from backend.services.question_eligibility import question_eligibility


class VerificationCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    operation: Literal["verify", "revoke"]
    question_id: UUID
    expected_answer_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    verifier: str = Field(min_length=1, max_length=100)
    method: str = Field(min_length=3, max_length=120)
    note: str = Field(min_length=5, max_length=2000)
    idempotency_key: str = Field(min_length=1, max_length=160)
    verification_type: Literal["human_verified", "verified_reference"] | None = None
    source_reference: AnswerReferenceMetadata | None = None
    expected_verification_event_id: UUID | None = None

    @model_validator(mode="after")
    def validate_operation(self):
        if self.operation == "verify":
            if self.expected_verification_event_id is not None:
                raise ValueError("verify command cannot name a revoke target")
            if self.verification_type is None:
                raise ValueError("verify command requires verification_type")
            if self.verification_type == "verified_reference" and self.source_reference is None:
                raise ValueError("verified_reference requires a source_reference")
            if self.verification_type == "human_verified" and self.source_reference is not None:
                raise ValueError("human_verified cannot include authoritative reference metadata")
        else:
            if self.expected_verification_event_id is None:
                raise ValueError("revoke command requires expected_verification_event_id")
            if self.verification_type is not None or self.source_reference is not None:
                raise ValueError("revoke command cannot carry a new verification claim")
        return self


class VerificationManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["answer-verification-manifest-v1"]
    entries: list[VerificationCommand] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def unique_questions(self):
        question_ids = [entry.question_id for entry in self.entries]
        if len(question_ids) != len(set(question_ids)):
            raise ValueError("manifest may contain only one operation per question")
        return self


def _subject_key(value: str) -> str:
    return "math2" if value in {"math2", "数学二", "考研数学"} else "408" if value == "408" else value


def candidates(db, *, subject: str | None, limit: int) -> dict:
    query = (select(Question, KnowledgePoint)
        .join(KnowledgePoint, KnowledgePoint.id == Question.kp_id)
        .where(Question.is_active.is_(True), KnowledgePoint.is_active.is_(True))
        .order_by(KnowledgePoint.code, Question.id))
    if subject:
        expected = _subject_key(subject)
        if expected == "math2":
            query = query.where(KnowledgePoint.subject.in_(["数学二", "考研数学", "math2"]))
        else:
            query = query.where(KnowledgePoint.subject == expected)
    rows = db.execute(query.limit(limit)).all()
    items = []
    for question, node in rows:
        eligibility = question_eligibility(question, node)
        current = current_answer_verification(question)
        items.append({
            "question_id": str(question.id),
            "subject": node.subject,
            "knowledge_node": {"code": node.code, "name": node.name},
            "question_origin": question.question_provenance,
            "question_type": question.question_type,
            "stem": question.stem,
            "current_answer": question.correct_answer,
            "answer_provenance": question.answer_provenance,
            "answer_reliability": question.answer_reliability,
            "grading_capability": eligibility.grading_capability,
            "evidence_capability": eligibility.evidence_capability,
            "verification_state": ({"status": "CURRENT", "type": current.verification_type,
                "event_id": str(current.id), "verifier": current.verifier,
                "method": current.verification_method, "answer_sha256": current.answer_sha256}
                if current else {"status": "UNVERIFIED", "stale_event_id": str(question.answer_verification_event_id)
                    if question.answer_verification_event_id else None,
                    "answer_sha256": answer_version_sha256(question)}),
            "practice_eligible": eligibility.practice_eligible,
            "blocking_reasons": list(eligibility.blocking_reasons),
        })
    return {"mode": "read_only_candidates", "limit": limit, "count": len(items), "items": items}


def apply_manifest(db, manifest: VerificationManifest) -> list[dict]:
    results = []
    for command in sorted(manifest.entries, key=lambda item: str(item.question_id)):
        if command.operation == "verify":
            event = verify_answer(db, question_id=command.question_id,
                verification_type=command.verification_type or "", verifier=command.verifier,
                method=command.method, note=command.note,
                idempotency_key=command.idempotency_key,
                expected_answer_sha256=command.expected_answer_sha256,
                source_metadata=command.source_reference.model_dump(mode="json")
                    if command.source_reference else None)
        else:
            event = revoke_answer_verification(db, question_id=command.question_id,
                expected_event_id=command.expected_verification_event_id,
                verifier=command.verifier, method=command.method, note=command.note,
                idempotency_key=command.idempotency_key,
                expected_answer_sha256=command.expected_answer_sha256)
        results.append({"question_id": str(command.question_id), "operation": command.operation,
            "event_id": str(event.id), "event_type": event.event_type,
            "verification_type": event.verification_type, "answer_sha256": event.answer_sha256})
    db.flush()
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    list_parser = sub.add_parser("candidates", help="list local questions and exact answer hashes")
    list_parser.add_argument("--subject", choices=("math2", "408"))
    list_parser.add_argument("--limit", type=int, default=100)
    list_parser.add_argument("--output", type=Path, help="export only to ignored storage/answer-trust")
    apply_parser = sub.add_parser("apply", help="dry-run a local manifest; --apply writes an audit event")
    apply_parser.add_argument("manifest", type=Path)
    apply_parser.add_argument("--apply", action="store_true", help="commit verification/revocation events")
    args = parser.parse_args()

    if args.command == "candidates" and not 1 <= args.limit <= 500:
        parser.error("--limit must be between 1 and 500")
    output = None
    if args.command == "candidates" and args.output:
        from scripts.answer_trust_migration_preflight import private_output
        output = private_output(args.output)
    if args.command == "apply":
        if args.manifest.stat().st_size > 4 * 1024 * 1024:
            parser.error("manifest exceeds 4 MiB")
        manifest = VerificationManifest.model_validate_json(args.manifest.read_text(encoding="utf-8"))
        settings = get_settings()
        if args.apply and settings.app_env == "prod":
            parser.error("verification writes are disabled in APP_ENV=prod")
    else:
        manifest = None
        get_settings()
    settings = get_settings()
    engine = create_db_engine(str(settings.active_database_url))
    try:
        with create_session_factory(engine)() as db:
            revision = db.scalar(text("SELECT version_num FROM alembic_version"))
            if revision not in {"f45a9b7e2c10", "f46b2c8d901a"}:
                raise SystemExit(
                    "Refusing to run: apply migration f45a9b7e2c10 in the intended local environment first. "
                    f"Current schema revision is {revision!r}. No changes were made."
                )
            if args.command == "candidates":
                db.execute(text("SET TRANSACTION READ ONLY"))
                result = candidates(db, subject=args.subject, limit=args.limit)
                db.rollback()
            else:
                result = {"mode": "apply" if args.apply else "dry_run",
                    "changes": apply_manifest(db, manifest)}
                if args.apply:
                    db.commit()
                else:
                    db.rollback()
            if output:
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
                print(json.dumps({"mode": result["mode"], "count": result["count"], "output": str(output)}, ensure_ascii=False))
            else:
                print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
