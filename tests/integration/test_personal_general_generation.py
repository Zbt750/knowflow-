"""Synthetic owned-DB fixtures only; no real model, formal review or user evidence."""
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4
import json
import pytest
from sqlalchemy import select, func
from backend.models.learning import (KnowledgePoint, Question, QuestionVersion, KpState,
    PracticeItem, DailyPlan, LearningEvent, QuestionAttempt, QuestionAutoReviewEvent)
from backend.schemas.personal_questions import GenerationTarget, PersonalGenerationRequest
from backend.services.personal_question_service import run_generation, append_personal
from backend.services.personal_generation_intent import generation_confirmation, generation_intent
from backend.services.question_eligibility import question_eligibility
from backend.services.question_generation import current_generation_binding
from backend.services.answer_submission_service import submit_answer
from scripts.run_question_repair_pilot import isolated_factory

NOW = datetime(2026, 10, 17, 3, tzinfo=timezone.utc)


@pytest.fixture
def general_bank(test_database_url):
    with isolated_factory(test_database_url) as (factory, _):
        with factory.begin() as db:
            node = KnowledgePoint(code="TEST_FIXTURE.geometric_series", name="等比级数的敛散性与求和",
                subject="考研数学", is_active=True, is_assessable=True, is_reference_only=False)
            db.add(node); db.flush(); db.add(KpState(kp_id=node.id)); kp = node.id
        yield factory, kp


class GeneralModel:
    simulation = True
    model = "TEST_FIXTURE_general_no_network"

    def __init__(self, fault=None):
        self.calls = 0; self.requests = []; self.fault = fault

    def complete(self, messages, *, attempt=1):
        self.calls += 1
        if self.fault == "timeout": raise TimeoutError("TEST_FIXTURE no network")
        request = json.loads(messages[-1]["content"]); self.requests.append(request)
        kind = request["question_type"]
        data = {"stem": "已知等比级数首项为2、公比为参数r，说明其收敛条件，并计算r=1/2时的和。",
            "question_type": kind, "options": None, "correct_answer": "当|r|<1时收敛；r=1/2时和为4。",
            "explanation": "首项非零时等比级数收敛当且仅当公比绝对值小于1。取r=1/2满足条件，由部分和取极限得到和为4。",
            "final_value": "收敛条件|r|<1；指定公比时和为4", "steps": []}
        if kind == "single_choice":
            data.update(stem="首项为2的等比级数公比为r，若级数收敛且和为4，则r为多少？",
                options={"A": "1/2", "B": "2", "C": "-2", "D": "1"}, correct_answer="A", final_value="1/2")
        if self.fault == "duplicate_options": data["options"]["D"] = data["options"]["A"]
        if self.fault == "wrong_step": data["steps"] = [{"expression": "2+2", "value": "5"}]
        if self.fault == "wrong_type": data["question_type"] = "proof"
        if self.fault == "empty_explanation": data["explanation"] = " " * 20
        if self.fault == "integral_limit_contradiction":
            data.update(stem=r"设 $f(x)$ 在 $x=0$ 的某邻域内二阶可导，且 $f(0)=0$，$f'(0)=1$，$f''(0)=2$。求极限 $\lim_{x\to 0}\dfrac{x f(x)-\int_0^x f(t)\,dt}{x^3}$ 的值。",
                options={"A": r"$\dfrac{1}{3}$", "B": r"$\dfrac{1}{2}$", "C": r"$\dfrac{2}{3}$", "D": r"$1$"},
                correct_answer="C", final_value=r"$\dfrac{2}{3}$",
                explanation="该极限不存在，因为分子最低阶为 $x^2/2$；解析末尾又声称答案为 $2/3$。")
        if self.fault == "integral_limit_valid":
            data.update(stem=r"设 $f(x)$ 在 $x=0$ 附近二阶可导，$f(0)=f'(0)=0$，$f''(0)=2$。求 $\lim_{x\to0}\frac{x f(x)-\int_0^x f(t)\,dt}{x^3}$。",
                options=None, correct_answer=r"$\frac{2}{3}$", final_value=r"$\frac{2}{3}$",
                explanation=r"由二阶Taylor展开，$f(x)=x^2+o(x^2)$。因此 $xf(x)=x^3+o(x^3)$，且 $\int_0^x f(t)dt=\frac{x^3}{3}+o(x^3)$。相减后除以 $x^3$，极限为 $\frac23$。")
        if self.fault == "finite_choice_nonfinite_final":
            data.update(
                stem="设 f 在 0 附近二阶可导，f(0)=0,f'(0)=1,f''(0)=2，求一个含积分项的极限。",
                options={"A": r"\(\dfrac12\)", "B": r"\(1\)", "C": r"\(\dfrac13\)", "D": r"\(\dfrac23\)"},
                correct_answer="A",
                final_value="按所给条件计算，原极限不存在（发散）；题设不足以得到一个有限值，故无正确选项。",
                explanation="由展开可见该极限发散，因此所选有限选项与最终结论矛盾。")
        return json.dumps(data, ensure_ascii=False), {"prompt_tokens": 90, "completion_tokens": 110, "total_tokens": 200}


def request(kp, kind="single_choice"):
    return PersonalGenerationRequest(request_key=uuid4(), generation_mode="ai_generated", surface="study",
        append_to_today=True, targets=[GenerationTarget(kp_id=kp, count=1, question_type=kind, difficulty="comprehensive")])


@pytest.mark.parametrize("kind", ["single_choice", "fill_blank", "calculation", "proof", "subjective"])
def test_unregistered_topic_and_all_supported_types_save_versions_but_not_plans(general_bank, kind):
    f, kp = general_bank; model = GeneralModel(); body = request(kp, kind)
    result = run_generation(f, body, model, now=NOW)
    assert len(result["question_ids"]) == 1, result
    assert result["reference_only_question_ids"] == result["question_ids"]
    assert model.calls == 1 and result["calls"][0]["usage"]["total_tokens"] == 200
    assert model.requests[0]["node"]["code"] == "TEST_FIXTURE.geometric_series"
    assert "family_contract" not in model.requests[0]
    assert "参考" in result["message"] and "尚未加入" in result["message"]
    assert run_generation(f, body, model, now=NOW)["replayed"] and model.calls == 1
    with f() as db:
        q = db.get(Question, UUID(result["question_ids"][0])); node = db.get(KnowledgePoint, kp)
        assert q.kp_id == kp and q.bank_scope == "personal" and q.current_version_id is not None
        assert db.get(QuestionVersion, q.current_version_id).question_id == q.id
        eligibility = question_eligibility(q, node)
        assert eligibility.practice_eligible and not eligibility.objective_feedback_eligible
        assert eligibility.evidence_capability == "personal_practice_only"
        assert not eligibility.auto_review_current and eligibility.verified_grading_method is None
        assert q.auto_review_event_id is None
        assert db.scalar(select(func.count()).select_from(QuestionAutoReviewEvent)) == 0
        from backend.services.auto_question_review import assess_auto_qualification
        assert assess_auto_qualification(db, q, node)["status"] == "QUARANTINED"
        for table in (DailyPlan, PracticeItem, LearningEvent, QuestionAttempt):
            assert db.scalar(select(func.count()).select_from(table)) == 0
        assert db.get(KpState, kp).state == "unseen"
    added = append_personal(f, question_ids=[UUID(result["question_ids"][0])], now=NOW)
    assert added["added"] == 1
    assert append_personal(f, question_ids=[UUID(result["question_ids"][0])], now=NOW)["added"] == 0
    with f.begin() as db:
        verdict = submit_answer(db, item_id=UUID(added["numbers"][0]["item_id"]),
            selected_option="A" if kind == "single_choice" else None,
            raw_answer=None if kind == "single_choice" else "4", confidence="high",
            idempotency_key="TEST_FIXTURE_general_" + kind, now=NOW)
        assert verdict.result == "unknown"
        assert verdict.effective_confirmation_count == 0
        assert db.get(KpState, kp).mastered_at is None
        assert db.scalar(select(func.count()).select_from(QuestionAttempt)) == 1
        assert db.scalar(select(func.count()).select_from(LearningEvent)) == 1


def test_confirmed_wrong_integral_limit_is_rejected_before_any_save(general_bank):
    f, kp = general_bank; model = GeneralModel(fault="integral_limit_contradiction")
    result = run_generation(f, request(kp), model, now=NOW)
    assert model.calls == 1
    assert result["question_ids"] == []
    assert result["status"] == "failed"
    assert result["failures"][0]["reason"] == "CONFIRMED_WRONG"
    assert result["failures"][0]["issues"] == ["product_integral_limit_answer_conflict"]
    with f() as db:
        for table in (Question, QuestionVersion, PracticeItem, QuestionAttempt, LearningEvent):
            assert db.scalar(select(func.count()).select_from(table)) == 0


def test_proven_series_answer_conflict_is_classified_as_math_rejection(general_bank):
    from pathlib import Path
    raw = (Path(__file__).parents[1] / 'unit/fixtures/deepseek_series_conflict_20261019.json').read_text(encoding='utf-8')
    class RecordedResponse:
        simulation = True
        model = 'recorded-real-deepseek-offline-replay'
        def __init__(self): self.calls = 0
        def complete(self, messages, *, attempt=1):
            self.calls += 1
            return raw, {'prompt_tokens': 916, 'completion_tokens': 842, 'total_tokens': 1758}
    f, kp = general_bank; model = RecordedResponse()
    result = run_generation(f, request(kp, 'calculation'), model, now=NOW)
    assert model.calls == 1 and result['question_ids'] == []
    assert result['failures'][0]['reason'] == 'CONFIRMED_WRONG'
    assert set(result['failures'][0]['issues']) & {
        'answer_final_value_conflict', 'statement_answer_conflict', 'explanation_step_conflict'}
    with f() as db:
        for table in (Question, QuestionVersion, PracticeItem, QuestionAttempt, LearningEvent):
            assert db.scalar(select(func.count()).select_from(table)) == 0


def test_real_finite_choice_nonfinite_conclusion_rejected_before_any_save(general_bank):
    f, kp = general_bank; model = GeneralModel(fault="finite_choice_nonfinite_final")
    result = run_generation(f, request(kp), model, now=NOW)
    assert model.calls == 1 and result["question_ids"] == [], result
    assert result["status"] == "failed"
    assert result["failures"][0]["reason"] == "CONFIRMED_WRONG", result["failures"]
    assert "selected_option_conflicts_with_nonfinite_final_value" in result["failures"][0]["issues"]
    with f() as db:
        for table in (Question, QuestionVersion, PracticeItem, QuestionAttempt, LearningEvent):
            assert db.scalar(select(func.count()).select_from(table)) == 0


def test_bounded_math_gate_accepts_consistent_supported_control_but_keeps_unverified_status(general_bank):
    f, kp = general_bank
    result = run_generation(f, request(kp, 'calculation'), GeneralModel('integral_limit_valid'), now=NOW)
    assert len(result['question_ids']) == 1, result
    assert result['reference_only_question_ids'] == result['question_ids']
    with f() as db:
        q = db.get(Question, UUID(result['question_ids'][0]))
        generation = q.grading_config['generation']
        assert generation['mathematical_correctness_status'] == 'not_independently_verified'
        assert generation['review_status'] == 'STRUCTURE_CHECKED_REFERENCE_ONLY'
        assert generation['answer_independently_verified'] is False
        assert db.scalar(select(func.count()).select_from(QuestionVersion)) == 1
        assert db.scalar(select(func.count()).select_from(PracticeItem)) == 0


@pytest.mark.parametrize("fault", ["duplicate_options", "wrong_step", "wrong_type", "empty_explanation", "timeout"])
def test_general_content_failures_never_save_or_auto_retry(general_bank, fault):
    f, kp = general_bank; model = GeneralModel(fault)
    result = run_generation(f, request(kp), model, now=NOW)
    assert model.calls == 1 and not result["question_ids"], result
    with f() as db:
        assert db.scalar(select(func.count()).select_from(Question)) == 0
        assert db.scalar(select(func.count()).select_from(PracticeItem)) == 0


def test_real_deepseek_conflicting_formula_cannot_save_or_append(general_bank):
    from pathlib import Path
    raw=(Path(__file__).parents[1]/'unit/fixtures/deepseek_series_conflict_20261019.json').read_text(encoding='utf-8')
    class RecordedResponse:
        simulation=True
        model='recorded-real-deepseek-offline-replay'
        calls=0
        def complete(self,messages,*,attempt=1):
            self.calls+=1
            return raw,{'prompt_tokens':916,'completion_tokens':842,'total_tokens':1758}
    f,kp=general_bank;model=RecordedResponse()
    result=run_generation(f,request(kp,'calculation'),model,now=NOW)
    assert model.calls==1 and result['question_ids']==[],result
    assert result['failures'],result
    assert result['failures'][0]['reason']=='CONFIRMED_WRONG',result['failures']
    with f() as db:
        for table in (Question,QuestionVersion,PracticeItem,QuestionAttempt,LearningEvent):
            assert db.scalar(select(func.count()).select_from(table))==0


def test_confirmation_offers_every_valid_leaf_not_solver_whitelist(general_bank):
    f, kp = general_bank
    with f.begin() as db:
        root = KnowledgePoint(code="TEST_FIXTURE.root", name="高等数学", subject="考研数学", is_assessable=False)
        db.add(root); db.flush()
        for index in range(252):
            db.add(KnowledgePoint(code=f"TEST_FIXTURE.full_coverage.{index}", name=f"合成展示节点{index}",
                subject="408", parent_id=root.id, is_active=True, is_assessable=True))
        db.add(KnowledgePoint(code="TEST_FIXTURE.inactive", name="停用", subject="408", is_active=False))
    ctx = SimpleNamespace(knowledge_node_ids=[kp], question_id=None, surface="study", daily_plan_id=None)
    with f() as db:
        confirmation = generation_confirmation(db, "给我出一道等比级数的证明题", ctx, uuid4())
        assert len(confirmation["nodes"]) == 253
        assert confirmation["selected_kp_id"] == str(kp)
        assert "尚不支持" not in confirmation["message"]
        intent = generation_intent(db, "给我出一道等比级数的证明题并加入今日", ctx, uuid4(), confirmed_kp_id=kp)
        assert intent.targets[0].question_type == "proof" and not intent.append_to_today


def test_tampering_or_public_scope_cannot_reuse_general_admission(general_bank):
    f, kp = general_bank
    result = run_generation(f, request(kp), GeneralModel(), now=NOW)
    with f() as db:
        q = db.get(Question, UUID(result["question_ids"][0])); node = db.get(KnowledgePoint, kp)
        assert current_generation_binding(q, node)
        changed = deepcopy(q.grading_config); changed["generation"]["node_code"] = "another"
        q.grading_config = changed
        assert not current_generation_binding(q, node)
    with f() as db:
        q = db.get(Question, UUID(result["question_ids"][0])); node = db.get(KnowledgePoint, kp)
        q.bank_scope = "public"; q.generation_batch_id = None
        assert not question_eligibility(q, node).practice_eligible


def test_optional_verifier_error_is_audited_not_faked_as_pass(general_bank, monkeypatch):
    f, kp = general_bank
    def unavailable(_question): raise RuntimeError("TEST_FIXTURE optional verifier")
    monkeypatch.setattr("backend.services.quality_verifiers.verify_problem", unavailable)
    result = run_generation(f, request(kp), GeneralModel(), now=NOW)
    assert len(result["question_ids"]) == 1, result
    with f() as db:
        q = db.get(Question, UUID(result["question_ids"][0]))
        audit = q.grading_config["generation"]
        assert audit["independent_verification"]["status"] == "ERROR"
        assert audit["answer_independently_verified"] is False
        assert not question_eligibility(q, db.get(KnowledgePoint, kp)).objective_feedback_eligible


def test_general_assistant_confirmation_then_save_uses_same_business_stream(general_bank):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.api.routes.chat import router
    from backend.models.chat import ChatSession
    f, kp = general_bank; model = GeneralModel(); app = FastAPI(); app.include_router(router, prefix="/api")
    app.state.session_factory = f; app.state.personal_generation_provider = model
    app.state.settings = SimpleNamespace(app_env="test", capture_test_evidence=False)
    with f.begin() as db:
        session = ChatSession(title="TEST_FIXTURE general confirmation", mode="builtin", purpose="qa")
        db.add(session); db.flush(); sid = session.id
    payload = {"question": "给我出一道等比级数的敛散性与求和的题", "request_key": str(uuid4()),
        "study_context": {"surface": "study", "knowledge_node_ids": [str(kp)]}}
    with TestClient(app) as client:
        initial = client.post(f"/api/chat/sessions/{sid}/assistant:stream", json=payload)
        assert "event: personal_generation_confirmation" in initial.text and model.calls == 0
        payload.update(request_key=str(uuid4()), personal_generation_confirmed_kp_id=str(kp))
        saved = client.post(f"/api/chat/sessions/{sid}/assistant:stream", json=payload)
        assert "event: personal_generation\n" in saved.text and "event: error" not in saved.text, saved.text
        assert '"status":"completed"' in saved.text.replace(" ", "") and model.calls == 1
    with f() as db:
        assert db.scalar(select(func.count()).select_from(Question)) == 1
        assert db.scalar(select(func.count()).select_from(PracticeItem)) == 0
