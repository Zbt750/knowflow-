"""Replay one frozen real model response through the normal personal-question path.

The provider is an offline fixture: this test does not call DeepSeek.  The raw
response is read from the ignored Phase 4.5I run artifact, then parsed,
verified, saved, appended, and answered through application services in an
owned isolated PostgreSQL cluster.
"""
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from backend.models.learning import KnowledgePoint, KpState, Question, PracticeItem, QuestionAttempt, LearningEvent
from backend.schemas.personal_questions import PersonalGenerationRequest, GenerationTarget
from backend.services.answer_submission_service import submit_answer
from backend.services.personal_question_service import append_personal, run_generation, bank_rows
from backend.services.question_generation import (
    GENERATION_VERSION, PERSONAL_C7_PROMPT_VERSION, FAMILY_REGISTRY_VERSION,
    VERIFIER_VERSION,
)
from backend.services.question_eligibility import question_eligibility
from scripts.run_question_repair_pilot import isolated_factory


NOW = datetime(2026, 10, 9, 3, tzinfo=timezone.utc)
FROZEN_CALLS = Path("storage/quality-audits/phase45i-real-20261009/actual-run/provider-calls.jsonl")


def _frozen_derivative_output():
    if not FROZEN_CALLS.is_file():
        pytest.skip("private frozen Phase45I source output is unavailable")
    rows = [json.loads(line) for line in FROZEN_CALLS.read_text(encoding="utf-8").splitlines() if line.strip()]
    row = next((item for item in rows if item.get("call_number") == 1), None)
    if not row or row.get("http_status") != 200 or row.get("finish_reason") != "stop":
        pytest.skip("frozen derivative output is not a complete successful response")
    return row["response_content"]


class FrozenReplayProvider:
    model = "phase45i-frozen-offline-replay"
    simulation = True

    def __init__(self, raw):
        self.raw = raw
        self.calls = 0

    def complete(self, messages, *, attempt=1):
        self.calls += 1
        assert attempt == 1
        assert messages[-1]["role"] == "user"
        return self.raw, None


def test_frozen_real_candidate_uses_personal_bank_and_today_answer_path(test_database_url):
    with isolated_factory(test_database_url) as (factory, _):
        with factory.begin() as db:
            node = KnowledgePoint(code="math.exam.de439863790e", name="导数与微分的计算",
                subject="考研数学", is_active=True, is_assessable=True, is_reference_only=False)
            db.add(node)
            db.flush()
            db.add(KpState(kp_id=node.id))
            node_id = node.id

        provider = FrozenReplayProvider(_frozen_derivative_output())
        request_key = uuid4()
        body = PersonalGenerationRequest(request_key=request_key, surface="study",
            targets=[GenerationTarget(kp_id=node_id, count=1, question_type="single_choice", difficulty="basic")])
        generated = run_generation(factory, body, provider, now=NOW)

        assert provider.calls == 1
        assert generated["status"] == "completed", generated
        assert len(generated["question_ids"]) == 1
        assert generated.get("append_error") is None
        question_id = UUID(generated["question_ids"][0])

        with factory() as db:
            personal = bank_rows(db, scope="personal", kp_id=node_id)
            public = bank_rows(db, scope="public", kp_id=node_id)
            assert personal["total"] == 1
            assert public["total"] == 0
            stored = db.get(Question, question_id)
            assert stored is not None and stored.bank_scope == "personal"
            assert stored.kp_id == node_id
            assert stored.generation_batch_id == UUID(generated["batch_id"])
            assert stored.explanation and "求导" in stored.explanation
            generation = stored.grading_config["generation"]
            assert generation["version"] == GENERATION_VERSION
            assert generation["verifier_version"] == VERIFIER_VERSION
            assert generation["prompt_version"] == PERSONAL_C7_PROMPT_VERSION
            assert generation["family_registry_version"] == FAMILY_REGISTRY_VERSION
            assert generation["review_status"] == "AUTO_PASS"
            assert generation["real_model_called"] is False  # this is an offline replay fixture
            eligibility = question_eligibility(stored, db.get(KnowledgePoint, node_id))
            assert eligibility.evidence_capability == "personal_practice_only"
            item = db.scalar(select(PracticeItem).where(PracticeItem.question_id == question_id))
            assert item is None, "generation alone must not append to today's paper"
        # Represent the explicit user action after previewing the saved result.
        added = append_personal(factory, question_ids=[question_id], now=NOW)
        assert added['added'] == 1
        with factory() as db:
            item = db.scalar(select(PracticeItem).where(PracticeItem.question_id == question_id))
            assert item is not None, "explicit append action should create today's practice item"
            from backend.api.routes.study import read_practice_item_answer
            answer_view = read_practice_item_answer(item.id, db)
            assert answer_view.correct_answer == stored.correct_answer
            assert answer_view.explanation == stored.explanation
            state_before = list(db.get(KpState, node_id).evidence_window or [])

        with factory.begin() as db:
            item = db.scalar(select(PracticeItem).where(PracticeItem.question_id == question_id))
            verdict = submit_answer(db, item_id=item.id, raw_answer=None, selected_option="A",
                idempotency_key="TEST_FIXTURE phase45i frozen response", now=NOW)
            assert verdict.result == "right", verdict
            attempt = db.scalar(select(QuestionAttempt).where(QuestionAttempt.question_id == question_id))
            assert attempt is not None
            assert attempt.grading_evidence["bank_scope"] == "personal"
            assert attempt.grading_evidence["evidence_reliability"] != "verified_objective"
            assert db.get(KpState, node_id).evidence_window == state_before
            assert db.get(KpState, node_id).mastered_at is None
            event = db.scalar(select(LearningEvent).where(LearningEvent.source_id == attempt.id))
            assert event is not None
            assert event.evidence_level == "weak"

        with factory() as db:
            assert bank_rows(db, scope="personal", kp_id=node_id)["total"] == 1
            assert bank_rows(db, scope="public", kp_id=node_id)["total"] == 0
            assert len(list(db.scalars(select(QuestionAttempt).where(
                QuestionAttempt.question_id == question_id
            )))) == 1
