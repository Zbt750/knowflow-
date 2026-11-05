"""Prepare explicitly synthetic, version-bound learning fixtures in an owned test DB."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def validate_test_target(url: str | None, owned_port: str | None) -> str:
    from sqlalchemy.engine import make_url
    if not url:
        raise ValueError("Explicit TEST_DATABASE_URL required")
    parsed = make_url(url)
    try:
        port = int(parsed.port or 0)
        owner = int(owned_port or 0)
    except ValueError:
        raise ValueError("Explicit owned test port required") from None
    if (parsed.get_backend_name() != "postgresql" or parsed.host not in {"127.0.0.1", "localhost", "::1"}
            or port <= 18000 or port == 5433 or port != owner
            or not (parsed.database or "").endswith("_test")):
        raise ValueError("Refusing test target: owned loopback _test database on an isolated port required")
    return url


def prepare_learning(db) -> dict:
    from sqlalchemy import select
    from backend.models.learning import KnowledgePoint, Question, KpMasteryPolicy
    from backend.services.graduation_question_set import freeze_graduation_question_set
    from backend.services.question_eligibility import question_eligibility
    from scripts.seed import seed_all, load_json
    # These are synthetic fixtures for UI/service contracts, never real human review.
    from tests.integration.test_learning_loop import mark_isolated_question_trusted

    seed_stems = {item["stem"] for item in load_json("questions.json")["questions"]}
    if any(q.stem not in seed_stems for q in db.scalars(select(Question))):
        raise ValueError("Fresh E2E fixture database required; unrelated question data present")
    seed_all(db, include_exam_references=True)
    db.flush()
    accepted, unsupported = [], []
    by_node = {}
    for question in db.scalars(select(Question)).all():
        if question.grading_config is None and question.question_type == "calculation":
            question.grading_config = {"verified": True, "method": "numeric_final", "version": "E2E_TEST_FIXTURE"}
        mark_isolated_question_trusted(question, db=db)
        db.flush()
        node = db.get(KnowledgePoint, question.kp_id)
        eligibility = question_eligibility(question, node)
        if eligibility.practice_eligible and eligibility.evidence_capability == "verified_objective":
            accepted.append(str(question.id))
            by_node.setdefault(question.kp_id, []).append(question.id)
        else:
            unsupported.append({"question_id": str(question.id), "reasons": list(eligibility.blocking_reasons)})
    for kp_id, ids in by_node.items():
        row = db.get(KpMasteryPolicy, kp_id)
        if row is not None and row.graduation_set_version:
            if set(row.graduation_question_ids) != {str(qid) for qid in ids}:
                raise ValueError("Existing E2E frozen set differs; use a fresh fixture database")
            continue
        freeze_graduation_question_set(db, kp_id=kp_id, question_ids=ids,
            reason="E2E_TEST_FIXTURE: synthetic question/answer stamps, not content quality verification",
            now=datetime(2026, 1, 1, tzinfo=timezone.utc))
    return {"fixture_kind": "E2E_TEST_FIXTURE", "formal_fixture_count": len(accepted),
            "frozen_node_count": len(by_node), "unsupported": unsupported}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        url = validate_test_target(os.environ.get("TEST_DATABASE_URL"), os.environ.get("KAOYAN_OWNED_TEST_PORT"))
        if args.validate_only:
            print("Owned isolated test target validated")
            return 0
        if os.environ.get("APP_ENV") != "test":
            raise ValueError("APP_ENV=test required")
        if not args.apply:
            print("Dry run: synthetic fixture preparation only; pass --apply to write the isolated test database")
            return 0
        from backend.db import create_db_engine, create_session_factory
        engine = create_db_engine(url)
        try:
            with create_session_factory(engine).begin() as db:
                result = prepare_learning(db)
            print(json.dumps(result, ensure_ascii=False))
        finally:
            engine.dispose()
        return 0
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
