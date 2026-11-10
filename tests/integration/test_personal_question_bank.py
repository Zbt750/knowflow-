"""No real provider or development data. Fixtures inside marked temporary schemas."""
from datetime import datetime, timezone, timedelta
from uuid import uuid4, UUID, uuid5, NAMESPACE_URL
from copy import deepcopy
import json
import os
import pytest
from sqlalchemy import select, func, text
from backend.models.learning import KnowledgePoint, Question, QuestionVersion, PersonalAnswerVerificationEvent, DailyPlan, PracticeItem, KpState, LearningEvent, QuestionAttempt, KpGraduationQuestionSetVersion
from backend.models.chat import ChatMessage
from backend.models.personal_generation import PersonalGenerationBatch
from backend.schemas.personal_questions import PersonalGenerationRequest, GenerationTarget
from backend.services.personal_question_service import run_generation, append_personal, bank_rows, node_activity
from backend.services.question_eligibility import question_eligibility
from backend.services.answer_submission_service import submit_answer
from backend.services.answer_verification import answer_version_sha256
from scripts.run_question_repair_pilot import isolated_factory
from scripts.run_question_generation_pilot import FixtureModel

NOW = datetime(2026,10,9,3,tzinfo=timezone.utc)


@pytest.fixture
def bank(test_database_url):
    with isolated_factory(test_database_url) as (factory, _):
        with factory.begin() as db:
            node = KnowledgePoint(code="math.exam.c431f98f817c", name="定积分的计算", subject="考研数学",
                is_active=True, is_assessable=True, is_reference_only=False)
            db.add(node); db.flush(); db.add(KpState(kp_id=node.id)); kp = node.id
        yield factory, kp


def test_runtime_role_can_read_question_versions_reviews_sets_and_personal_batches(test_database_url):
    """Check the isolated desktop application's actual DB role, not only postgres."""
    with isolated_factory(test_database_url) as (factory, _):
        with factory() as db:
            rows = db.execute(text("""
                SELECT current_user, table_name,
                       to_regclass(format('public.%I', table_name)) IS NOT NULL AS table_exists,
                       has_table_privilege(current_user, format('public.%I', table_name), 'SELECT') AS can_select
                FROM unnest(CAST(:table_names AS text[])) AS required(table_name)
            """), {"table_names": [
                "question_versions", "question_auto_review_events", "personal_answer_verification_events",
                "question_answer_verification_events", "kp_graduation_question_set_versions",
                "personal_generation_batches",
            ]}).all()
            assert rows and len(rows) == 6
            assert all(row.table_exists and row.can_select for row in rows), rows
            assert len({row.current_user for row in rows}) == 1


def body(kp, count=3, surface="study", types=None, generation_mode="ai_enhanced"):
    return PersonalGenerationRequest(request_key=uuid4(), surface=surface, generation_mode=generation_mode,
        targets=[GenerationTarget(kp_id=kp, count=c, question_type=t) for t,c in (types or [("single_choice",count)])])


class Model(FixtureModel):
    def __init__(self, faults=None): self.calls=0; self.faults=faults or {}; self.requests=[]; self.last_stem=None
    def complete(self, messages, *, attempt=1):
        self.calls += 1
        fault=self.faults.get(self.calls)
        if fault == "timeout": raise TimeoutError("TEST_FIXTURE no network")
        request=json.loads(messages[-1]["content"])
        self.requests.append(request)
        if isinstance(request.get("candidates"), list):
            response={"candidate_id":"candidate_1","wording_id":"guided",
                "teaching_focus_id":"common_pitfall"}
            if fault in {"wrong_answer","bad_explanation","missing_condition","duplicate_options","unsupported_proof","duplicate"}:
                response["stem"]="TEST_FIXTURE forbidden model-authored question"
            raw=json.dumps(response,ensure_ascii=False)
            if fault=="malformed": raw="not valid JSON"
            return raw,{"prompt_tokens":100,"completion_tokens":40,"total_tokens":140}
        if fault: request["fault"]=fault
        if fault=="duplicate": request["sample"]=1
        if isinstance(request.get("problem_spec"), dict):
            spec=request["problem_spec"]
            stem=self.last_stem if fault=="duplicate" and self.last_stem else spec["canonical_problem"]
            data={"stem":stem,"question_type":spec["question_type"],
                  "teaching_note":"先整理题目条件，再按对应规则推演，最后检查结论是否符合条件。"}
            self.last_stem=spec["canonical_problem"]
            if fault in {"duplicate_options","unsupported_proof"}: data["options"]={"A":"TEST_FIXTURE unexpected"}
            if fault=="wrong_answer": data["correct_answer"]="999"
            if fault=="bad_explanation": data["teaching_note"]="答案为999，直接选择该结果。"
            if fault=="missing_condition": data["stem"]="计算未知函数在未指定区间的定积分。"
            raw=json.dumps(data,ensure_ascii=False)
            if fault=="malformed": raw="not valid JSON"
            return raw,{"prompt_tokens":100,"completion_tokens":100,"total_tokens":200}
        wire=[*messages[:-1],{"role":"user","content":json.dumps(request)}]
        raw,_=super().complete(wire,attempt=attempt)
        if fault=='missing_condition':
            data=json.loads(raw);data['stem']='计算未知函数在未指定区间的定积分。';raw=json.dumps(data)
        if fault=='malformed':raw='not valid JSON'
        return raw,{"prompt_tokens":100,"completion_tokens":100,"total_tokens":200}


def test_mixed_generation_saves_only_then_explicit_append_is_idempotent(bank):
    f,kp=bank; b=body(kp,types=[("single_choice",2),("fill_blank",1)]); m=Model()
    r=run_generation(f,b,m,now=NOW)
    assert len(r["question_ids"])==3 and not r.get("numbers") and not r.get("append_error"), {
        "question_ids": r.get("question_ids"), "failures": r.get("failures"),
        "status": r.get("status"), "append_error": r.get("append_error"),
    }
    assert m.calls==3 and r["calls"][0]["usage"]["total_tokens"]==140
    replay=run_generation(f,b,m,now=NOW)
    assert replay["replayed"] and m.calls==3
    with f() as db:
        assert db.scalar(select(func.count()).select_from(PracticeItem))==0
        assert db.scalar(select(func.count()).select_from(DailyPlan))==0
        assert db.scalar(select(func.count()).select_from(QuestionAttempt))==0
        assert db.scalar(select(func.count()).select_from(LearningEvent))==0
        assert db.get(KpState,kp).state=="unseen"
        assert bank_rows(db,scope="personal")["total"]==3
        assert bank_rows(db,scope="public")["total"]==0
        assert node_activity(db,kp)["count"]==3
        assert "可进入练习" in node_activity(db,kp)["latest"]["message"]
    appended = append_personal(f, question_ids=[UUID(q) for q in r["question_ids"]], now=NOW)
    assert appended["added"]==3 and [n["number"] for n in appended["numbers"]]==[1,2,3]
    assert append_personal(f, question_ids=[UUID(q) for q in r["question_ids"]], now=NOW)["added"]==0
    with f() as db: assert db.scalar(select(func.count()).select_from(PracticeItem))==3


def test_question_duplicate_key_ignores_multiple_choice_label_permutation():
    from backend.services.personal_question_service import duplicate_key
    first = Question(kp_id=uuid4(), stem="求导数", question_type="single_choice",
        options={"A": "x", "B": "2x", "C": "3x", "D": "4x"})
    permuted = Question(kp_id=uuid4(), stem="求导数", question_type="single_choice",
        options={"A": "3x", "B": "x", "C": "4x", "D": "2x"})
    assert duplicate_key(first) == duplicate_key(permuted)


def test_prompt_binds_real_node_type_difficulty_and_c6_candidate_menu(bank):
    f,kp=bank; b=body(kp,types=[("single_choice",1)]); b.targets[0].difficulty="improved"; m=Model()
    result=run_generation(f,b,m,now=NOW)
    assert len(result["question_ids"])==1,result
    assert len(m.requests)==1
    request=m.requests[0]
    assert request["family"]=="power_integral"
    assert request["question_type"]=="single_choice"
    assert request["difficulty"]=="improved"
    assert request["node"]=={"name":"定积分的计算","code":"math.exam.c431f98f817c"}
    assert request["family_contract"]["registry_version"]=="personal-question-family-registry-v3"
    assert request["family_contract"]["canonical_stem_template"].startswith("计算定积分")
    assert len(request["candidates"])==3 and "problem_spec" not in request
    assert all("canonical_answer" not in candidate for candidate in request["candidates"])
    assert result["calls"][0]["prompt_version"]=="question-generation-c6-v1"
    assert result["calls"][0]["max_output_tokens"]==1200
    with f() as db:
        q=db.get(Question,UUID(result["question_ids"][0]))
        assert q.stem.startswith("请先辨认本题适用的知识规则")
        assert "常见检查" in q.explanation
        assert q.grading_config["generation"]["generation_mode"]=="ai_enhanced"


def test_ai_generated_mode_authors_full_question_and_keeps_attempt_out_of_graduation(bank):
    from backend.services.question_generation import PERSONAL_C7_PROMPT_VERSION

    factory, kp = bank
    class FullQuestionModel:
        simulation = True
        calls = 0
        requests = []
        def complete(self, messages, *, attempt=1):
            self.calls += 1
            request = json.loads(messages[-1]["content"])
            self.requests.append(request)
            return json.dumps({
                "stem": "计算定积分：∫_0^2 x dx = ____。",
                "question_type": "fill_blank", "options": None,
                "correct_answer": "2",
                "explanation": "原函数为x²/2。代入上、下限，得到2²/2−0²/2=2。",
                "final_value": "2", "steps": [{"expression": "4/2", "value": "2"}],
            }, ensure_ascii=False), {"prompt_tokens": 250, "completion_tokens": 150, "total_tokens": 400}

    model = FullQuestionModel()
    result = run_generation(factory, body(kp, 1, types=[("fill_blank", 1)],
        generation_mode="ai_generated"), model, now=NOW)
    assert model.calls == 1 and len(result["question_ids"]) == 1, result
    assert "candidates" not in model.requests[0] and "learning_focus" not in model.requests[0]
    assert model.requests[0]["family_contract"]["node_code"] == "math.exam.c431f98f817c"
    assert result["calls"][0]["prompt_version"] == PERSONAL_C7_PROMPT_VERSION
    with factory.begin() as db:
        q = db.get(Question, UUID(result["question_ids"][0]))
        version = db.get(QuestionVersion, q.current_version_id)
        item = db.scalar(select(PracticeItem).where(PracticeItem.question_id == q.id))
        assert version is not None and version.question_id == q.id
        assert version.stem == q.stem and version.correct_answer == q.correct_answer
        assert item is None
        assert db.scalar(select(func.count()).select_from(DailyPlan)) == 0
        assert "尚未加入今日学习" in result["message"]
    assert append_personal(factory, question_ids=[UUID(q) for q in result["question_ids"]], now=NOW)["added"] == 1
    with factory.begin() as db:
        q = db.get(Question, UUID(result["question_ids"][0]))
        item = db.scalar(select(PracticeItem).where(PracticeItem.question_id == q.id))
        state = db.get(KpState, kp)
        before = {"state": state.state, "mastered_at": state.mastered_at,
                  "evidence_window": list(state.evidence_window or [])}
        assert q.stem == "计算定积分：∫_0^2 x dx = ____。"
        assert q.bank_scope == "personal" and q.answer_provenance == "ai_generated"
        assert q.grading_config["generation"]["generation_mode"] == "ai_generated"
        assert q.grading_config["generation"]["prompt_version"] == PERSONAL_C7_PROMPT_VERSION
        assert item is not None and q.kp_id == kp
        assert question_eligibility(q, db.get(KnowledgePoint, kp)).evidence_capability == "personal_practice_only"
        verdict = submit_answer(db, item_id=item.id, raw_answer="2", selected_option=None,
            idempotency_key=f"TEST_FIXTURE C7 {q.id}", now=NOW)
        db.flush()
        after = {"state": state.state, "mastered_at": state.mastered_at,
                 "evidence_window": list(state.evidence_window or [])}
        assert verdict.result == "right"
        assert verdict.effective_confirmation_count == 0
        assert after == before


def test_deterministic_fast_uses_no_provider_and_is_not_counted_as_model_call(bank):
    f,kp=bank
    class ForbiddenProvider:
        def complete(self,*_args,**_kwargs): raise AssertionError("fast mode must not call a provider")
    result=run_generation(f,body(kp,1,surface="chat",generation_mode="deterministic_fast"),ForbiddenProvider(),now=NOW)
    assert len(result["question_ids"])==1 and result["model_calls"]==0 and result["calls"]==[]
    with f() as db:
        q=db.get(Question,UUID(result["question_ids"][0]))
        batch=db.get(PersonalGenerationBatch,UUID(result["batch_id"]))
        assert batch.reserved_calls==0
        assert q.question_provenance=="trusted_practice"
        assert q.answer_provenance=="server_generated" and q.answer_reliability=="unverified"
        assert q.grading_config["generation"]["prompt_version"]=="deterministic-problem-spec-v1"
        assert question_eligibility(q,db.get(KnowledgePoint,kp),teaching_enabled=True).evidence_capability=="personal_practice_only"


def test_unsupported_higher_complexity_is_rejected_before_reserving_or_calling(bank):
    from backend.errors import AppError
    f,kp=bank
    class ForbiddenProvider:
        calls=0
        def complete(self,*_args,**_kwargs): self.calls+=1; raise AssertionError("unsupported difficulty must fail closed")
    m=ForbiddenProvider(); b=body(kp,1); b.targets[0].difficulty="comprehensive"
    with f.begin() as db:
        node=db.get(KnowledgePoint,kp); node.code="math.exam.f4e5ed0360ea"; node.name="二阶行列式计算"
    with pytest.raises(AppError,match="personal_generation_unsupported_difficulty"):
        run_generation(f,b,m,now=NOW)
    assert m.calls==0
    with f() as db: assert db.scalar(select(func.count()).select_from(PersonalGenerationBatch))==0


def test_partial_quality_failures_are_retained_but_never_saved(bank):
    f,kp=bank; m=Model({2:"wrong_answer",4:"bad_explanation"})
    r=run_generation(f,body(kp,5),m,now=NOW)
    assert len(r["question_ids"])==3 and len(r["failures"])==2, r
    assert "另外2道" in r["message"]
    with f() as db: assert node_activity(db,kp)["count"]==3


@pytest.mark.parametrize("fault",["duplicate_options","unsupported_proof","wrong_answer","bad_explanation","timeout","missing_condition","malformed"])
def test_invalid_or_timeout_no_inventory(bank,fault):
    f,kp=bank; m=Model({1:fault}); r=run_generation(f,body(kp,1),m,now=NOW)
    assert r["question_ids"]==[] and r["status"]=="failed",r
    assert m.calls==1
    with f() as db: assert db.scalar(select(func.count()).select_from(PracticeItem))==0


def test_generation_ignores_append_hints_and_explicit_append_retry_without_model(bank):
    f,kp=bank; b=body(kp,2); b.plan_id=uuid4(); b.append_to_today=True; m=Model({2:"duplicate"})
    r=run_generation(f,b,m,now=NOW)
    assert len(r["question_ids"])==1 and not r.get("append_error") and not r.get("numbers"),r
    with f() as db:
        assert db.scalar(select(func.count()).select_from(PracticeItem))==0
        assert db.scalar(select(func.count()).select_from(DailyPlan))==0
    with pytest.raises(ValueError, match="plan_not_found"):
        append_personal(f,question_ids=[UUID(q) for q in r["question_ids"]],plan_id=b.plan_id,now=NOW)
    a=append_personal(f,question_ids=[UUID(q) for q in r["question_ids"]],now=NOW)
    assert a["added"]==1 and m.calls==2
    assert append_personal(f,question_ids=[UUID(q) for q in r["question_ids"]],now=NOW)["added"]==0
    with f() as db: assert "加入" in node_activity(db,kp)["latest"]["message"]


@pytest.mark.parametrize("surface", ["study", "chat", "knowledge"])
def test_generation_never_creates_today_items_until_explicit_append(bank, surface):
    f, kp = bank
    request = body(kp, 1, surface=surface)
    request.append_to_today = True
    request.plan_id = uuid4()
    result = run_generation(f, request, Model(), now=NOW)
    assert len(result["question_ids"]) == 1 and not result.get("numbers")
    with f() as db:
        question = db.get(Question, UUID(result["question_ids"][0]))
        assert question.kp_id == kp and question.bank_scope == "personal"
        assert db.scalar(select(func.count()).select_from(PracticeItem)) == 0
        assert db.scalar(select(func.count()).select_from(DailyPlan)) == 0
        assert question_eligibility(question, db.get(KnowledgePoint, kp)).evidence_capability == "personal_practice_only"
    first = append_personal(f, question_ids=[UUID(result["question_ids"][0])], now=NOW)
    second = append_personal(f, question_ids=[UUID(result["question_ids"][0])], now=NOW)
    assert first["added"] == 1 and second["added"] == 0
    with f() as db: assert db.scalar(select(func.count()).select_from(PracticeItem)) == 1


def test_personal_attempt_saved_hidden_history_and_graduation_exclusion(bank):
    f,kp=bank; r=run_generation(f,body(kp,1),Model(),now=NOW)
    assert append_personal(f,question_ids=[UUID(r["question_ids"][0])],now=NOW)["added"]==1
    with f.begin() as db:
        q=db.get(Question,UUID(r["question_ids"][0])); item=db.scalar(select(PracticeItem)); state=db.get(KpState,kp)
        before=deepcopy(state.evidence_window)
        verdict=submit_answer(db,item_id=item.id,raw_answer=None,selected_option=q.correct_answer,idempotency_key="TEST_FIXTURE personal answer",now=NOW)
        assert verdict.result=="right",verdict
        assert state.evidence_window==before and state.mastered_at is None
        attempt=db.scalar(select(QuestionAttempt))
        assert attempt.grading_evidence["bank_scope"]=="personal"
        assert attempt.grading_evidence["generation_batch_id"]==r["batch_id"]
        assert attempt.grading_evidence["evidence_reliability"]!="verified_objective"
        history=deepcopy(attempt.grading_evidence)
        q.is_hidden=True
    with f() as db:
        assert bank_rows(db)["total"]==0 and bank_rows(db,include_hidden=True)["total"]==1
        assert db.scalar(select(QuestionAttempt)).grading_evidence==history
        assert node_activity(db,kp)["count"]==0
        assert db.scalar(select(LearningEvent)).evidence_level=="weak"


def test_forged_public_provenance_cannot_certify_personal(bank):
    f,kp=bank; r=run_generation(f,body(kp,1,surface="chat"),Model(),now=NOW)
    with f.begin() as db:
        q=db.get(Question,UUID(r["question_ids"][0])); q.question_provenance="real_exam"
        q.content_trust="verified"; q.source_status="verified"; q.answer_provenance="human_verified"; q.answer_reliability="verified"
        q.grading_config={"verified":True,"method":"single_choice"}
        eligibility=question_eligibility(q,db.get(KnowledgePoint,kp))
        assert eligibility.evidence_capability=="personal_practice_only" and not eligibility.verified_grading_method
        assert db.scalar(select(func.count()).select_from(PracticeItem))==0


def test_scope_conflict_daily_limit_and_no_implicit_generating(bank):
    f,kp=bank; b=body(kp,1); m=Model(); run_generation(f,b,m,now=NOW)
    b.surface="chat"
    with pytest.raises(Exception,match="idempotency"):run_generation(f,b,m,now=NOW)
    from backend.services.personal_generation_intent import explicitly_generate
    assert not explicitly_generate("帮我练习一下")
    assert not explicitly_generate("不要生成新题，给我补两道已有题")
    assert not explicitly_generate("出题功能怎么用？")
    assert not explicitly_generate("帮我生成今日练习卷")
    assert explicitly_generate("给我出2道选择题、1道填空题")
    from backend.services.personal_generation_intent import generation_intent
    from backend.schemas.learning_assistant import StudyContext
    with f() as db:
        ctx=StudyContext(surface='study',knowledge_node_ids=[kp])
        explicit_but_separate = generation_intent(db, "生成一道定积分题并加入今日学习", ctx, uuid4())
        assert explicit_but_separate.append_to_today is False
        for bad in ('生成0道定积分题','生成十二道定积分题','生成一百道定积分题'):
            with pytest.raises(Exception):generation_intent(db,bad,ctx,uuid4())
    with f.begin() as db:
        db.get(PersonalGenerationBatch,UUID(run_generation(f,body(kp,1,surface="chat"),m,now=NOW)["batch_id"])).reserved_calls=30
    with pytest.raises(Exception):run_generation(f,body(kp,1),m,now=NOW)


def test_real_api_generates_lists_hides_and_retries_append(bank):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.api.routes.personal_questions import router
    from backend.api.routes.study import router as study_router
    from backend.api.deps import get_time_provider
    from backend.errors import AppError, app_error_handler
    f,kp=bank; app=FastAPI(); app.include_router(router,prefix="/api")
    app.include_router(study_router,prefix="/api")
    app.add_exception_handler(AppError,app_error_handler)
    app.state.session_factory=f; app.state.personal_generation_provider=Model()
    app.dependency_overrides[get_time_provider]=lambda:lambda:NOW
    with TestClient(app) as c:
        request=body(kp,1,surface="study")
        request.append_to_today=True
        r=c.post('/api/personal-questions/generate',json=request.model_dump(mode='json'))
        assert r.status_code==200,r.text
        q=r.json()['question_ids'][0]
        with f() as db:
            assert db.scalar(select(func.count()).select_from(PracticeItem))==0
            assert db.scalar(select(func.count()).select_from(DailyPlan))==0
        assert c.get('/api/question-bank?scope=personal').json()['total']==1
        assert c.get('/api/question-bank?scope=public').json()['total']==0
        detail=c.get(f'/api/knowledge/{kp}')
        assert detail.status_code==200,detail.text
        assert detail.json()['personal_questions']['count']==1
        assert c.get(f'/api/personal-questions/batches/{request.request_key}').json()['status']=='completed'
        a=c.post('/api/personal-questions/append',json={'question_ids':[q]})
        assert a.status_code==200 and a.json()['added']==1,a.text
        assert c.post('/api/personal-questions/append',json={'question_ids':[q]}).json()['added']==0
        assert c.patch(f'/api/personal-questions/{q}/visibility',json={'hidden':True}).status_code==200
        assert c.get(f'/api/knowledge/{kp}').json()['personal_questions']['count']==0
        assert c.get('/api/knowledge/tree').json()['nodes'][0]['online_question_count']==0
        assert c.get('/api/question-bank').json()['total']==0
        assert c.get('/api/question-bank?include_hidden=true').json()['total']==1
        assert c.patch(f'/api/personal-questions/{q}/visibility',json={'hidden':False}).status_code==200
        assert c.post('/api/personal-questions/generate',json=request.model_dump(mode='json')).json()['replayed']
        assert app.state.personal_generation_provider.calls==1


def test_assistant_stream_explicit_generation_uses_same_real_services(bank):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.api.routes.chat import router
    from backend.models.chat import ChatSession
    from types import SimpleNamespace
    f,kp=bank; app=FastAPI();app.include_router(router,prefix='/api')
    app.state.session_factory=f;app.state.personal_generation_provider=Model();app.state.settings=SimpleNamespace(app_env='test',capture_test_evidence=False)
    with f.begin() as db:
        s=ChatSession(title='TEST_FIXTURE generation',mode='builtin',purpose='qa');db.add(s);db.flush();sid=s.id
    with TestClient(app) as c:
        data={'question':'给我生成2道定积分基础选择题','request_key':str(uuid4()),
              'study_context':{'surface':'chat','knowledge_node_ids':[str(kp)],'conversation_id':str(sid)}}
        r=c.post(f'/api/chat/sessions/{sid}/assistant:stream',json=data)
        assert r.status_code==200 and 'event: personal_generation_confirmation' in r.text,r.text
        assert app.state.personal_generation_provider.calls==0
        # 明确知识点确认之后，才允许进入现有生成及独立核验服务。
        data={**data,'request_key':str(uuid4()),'personal_generation_confirmed_kp_id':str(kp)}
        r=c.post(f'/api/chat/sessions/{sid}/assistant:stream',json=data)
        assert r.status_code==200 and 'event: personal_generation' in r.text,r.text
        assert 'event: error' not in r.text,r.text
        assert c.post(f'/api/chat/sessions/{sid}/assistant:stream',json=data).status_code==200
        assert app.state.personal_generation_provider.calls==2
    with f() as db:
        # The deterministic fixture deliberately returns the same C7 item on
        # each model call; the shared real duplicate gate should keep only the
        # first one rather than inventing a second distinct question.
        assert bank_rows(db)['total']==1
        assert db.scalar(select(func.count()).select_from(DailyPlan))==0


def test_confirmed_node_id_resolves_duplicate_topic_names_in_generation_card(bank):
    """The card's selected node ID is authoritative when two valid nodes share a display name."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.api.routes.chat import router
    from backend.models.chat import ChatMessage, ChatSession
    from backend.api.deps import get_time_provider
    from types import SimpleNamespace
    f,_=bank
    with f.begin() as db:
        selected=KnowledgePoint(code='math.exam.c5c672022b7f',name='洛必达法则',subject='考研数学',
            is_active=True,is_assessable=True,is_reference_only=False)
        ambiguous=KnowledgePoint(code='fixture.math.duplicate_lhopital',name='洛必达法则',subject='考研数学',
            is_active=True,is_assessable=True,is_reference_only=False)
        db.add_all([selected,ambiguous]);db.flush()
        db.add_all([KpState(kp_id=selected.id),KpState(kp_id=ambiguous.id)])
        session=ChatSession(title='TEST_FIXTURE confirmed node scope',mode='builtin',purpose='qa')
        db.add(session);db.flush();sid=session.id;kp=selected.id
    app=FastAPI();app.include_router(router,prefix='/api');app.state.session_factory=f
    app.state.personal_generation_provider=Model();app.state.settings=SimpleNamespace(app_env='test',capture_test_evidence=False)
    app.dependency_overrides[get_time_provider]=lambda:lambda:NOW
    with TestClient(app) as client:
        data={'question':'给我生成一道洛必达法则的练习题','request_key':str(uuid4()),
            'personal_generation_mode':'ai_generated',
            'study_context':{'surface':'chat','knowledge_node_ids':[str(kp)],'conversation_id':str(sid)}}
        first=client.post(f'/api/chat/sessions/{sid}/assistant:stream?purpose=qa',json=data)
        assert first.status_code==200 and 'event: personal_generation_confirmation' in first.text,first.text
        with f() as db:
            confirmation=db.scalar(select(ChatMessage).where(ChatMessage.session_id==sid,ChatMessage.role=='assistant')
                .order_by(ChatMessage.seq.desc()).limit(1))
            assert confirmation and (confirmation.metadata_ or {}).get('personal_generation_confirmation')
            confirmation_id=str(confirmation.id)
        confirmed={**data,'request_key':str(uuid4()),'personal_generation_confirmed_kp_id':str(kp),
            'personal_generation_confirmation_message_id':confirmation_id}
        second=client.post(f'/api/chat/sessions/{sid}/assistant:stream?purpose=qa',json=confirmed)
        assert second.status_code==200 and 'event: personal_generation' in second.text,second.text
        assert 'personal_generation_scope_required' not in second.text,second.text
        assert app.state.personal_generation_provider.calls>0
    generation_request=app.state.personal_generation_provider.requests[0]
    assert generation_request['node']['code']=='math.exam.c5c672022b7f',generation_request


def test_chat_ai_generated_timeout_can_be_retried_once_and_stays_personal(test_database_url,monkeypatch):
    """A failed C7 attempt is visible, a safe explicit retry gets a fresh key, and saved content never becomes public."""
    import logging
    import sys,traceback
    from logging import LogRecord,ERROR,Formatter
    import backend.services.question_generation as question_generation_module
    import backend.services.personal_question_service as personal_question_module
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.api.routes.chat import router as chat_router
    from backend.api.routes.personal_questions import router as personal_questions_router
    from backend.models.chat import ChatSession
    from backend.models.learning import KpGraduationQuestionSetVersion
    from backend.api.deps import get_time_provider
    from types import SimpleNamespace

    with isolated_factory(test_database_url) as (factory,_):
        with factory.begin() as db:
            node=KnowledgePoint(code='math.exam.c5c672022b7f',name='洛必达法则',subject='考研数学',
                is_active=True,is_assessable=True,is_reference_only=False)
            db.add(node);db.flush();db.add(KpState(kp_id=node.id))
            plan=DailyPlan(study_date=NOW.astimezone(timezone.utc).date().isoformat(),status='active')
            db.add(plan)
            session=ChatSession(title='TEST_FIXTURE LHopital C7 retry',mode='builtin',purpose='qa')
            db.add(session);db.flush();kp=node.id;pid=plan.id;sid=session.id

        class TimeoutThenValidModel:
            simulation=True
            def __init__(self): self.calls=0; self.requests=[]
            def complete(self,messages,*,attempt=1):
                self.calls+=1
                if self.calls==1: raise TimeoutError('TEST_FIXTURE provider timeout')
                request=json.loads(messages[-1]['content']);self.requests.append(request)
                return json.dumps({
                    'stem':r'计算极限：\lim_{x\to 0}\frac{e^{2x}-1-2x}{x^2} 的值是（ ）。',
                    'question_type':'single_choice','options':{'A':'1','B':'2','C':'3','D':'4'},
                    'correct_answer':'B',
                    'explanation':'当x趋近0时，e^{2x}=1+2x+2x^2+o(x^2)，二次项系数为2，因此极限为2。',
                    'final_value':'2','steps':[]
                },ensure_ascii=False),{'prompt_tokens':200,'completion_tokens':120,'total_tokens':320}

        model=TimeoutThenValidModel();app=FastAPI();app.include_router(chat_router,prefix='/api')
        app.include_router(personal_questions_router,prefix='/api')
        app.state.session_factory=factory;app.state.personal_generation_provider=model
        app.state.settings=SimpleNamespace(app_env='test',capture_test_evidence=False)
        app.dependency_overrides[get_time_provider]=lambda:lambda:NOW
        context={'surface':'chat','knowledge_node_ids':[],'daily_plan_id':str(pid),'conversation_id':str(sid)}
        original='给我生成一道洛必达法则的练习题'
        initial={'question':original,'request_key':str(uuid4()),'study_context':context,
            'personal_generation_mode':'ai_generated'}
        with TestClient(app) as c:
            first=c.post(f'/api/chat/sessions/{sid}/assistant:stream',json=initial)
            assert first.status_code==200 and 'event: personal_generation_confirmation' in first.text,first.text
            first_history=c.get(f'/api/chat/sessions/{sid}/messages').json()
            card_id=next(row['message_id'] for row in reversed(first_history)
                if row['role']=='assistant' and row.get('personal_generation_confirmation'))
            confirmed={**initial,'request_key':str(uuid4()),
                'personal_generation_confirmed_kp_id':str(kp),
                'personal_generation_confirmation_message_id':card_id}
            private_tracebacks=[]
            for module in (question_generation_module,personal_question_module):
                target_logger=module.logger;original_exception=target_logger.exception
                def capture_exception(*args,_original=original_exception,_logger=target_logger,**kwargs):
                    exc_info=sys.exc_info()
                    record=LogRecord(_logger.name,ERROR,__file__,0,args[0],args[1:] or (),exc_info)
                    private_tracebacks.append(Formatter().format(record))
                    return _original(*args,**kwargs)
                monkeypatch.setattr(target_logger,'exception',capture_exception)
            failed=c.post(f'/api/chat/sessions/{sid}/assistant:stream',json=confirmed)
            assert failed.status_code==200 and 'event: personal_generation' in failed.text,failed.text
            error_data=json.loads(next(block.split('data: ',1)[1] for block in failed.text.split('\n\n')
                if block.startswith('event: error\n')))
            assert error_data['retryable'] is True,error_data
            assert 'PROVIDER_TIMEOUT' in failed.text and model.calls==1
            history=c.get(f'/api/chat/sessions/{sid}/messages').json()
            failed_row=next(row for row in reversed(history) if row['role']=='assistant' and row['status']=='failed')
            assert failed_row['personal_generation']['failure_stage']=='provider_call'
            assert failed_row['personal_generation']['failure_type']=='TimeoutError'
            assert failed_row['personal_generation']['question_ids']==[]
            private_traceback='\n'.join(private_tracebacks)
            assert 'TimeoutError' in private_traceback and 'stage=provider_call' in private_traceback,private_traceback
            evidence_dir=os.environ.get('PHASE45I_CLOSE_OUTPUT')
            if evidence_dir:
                from pathlib import Path
                Path(evidence_dir,'personal-generation-timeout-traceback.txt').write_text(
                    private_traceback,encoding='utf-8')

            assistant_ids_before_retry=[row['message_id'] for row in history if row['role']=='assistant']
            retried=c.post(f'/api/chat/sessions/{sid}/assistant:stream',json={**confirmed,
                'request_key':str(uuid4()),'retry_of_message_id':failed_row['message_id']})
            assert retried.status_code==200 and 'event: personal_generation' in retried.text,retried.text
            assert 'event: error' not in retried.text,retried.text
            assert model.calls==2
            history_after_retry=c.get(f'/api/chat/sessions/{sid}/messages').json()
            assistant_rows_after_retry=[row for row in history_after_retry if row['role']=='assistant']
            assert [row['message_id'] for row in assistant_rows_after_retry]==assistant_ids_before_retry
            retried_row=next(row for row in assistant_rows_after_retry if row['message_id']==failed_row['message_id'])
            assert retried_row['status']=='completed'
            with factory() as db:
                retried_record=db.get(ChatMessage,UUID(failed_row['message_id']))
                attempts=retried_record.metadata_.get('retry_history',[])
                assert len(attempts)==1 and attempts[0]['failure_stage']=='provider_call',attempts
            result=json.loads(next(block.split('data: ',1)[1] for block in retried.text.split('\n\n')
                if block.startswith('event: personal_generation\n')))
            assert result['status']=='completed' and len(result['question_ids'])==1,result
            qid=result['question_ids'][0]
            batch=c.get(f'/api/personal-questions/batches/{result["batch_id"]}')
            assert batch.status_code==200 and batch.json()['status']=='completed'
            assert c.get('/api/question-bank?scope=personal').json()['total']==1
            assert c.get('/api/question-bank?scope=public').json()['total']==0

            appended=c.post(f'/api/chat/sessions/{sid}/assistant:stream',json={**confirmed,
                'request_key':str(uuid4()),'question':'把这道题加入今天的学习',
                'personal_generation_confirmed_kp_id':None,
                'personal_generation_confirmation_message_id':None})
            assert appended.status_code==200 and '已将刚才生成的 AI 练习题加入今日学习（本次新增 1 道）' in appended.text,appended.text
            with factory() as db:
                q=db.get(Question,UUID(qid))
                item=db.scalar(select(PracticeItem).where(PracticeItem.plan_id==pid,PracticeItem.question_id==UUID(qid)))
                assert q and q.bank_scope=='personal' and q.question_provenance=='ai_generated_practice'
                assert item and item.question_version_id==q.current_version_id
                assert db.scalar(select(func.count()).select_from(QuestionAttempt))==0
                assert db.scalar(select(func.count()).select_from(KpGraduationQuestionSetVersion))==0
                assert db.get(KpState,kp).state=='unseen'


def test_chat_ai_generated_math_rejection_can_be_explicitly_retried(test_database_url):
    """A proven wrong answer is not saved, is retryable, and a fresh explicit attempt can succeed."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from types import SimpleNamespace
    from backend.api.routes.chat import router as chat_router
    from backend.api.routes.personal_questions import router as personal_questions_router
    from backend.models.chat import ChatSession
    from backend.api.deps import get_time_provider

    with isolated_factory(test_database_url) as (factory, _):
        with factory.begin() as db:
            node=KnowledgePoint(code='math.test.lhopital_generic',name='洛必达法则',subject='考研数学',
                is_active=True,is_assessable=True,is_reference_only=False)
            db.add(node);db.flush();db.add(KpState(kp_id=node.id))
            plan=DailyPlan(study_date=NOW.astimezone(timezone.utc).date().isoformat(),status='active')
            db.add(plan);session=ChatSession(title='TEST_FIXTURE LHopital math rejection retry',mode='builtin',purpose='qa')
            db.add(session);db.flush();kp=node.id;pid=plan.id;sid=session.id

        class WrongThenCorrectProvider:
            simulation=True
            def __init__(self):self.calls=0
            def complete(self,_messages,*,attempt=1):
                self.calls+=1;wrong=self.calls==1
                data={'stem':r'求极限 \(\displaystyle\lim_{x\to 1}\frac{x^3-3x^2+3x-1}{x^2-2x+1}\)，下面正确的是（ ）',
                    'question_type':'single_choice','options':{'A':r'\(0\)','B':r'\(\frac{3}{2}\)','C':r'\(\frac{1}{2}\)','D':r'\(1\)'},
                    'correct_answer':'B' if wrong else 'A','explanation':'TEST_FIXTURE 按题目约分计算极限。',
                    'final_value':'3/2' if wrong else '0','steps':[]}
                return json.dumps(data,ensure_ascii=False),{'prompt_tokens':120,'completion_tokens':90,'total_tokens':210}

        model=WrongThenCorrectProvider();app=FastAPI();app.include_router(chat_router,prefix='/api')
        app.include_router(personal_questions_router,prefix='/api');app.state.session_factory=factory
        app.state.personal_generation_provider=model;app.state.settings=SimpleNamespace(app_env='test',capture_test_evidence=False)
        app.dependency_overrides[get_time_provider]=lambda:lambda:NOW
        context={'surface':'chat','knowledge_node_ids':[],'daily_plan_id':str(pid),'conversation_id':str(sid)}
        original='给我生成一道洛必达法则的练习题'
        initial={'question':original,'request_key':str(uuid4()),'study_context':context,'personal_generation_mode':'ai_generated'}
        with TestClient(app) as c:
            first=c.post(f'/api/chat/sessions/{sid}/assistant:stream?purpose=qa',json=initial)
            assert first.status_code==200 and 'event: personal_generation_confirmation' in first.text,first.text
            history=c.get(f'/api/chat/sessions/{sid}/messages?purpose=qa').json()
            card=next(row for row in reversed(history) if row['role']=='assistant' and row.get('personal_generation_confirmation'))
            confirmed={**initial,'request_key':str(uuid4()),'personal_generation_confirmed_kp_id':str(kp),
                'personal_generation_confirmation_message_id':card['message_id']}
            failed=c.post(f'/api/chat/sessions/{sid}/assistant:stream?purpose=qa',json=confirmed)
            assert failed.status_code==200 and 'personal_generation_answer_conflict' in failed.text,failed.text
            error=json.loads(next(block.split('data: ',1)[1] for block in failed.text.split('\n\n') if block.startswith('event: error\n')))
            assert error['retryable'] is True and error['failure_stage']=='math_verification',error
            history=c.get(f'/api/chat/sessions/{sid}/messages?purpose=qa').json()
            failed_row=next(row for row in reversed(history) if row['role']=='assistant' and row['status']=='failed')
            saved=failed_row['personal_generation']
            assert saved['question_ids']==[] and saved['failure_stage']=='math_verification'
            assert saved['failures'][0]['reason']=='CONFIRMED_WRONG' and model.calls==1
            with factory() as db:
                assert db.scalar(select(func.count()).select_from(Question).where(Question.bank_scope=='personal'))==0
                batch=db.scalar(select(PersonalGenerationBatch).where(PersonalGenerationBatch.status=='failed'))
                assert batch and batch.result['question_ids']==[]

            assistant_ids_before_retry=[row['message_id'] for row in history if row['role']=='assistant']
            retried=c.post(f'/api/chat/sessions/{sid}/assistant:stream?purpose=qa',json={**confirmed,
                'request_key':str(uuid4()),'retry_of_message_id':failed_row['message_id']})
            assert retried.status_code==200 and 'event: error\n' not in retried.text,retried.text
            assert model.calls==2
            history_after_retry=c.get(f'/api/chat/sessions/{sid}/messages?purpose=qa').json()
            assistant_rows_after_retry=[row for row in history_after_retry if row['role']=='assistant']
            assert [row['message_id'] for row in assistant_rows_after_retry]==assistant_ids_before_retry
            assert next(row for row in assistant_rows_after_retry if row['message_id']==failed_row['message_id'])['status']=='completed'
            with factory() as db:
                retried_record=db.get(ChatMessage,UUID(failed_row['message_id']))
                attempts=retried_record.metadata_.get('retry_history',[])
                assert len(attempts)==1 and attempts[0]['failure_stage']=='math_verification',attempts
            result=json.loads(next(block.split('data: ',1)[1] for block in retried.text.split('\n\n')
                if block.startswith('event: personal_generation\n')))
            assert result['status']=='completed' and len(result['question_ids'])==1,result
            with factory() as db:
                q=db.get(Question,UUID(result['question_ids'][0]))
                assert q and q.bank_scope=='personal' and q.question_provenance=='ai_generated_practice'
                assert db.scalar(select(func.count()).select_from(Question).where(Question.bank_scope=='public'))==0


@pytest.mark.parametrize('unsupported_context',[False,True])
def test_assistant_generation_preflight_never_calls_model_or_changes_paper(bank,unsupported_context):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.api.routes.chat import router
    from backend.models.chat import ChatSession
    from types import SimpleNamespace
    f,kp=bank;app=FastAPI();app.include_router(router,prefix='/api')
    app.state.session_factory=f;app.state.personal_generation_provider=Model();app.state.settings=SimpleNamespace(app_env='test',capture_test_evidence=False)
    with f.begin() as db:
        if unsupported_context:
            other=KnowledgePoint(code='TEST_FIXTURE.curvature',name='曲率',subject='考研数学',is_active=True,is_assessable=True)
            db.add(other);db.flush();scope=[str(other.id)]
        else:scope=[]
        session=ChatSession(title='TEST_FIXTURE preflight',mode='builtin',purpose='qa')
        db.add(session);db.flush();sid=session.id
    payload={'question':'给我出一道曲率题' if unsupported_context else '给我出一道新题',
        'request_key':str(uuid4()),'study_context':{'surface':'chat','knowledge_node_ids':scope}}
    with TestClient(app) as c:
        response=c.post(f'/api/chat/sessions/{sid}/assistant:stream',json=payload)
        assert 'event: personal_generation_confirmation' in response.text,response.text
        assert 'event: error' not in response.text
        assert app.state.personal_generation_provider.calls==0
        # 只提示选择真实可核验的节点，不悄悄替用户换范围。
        confirmation=json.loads(next(block.split('data: ',1)[1] for block in response.text.split('\n\n')
            if block.startswith('event: personal_generation_confirmation\n')))
        assert confirmation['selected_kp_id'] == (scope[0] if unsupported_context else None)
        history=c.get(f'/api/chat/sessions/{sid}/messages').json()
        offered = {row['kp_id'] for row in history[-1]['personal_generation_confirmation']['nodes']}
        assert str(kp) in offered
        if unsupported_context: assert scope[0] in offered
    with f() as db:
        assert db.scalar(select(func.count()).select_from(Question))==0
        assert db.scalar(select(func.count()).select_from(PersonalGenerationBatch))==0
        assert db.scalar(select(func.count()).select_from(PracticeItem))==0


def test_actual_visible_numbers_and_old_item_ids_are_stable(bank):
    f,kp=bank
    with f.begin() as db:
        p=DailyPlan(study_date=NOW.date().isoformat(),status='active');db.add(p);db.flush();pid=p.id
        old=[]
        for i,qt in enumerate(['single_choice']*3+['fill_blank']*2+['calculation']*3,1):
            q=Question(kp_id=kp,question_type=qt,stem=f'TEST_FIXTURE old {i}',correct_answer='1',explanation='TEST_FIXTURE old explanation')
            db.add(q);db.flush();item=PracticeItem(plan_id=p.id,question_id=q.id,kp_id=kp,ordinal=i)
            db.add(item);db.flush();old.append(item.id)
    b=body(kp,types=[('single_choice',2),('fill_blank',1)]);b.plan_id=pid
    r=run_generation(f,b,Model(),now=NOW)
    assert len(r['question_ids'])==3 and not r.get('numbers'),r
    with f() as db:
        items=list(db.scalars(select(PracticeItem).where(PracticeItem.plan_id==pid).order_by(PracticeItem.ordinal)))
        assert [i.id for i in items]==old
    appended=append_personal(f,question_ids=[UUID(q) for q in r['question_ids']],plan_id=pid,now=NOW)
    assert [n['number'] for n in appended['numbers']]==[4,5,8],appended
    with f() as db:
        items=list(db.scalars(select(PracticeItem).where(PracticeItem.plan_id==pid).order_by(PracticeItem.ordinal)))
        assert [i.id for i in items[:8]]==old


def test_multi_node_counts_and_saved_only_no_mastery(bank):
    f,kp=bank
    with f.begin() as db:
        node=KnowledgePoint(code='cs408.ds.topic.1efaf3d00b50',name='二叉树基础（性质+存储）',subject='408',is_active=True,is_assessable=True,is_reference_only=False)
        db.add(node);db.flush();other=node.id;db.add(KpState(kp_id=other))
    b=body(kp,1,surface='knowledge');b.targets.append(GenerationTarget(kp_id=other,count=2))
    r=run_generation(f,b,Model(),now=NOW)
    assert len(r['question_ids'])==3,r
    with f() as db:
        assert node_activity(db,kp)['count']==1 and node_activity(db,other)['count']==2
        assert db.scalar(select(func.count()).select_from(LearningEvent))==0
        assert db.scalar(select(func.count()).select_from(PracticeItem))==0
        assert all(s.state=='unseen' for s in db.scalars(select(KpState)))


def test_unregistered_node_name_does_not_reserve_or_call_provider(bank):
    f,kp=bank
    with f.begin() as db:
        node=db.get(KnowledgePoint,kp)
        node.code="TEST_FIXTURE.looks_like_integral"
        node.name="定积分的计算"
    model=Model()
    with pytest.raises(Exception,match="personal_generation_unsupported"):
        run_generation(f,body(kp,1),model,now=NOW)
    assert model.calls==0
    with f() as db:
        assert db.scalar(select(func.count()).select_from(PersonalGenerationBatch))==0


@pytest.mark.parametrize("generation_mode", ["ai_enhanced", "deterministic_fast"])
def test_c6_registered_families_run_through_personal_bank_and_attempt_isolation(bank, generation_mode):
    from scripts.run_phase45i_real_batch import load_targets
    from backend.services.personal_question_families import resolve_family

    factory, existing_integral_id = bank
    fixture, _, _, _ = load_targets()
    subject_targets = {"数学二": [], "408": []}
    with factory.begin() as db:
        for record in fixture["nodes"]:
            node = db.scalar(select(KnowledgePoint).where(KnowledgePoint.code == record["code"]))
            if not node:
                node = KnowledgePoint(id=UUID(record["id"]), code=record["code"], name=record["name"],
                    subject="考研数学" if record["subject"] == "数学二" else "408",
                    is_active=True, is_assessable=True, is_reference_only=False)
                db.add(node); db.flush(); db.add(KpState(kp_id=node.id))
            spec = resolve_family(node.code)
            assert spec and spec.family_id == record["expected_family"]
            subject_targets[record["subject"]].append(GenerationTarget(
                kp_id=node.id, count=1, question_type="single_choice"))
            if resolve_family(node.code, "fill_blank"):
                subject_targets[record["subject"]].append(GenerationTarget(
                    kp_id=node.id, count=1, question_type="fill_blank"))
    assert any(row.kp_id == existing_integral_id for row in subject_targets["数学二"])

    class ForbiddenProvider:
        calls = 0
        def complete(self, *_args, **_kwargs):
            self.calls += 1
            raise AssertionError("deterministic mode must never call a provider")

    model = Model() if generation_mode == "ai_enhanced" else ForbiddenProvider()
    saved_by_subject = {subject: [] for subject in ("数学二", "408")}
    duplicate_rejections = {subject: 0 for subject in ("数学二", "408")}
    # Two deterministic rounds provide multiple parameter combinations per
    # registered family/type. Each simulated study day reserves only 19 calls;
    # each service request stays within the production batch size of five.
    for day_offset in range(2):
        stamp = NOW + timedelta(days=day_offset)
        for subject in ("数学二", "408"):
            for offset in range(0, len(subject_targets[subject]), 5):
                batch_key = uuid5(NAMESPACE_URL, f"TEST_FIXTURE C6 bank {generation_mode} {day_offset} {subject} {offset}")
                result = run_generation(factory, PersonalGenerationRequest(request_key=batch_key, surface="study",
                    generation_mode=generation_mode,
                    targets=subject_targets[subject][offset:offset + 5]), model, now=stamp)
                unexpected_failures = [failure for failure in result["failures"]
                    if failure.get("reason") != "duplicate"]
                assert not unexpected_failures, json.dumps({"day_offset": day_offset, "subject": subject,
                    "offset": offset, "failures": unexpected_failures}, ensure_ascii=False)
                duplicate_rejections[subject] += len(result["failures"])
                assert len(result["question_ids"]) + len(result["failures"]) == len(
                    subject_targets[subject][offset:offset + 5]), result
                saved_by_subject[subject].extend((raw_id, stamp) for raw_id in result["question_ids"])
                assert not result.get("numbers") and not result.get("append_error")
                for raw_id in result["question_ids"]:
                    assert append_personal(factory, question_ids=[UUID(raw_id)], now=stamp)["added"] == 1

    expected_requests = {subject: len(targets) * 2 for subject, targets in subject_targets.items()}
    for subject in ("数学二", "408"):
        assert len(saved_by_subject[subject]) + duplicate_rejections[subject] == expected_requests[subject]
    assert model.calls == (38 if generation_mode == "ai_enhanced" else 0)
    for subject, question_rows in saved_by_subject.items():
        for raw_id, stamp in question_rows:
            selected_id = UUID(raw_id)
            with factory.begin() as db:
                question = db.get(Question, selected_id)
                item = db.scalar(select(PracticeItem).where(PracticeItem.question_id == selected_id))
                state = db.get(KpState, question.kp_id)
                before_window = list(state.evidence_window or [])
                assert question.bank_scope == "personal" and item is not None
                assert question.grading_config["generation"]["prompt_version"] == (
                    "question-generation-c6-v1" if generation_mode == "ai_enhanced"
                    else "deterministic-problem-spec-v1")
                assert question.grading_config["generation"]["generation_mode"] == generation_mode
                assert question.grading_config["generation"]["family_registry_version"] == "personal-question-family-registry-v3"
                assert item.completed_at is None
                answer_kwargs = ({"selected_option": question.correct_answer, "raw_answer": None}
                    if question.question_type == "single_choice" else
                    {"selected_option": None, "raw_answer": question.correct_answer})
                key = f"TEST_FIXTURE C5 {subject} {question.id}"
                verdict = submit_answer(db, item_id=item.id, **answer_kwargs,
                    idempotency_key=key, now=stamp)
                assert verdict.result == "right", (subject, question.question_type, verdict)
                attempt = db.scalar(select(QuestionAttempt).where(QuestionAttempt.idempotency_key == key))
                assert attempt and attempt.grading_evidence["bank_scope"] == "personal"
                assert attempt.grading_evidence["evidence_capability"] == "personal_practice_only"
                assert state.evidence_window == before_window and state.mastered_at is None
    with factory() as db:
        batches = list(db.scalars(select(PersonalGenerationBatch)))
        calls_by_day = {day:sum(row.reserved_calls for row in batches if row.study_date == day)
            for day in {row.study_date for row in batches}}
        assert len(calls_by_day) == 2
        if generation_mode == "ai_enhanced":
            assert all(0 < calls <= 30 for calls in calls_by_day.values())
        else:
            assert all(calls == 0 for calls in calls_by_day.values())
        personal_questions = list(db.scalars(select(Question).where(Question.bank_scope == "personal")))
        expected_saved = sum(len(rows) for rows in saved_by_subject.values())
        assert len(personal_questions) == bank_rows(db, scope="personal")["total"] == expected_saved
        assert bank_rows(db, scope="public")["total"] == 0
        assert db.scalar(select(func.count()).select_from(QuestionAttempt)) == expected_saved
        from backend.services.golden_learning_slice import digest
        variants = {}
        parameter_variants = {}
        for question in personal_questions:
            generation = question.grading_config["generation"]
            spec = generation["problem_spec"]
            key = (spec["knowledge_node_code"], question.question_type)
            variants.setdefault(key, []).append(digest({"parameters":spec["parameters"],"options":question.options}))
            parameter_variants.setdefault(key, []).append(digest(spec["parameters"]))
        assert len(variants) == 19
        assert all(signatures and len(set(signatures)) == len(signatures) for signatures in variants.values())
        for (node_code, _question_type), signatures in parameter_variants.items():
            family = next(row["expected_family"] for row in fixture["nodes"] if row["code"] == node_code)
            if family != "improper_integral_parameter" and len(signatures) > 1:
                assert len(set(signatures)) == len(signatures)


def test_agent_reads_personal_inventory_without_invoking_generation(bank):
    from backend.services.learning_task_tools import TaskTools
    f,kp=bank;m=Model();r=run_generation(f,body(kp,1,surface='chat'),m,now=NOW)
    tools=TaskTools(f,budget_minutes=30,now=NOW,goal='帮我练习定积分')
    tools.nodes.add(kp)
    out=tools.execute('find_questions',{'kp_ids':[str(kp)]})
    assert len(out['questions'])==1,out
    assert out['questions'][0]['question_trust']['bank_scope']=='personal'
    assert out['questions'][0]['question_trust']['evidence_capability']=='personal_practice_only'
    assert m.calls==1


def test_independent_math_rejection_is_reported_as_retryable_quality_failure(bank):
    """A final version verifier rejection rolls back only the bad item and stays user-retryable."""
    f, _ = bank
    with f.begin() as db:
        node = KnowledgePoint(code="math.test.lhopital_generic", name="洛必达法则", subject="考研数学",
            is_active=True, is_assessable=True, is_reference_only=False)
        db.add(node); db.flush(); db.add(KpState(kp_id=node.id)); kp = node.id

    class IncorrectLimitAnswer:
        simulation = True
        calls = 0
        model = "TEST_FIXTURE independent-math-rejection"
        def complete(self, _messages, *, attempt=1):
            self.calls += 1
            return json.dumps({
                "stem": r"求极限 \(\displaystyle\lim_{x\to 1}\frac{x^3-3x^2+3x-1}{x^2-2x+1}\)，下面正确的是（ ）",
                "question_type": "single_choice",
                "options": {"A": r"\(0\)", "B": r"\(\frac{3}{2}\)", "C": r"\(\frac{1}{2}\)", "D": r"\(1\)"},
                "correct_answer": "B",
                "explanation": "TEST_FIXTURE 错误答案，不能通过独立数学校验。",
                "final_value": "3/2", "steps": [],
            }, ensure_ascii=False), {"prompt_tokens": 100, "completion_tokens": 100, "total_tokens": 200}

    request = PersonalGenerationRequest(request_key=uuid4(), surface="study", generation_mode="ai_generated",
        targets=[GenerationTarget(kp_id=kp, count=1, question_type="single_choice")])
    provider = IncorrectLimitAnswer()
    result = run_generation(f, request, provider, now=NOW)
    assert provider.calls == 1
    assert result["status"] == "failed" and result["question_ids"] == []
    assert result["failure_stage"] == "math_verification" and result["failure_type"] == "ValueError"
    assert result["failures"][0]["reason"] == "CONFIRMED_WRONG"
    assert result["diagnostics"][0]["code"] == "personal_generation_answer_conflict"
    assert "未保存" in result["diagnostics"][0]["message"]
    with f() as db:
        batch = db.scalar(select(PersonalGenerationBatch).where(
            PersonalGenerationBatch.request_key == str(request.request_key)))
        assert batch and batch.status == "failed"
        assert batch.result["question_ids"] == []
        assert db.scalar(select(func.count()).select_from(Question).where(
            Question.bank_scope == "personal")) == 0


def test_real_lhopital_node_uses_registered_verified_limit_family():
    from backend.services.personal_question_families import resolve_family
    family = resolve_family("math.calculus.limit.lhopital", "single_choice")
    assert family is not None and family.family_id == "exp_limit"


def test_explicit_unsupported_lhopital_formula_is_rejected_before_model_or_batch(test_database_url):
    from backend.errors import AppError
    with isolated_factory(test_database_url) as (factory, _):
        with factory.begin() as db:
            node = KnowledgePoint(code="math.calculus.limit.lhopital", name="洛必达法则",
                subject="考研数学", is_active=True, is_assessable=True, is_reference_only=False)
            db.add(node); db.flush(); db.add(KpState(kp_id=node.id)); kp = node.id
        class NeverCalledProvider:
            calls = 0
            def complete(self, *_args, **_kwargs):
                self.calls += 1
                raise AssertionError("unsupported explicit formula must be rejected before model invocation")
        provider = NeverCalledProvider()
        request = PersonalGenerationRequest(request_key=uuid4(), surface="study", generation_mode="ai_generated",
            user_requirement="给我生成一道洛必达法则的单选题：求 x 趋于正无穷时 (5x²−3x+1)/(2x²+x−4) 的极限。",
            targets=[GenerationTarget(kp_id=kp, count=1, question_type="single_choice")])
        with factory() as db:
            personal_before = db.scalar(select(func.count()).select_from(Question).where(Question.bank_scope == "personal"))
        with pytest.raises(AppError) as raised:
            run_generation(factory, request, provider, now=NOW)
        assert raised.value.code == "personal_generation_requirement_unsupported"
        assert provider.calls == 0
        with factory() as db:
            assert db.scalar(select(PersonalGenerationBatch).where(
                PersonalGenerationBatch.request_key == str(request.request_key))) is None
            assert db.scalar(select(func.count()).select_from(Question).where(
                Question.bank_scope == "personal")) == personal_before


def test_verified_lhopital_answer_with_unverified_explanation_steps_is_saved_as_personal_reference(bank):
    f, _ = bank
    with f.begin() as db:
        node=KnowledgePoint(code="math.calculus.limit.lhopital",name="洛必达法则",subject="考研数学",
            is_active=True,is_assessable=True,is_reference_only=False)
        db.add(node);db.flush();db.add(KpState(kp_id=node.id));kp=node.id

    class ReferenceExplanationProvider:
        simulation=True
        model="TEST_FIXTURE verified-answer-reference-explanation"
        def complete(self,_messages,*,attempt=1):
            data={"stem":r"计算极限：\lim_{x\to 0}\frac{e^{2x}-1-2x}{x^2} 的值是（ ）。",
                "question_type":"single_choice","options":{"A":"1","B":"2","C":"3","D":"4"},
                "correct_answer":"B","explanation":"当x趋近0时可连续使用洛必达法则，最终得到2。",
                "final_value":"2","steps":[{"expression":"对分子和分母连续求导并取极限","value":"2"}]}
            return json.dumps(data,ensure_ascii=False),{"prompt_tokens":100,"completion_tokens":100,"total_tokens":200}

    request=PersonalGenerationRequest(request_key=uuid4(),surface="study",generation_mode="ai_generated",
        targets=[GenerationTarget(kp_id=kp,count=1,question_type="single_choice")])
    result=run_generation(f,request,ReferenceExplanationProvider(),now=NOW)
    assert result["status"]=="completed" and len(result["question_ids"])==1,result
    assert result["reference_only_question_ids"]==result["question_ids"]
    assert result["answer_verified_explanation_reference_question_ids"] == result["question_ids"]
    assert result["answer_verification_events"][0]["status"] == "verified"
    assert "答案已通过独立计算核验" in result["message"]
    assert "解析仍有部分内容未能自动证明" in result["message"]
    with f() as db:
        q=db.get(Question,UUID(result["question_ids"][0]))
        assert q and q.bank_scope=="personal" and q.question_provenance=="ai_generated_practice"
        generation=q.grading_config["generation"]
        assert generation["independent_verification"]["status"]=="PASS"
        assert generation["answer_independently_verified"] is True
        assert generation["explanation_independently_verified"] is False
        assert generation["review_status"]=="ANSWER_VERIFIED_EXPLANATION_REFERENCE_ONLY"
        assert generation["verified_content_hash"]
        assert q.answer_verification_event_id is None  # machine proof is not a human attestation
        assert q.grading_config["math_verification"]["status"] == "verified"
        version=db.get(QuestionVersion,q.current_version_id)
        event=db.scalar(select(PersonalAnswerVerificationEvent).where(
            PersonalAnswerVerificationEvent.question_version_id==q.current_version_id))
        assert version and version.snapshot_json["grading_config"]["math_verification"]["status"]=="verified"
        assert event and event.status=="verified" and event.question_id==q.id
        assert event.question_snapshot_sha256==version.content_hash
        assert event.answer_sha256==answer_version_sha256(q)
        assert event.id==UUID(result["answer_verification_events"][0]["event_id"])
        assert question_eligibility(q,db.get(KnowledgePoint,q.kp_id)).practice_eligible


def test_independently_verified_personal_answer_updates_fsrs_only(bank):
    from backend.services.adaptive_schedule_projection import read_projection
    f, _ = bank
    with f.begin() as db:
        node = KnowledgePoint(code="math.calculus.limit.lhopital", name="洛必达法则",
            subject="考研数学", is_active=True, is_assessable=True, is_reference_only=False)
        db.add(node); db.flush(); db.add(KpState(kp_id=node.id)); kp = node.id

    class ReferenceExplanationProvider:
        simulation = True
        model = "TEST_FIXTURE verified-personal-answer-for-FSRS"
        def complete(self, _messages, *, attempt=1):
            data = {"stem": r"计算极限：\lim_{x\to 0}\frac{e^{2x}-1-2x}{x^2} 的值是（ ）。",
                "question_type": "single_choice", "options": {"A": "1", "B": "2", "C": "3", "D": "4"},
                "correct_answer": "B", "explanation": "当x趋近0时可连续使用洛必达法则，最终得到2。",
                "final_value": "2", "steps": [{"expression": "对分子和分母连续求导并取极限", "value": "2"}]}
            return json.dumps(data, ensure_ascii=False), {"prompt_tokens": 100, "completion_tokens": 100, "total_tokens": 200}

    request = PersonalGenerationRequest(request_key=uuid4(), surface="study", generation_mode="ai_generated",
        targets=[GenerationTarget(kp_id=kp, count=1, question_type="single_choice")])
    generated = run_generation(f, request, ReferenceExplanationProvider(), now=NOW)
    assert generated["status"] == "completed" and generated["reference_only_question_ids"] == generated["question_ids"]
    qid = UUID(generated["question_ids"][0])
    with f() as db:
        question = db.get(Question, qid)
        assert question and question.grading_config["generation"]["answer_independently_verified"] is True
        assert question.grading_config["math_verification"]["status"] == "verified"
        version_id = question.current_version_id
        original_state = db.get(KpState, kp)
        original_evidence = list(original_state.evidence_window)
        original_graduation_count = db.scalar(select(func.count()).select_from(KpGraduationQuestionSetVersion))

    appended = append_personal(f, question_ids=[qid], now=NOW)
    assert appended["added"] == 1
    item_id = UUID(appended["numbers"][0]["item_id"])
    with f.begin() as db:
        result = submit_answer(db, item_id=item_id, raw_answer=None, selected_option="B",
            idempotency_key="TEST_FIXTURE independently verified personal answer FSRS", now=NOW)
        assert result.result == "right"

    with f() as db:
        attempt = db.scalar(select(QuestionAttempt).where(QuestionAttempt.practice_item_id == item_id))
        assert attempt and attempt.question_version_id == version_id
        assert attempt.grading_evidence["personal_answer_independently_verified"] is True
        assert attempt.grading_evidence["evidence_capability"] == "personal_practice_only"
        schedule = read_projection(db, NOW, [kp])
        assert (str(qid), str(version_id)) in schedule.cards
        assert schedule.skills[str(kp)].right == 0
        assert schedule.skills[str(kp)].wrong == 0
        assert schedule.skills[str(kp)].unknown == 1
        state = db.get(KpState, kp)
        assert state.evidence_window == original_evidence
        assert db.scalar(select(func.count()).select_from(KpGraduationQuestionSetVersion)) == original_graduation_count


def test_auto_pass_personal_generation_persists_version_bound_answer_proof(bank):
    f, _ = bank
    with f.begin() as db:
        node = KnowledgePoint(code="math.exam.f4e5ed0360ea", name="行列式",
            subject="考研数学", is_active=True, is_assessable=True, is_reference_only=False)
        db.add(node); db.flush(); db.add(KpState(kp_id=node.id)); kp = node.id

    class VerifiedDeterminantProvider:
        simulation = True
        model = "TEST_FIXTURE auto-pass determinant answer proof"
        def complete(self, _messages, *, attempt=1):
            data = {"stem": "计算二阶行列式，其中第一行是7、-3，第二行是5、4。",
                "question_type": "single_choice", "options": {"A": "13", "B": "43", "C": "-43", "D": "-13"},
                "correct_answer": "B", "explanation": "按ad-bc计算：7×4-(-3)×5=43。",
                "final_value": "43", "steps": [{"expression": "7×4-(-3)×5", "value": "43"}]}
            return json.dumps(data, ensure_ascii=False), {"prompt_tokens": 100, "completion_tokens": 100, "total_tokens": 200}

    request = PersonalGenerationRequest(request_key=uuid4(), surface="study", generation_mode="ai_generated",
        targets=[GenerationTarget(kp_id=kp, count=1, question_type="single_choice")])
    result = run_generation(f, request, VerifiedDeterminantProvider(), now=NOW)
    assert result["status"] == "completed" and len(result["question_ids"]) == 1, result
    assert result["answer_verification_events"][0]["status"] == "verified"
    qid = UUID(result["question_ids"][0])
    with f() as db:
        question = db.get(Question, qid)
        assert question and question.bank_scope == "personal"
        generation = question.grading_config["generation"]
        assert generation["review_status"] == "AUTO_PASS"
        assert generation["answer_independently_verified"] is True
        assert question.grading_config["math_verification"]["status"] == "verified"
        version = db.get(QuestionVersion, question.current_version_id)
        event = db.scalar(select(PersonalAnswerVerificationEvent).where(
            PersonalAnswerVerificationEvent.question_version_id == question.current_version_id))
        assert version and event and event.status == "verified"
        assert event.question_snapshot_sha256 == version.content_hash
        assert event.answer_sha256 == answer_version_sha256(question)
        assert event.id == UUID(result["answer_verification_events"][0]["event_id"])
        assert question.answer_verification_event_id is None  # Machine proof is not human attestation.


def test_c4_lhopital_adaptation_with_unverified_steps_is_personal_reference_only(bank):
    f, _ = bank
    with f.begin() as db:
        node = KnowledgePoint(code="math.calculus.limit.lhopital", name="洛必达法则",
            subject="考研数学", is_active=True, is_assessable=True, is_reference_only=False)
        db.add(node); db.flush(); db.add(KpState(kp_id=node.id))
        parent = Question(kp_id=node.id, question_type="single_choice",
            stem=r"计算极限：\lim_{x\to 0}\frac{\sin x}{x}，选择正确结果。",
            options={"A": "1", "B": "0", "C": "2", "D": "不存在"},
            correct_answer="A", explanation="TEST_FIXTURE public reference",
            difficulty="basic", skill_tags=[node.name], estimated_minutes=5)
        db.add(parent); db.flush(); kp, parent_id = node.id, parent.id

    class C4ReferenceExplanationProvider:
        simulation = True
        model = "TEST_FIXTURE c4-verified-answer-reference-explanation"
        def complete(self, _messages, *, attempt=1):
            data = {"stem": r"计算极限：\lim_{x\to 0}\frac{e^{2x}-1-2x}{x^2} 的值是（ ）。",
                "question_type": "single_choice", "options": {"A": "1", "B": "2", "C": "3", "D": "4"},
                "correct_answer": "B", "explanation": "当x趋近0时可连续使用洛必达法则，最终得到2。",
                "final_value": "2", "steps": [{"expression": "对分子和分母连续求导并取极限", "value": "2"}]}
            return json.dumps(data, ensure_ascii=False), {"prompt_tokens": 100, "completion_tokens": 100, "total_tokens": 200}

    request = PersonalGenerationRequest(request_key=uuid4(), surface="study", generation_mode="ai_generated",
        reference_question_id=parent_id,
        targets=[GenerationTarget(kp_id=kp, count=1, question_type="single_choice")])
    result = run_generation(f, request, C4ReferenceExplanationProvider(), now=NOW)
    assert result["status"] == "completed" and len(result["question_ids"]) == 1, result
    assert result["reference_only_question_ids"] == result["question_ids"]
    with f() as db:
        question = db.get(Question, UUID(result["question_ids"][0]))
        assert question and question.bank_scope == "personal"
        assert question.question_provenance == "ai_generated_practice"
        assert question.grading_mode == "self_assessed"
        assert question.grading_config["verified"] is False
        generation = question.grading_config["generation"]
        assert generation["prompt_version"] == "question-generation-c4-v1"
        assert generation["review_status"] == "ANSWER_VERIFIED_EXPLANATION_REFERENCE_ONLY"
        assert generation["answer_independently_verified"] is True
        assert generation["explanation_independently_verified"] is False
        assert generation["parent_question_id"] == str(parent_id)
        eligibility = question_eligibility(question, db.get(KnowledgePoint, kp), teaching_enabled=True)
        assert eligibility.evidence_capability == "personal_practice_only"
        assert eligibility.verified_grading_method is None


def test_personal_scope_overrides_real_test_human_verification_event(bank):
    from tests.integration.test_learning_loop import mark_isolated_question_trusted
    f,kp=bank;r=run_generation(f,body(kp,1,surface='chat'),Model(),now=NOW)
    with f.begin() as db:
        q=db.get(Question,UUID(r['question_ids'][0]));q.grading_config={'verified':True,'method':'single_choice'}
        mark_isolated_question_trusted(q,db=db)
        eligibility=question_eligibility(q,db.get(KnowledgePoint,kp),teaching_enabled=True)
        assert eligibility.answer_verification_current
        assert eligibility.evidence_capability=='personal_practice_only' and eligibility.verified_grading_method is None


def test_personal_repeated_cross_day_right_and_wrong_never_make_strict_evidence(bank):
    from datetime import timedelta
    f,kp=bank;r=run_generation(f,body(kp,1,surface='chat'),Model(),now=NOW)
    qid=UUID(r['question_ids'][0])
    with f() as db:
        generated=db.get(Question,qid)
        correct=generated.correct_answer
        wrong=next(label for label in generated.options if label!=correct)
    for day,choice in enumerate([correct,correct,wrong]):
        stamp=NOW+timedelta(days=day)
        a=append_personal(f,question_ids=[qid],now=stamp)
        with f.begin() as db:
            item=db.scalar(select(PracticeItem).where(PracticeItem.plan_id==UUID(a['plan_id'])))
            result=submit_answer(db,item_id=item.id,raw_answer=None,selected_option=choice,
                idempotency_key=f'TEST_FIXTURE personal day {day}',now=stamp)
            assert result.result==('right' if choice==correct else 'wrong')
            state=db.get(KpState,kp)
            assert state.evidence_window==[] and state.pending_review_question_ids==[] and state.mastered_at is None
    with f() as db:
        attempts=list(db.scalars(select(QuestionAttempt).order_by(QuestionAttempt.submitted_at)))
        assert len(attempts)==3
        assert attempts[0].grading_evidence['sequence_category']=='first_independent_correct'
        assert attempts[1].grading_evidence['sequence_category']=='repeat_correct'
        assert attempts[2].grading_evidence['sequence_category']=='incorrect'
        assert all(e.evidence_level=='weak' for e in db.scalars(select(LearningEvent)))


def test_provider_failure_preserves_already_saved_questions_and_usage(bank):
    f,kp=bank;m=Model({2:'malformed'});r=run_generation(f,body(kp,3,surface='chat'),m,now=NOW)
    assert len(r['question_ids'])==2 and m.calls==3 and r['status']=='partial'
    assert len(r['calls'])==3 and r['calls'][1]['usage_observed']
    assert r['calls'][1]['usage']['total_tokens']==140
    assert r['failures'][0]['review_status']=='FORMAT_ERROR'
    assert run_generation(f,PersonalGenerationRequest.model_validate({**body(kp,1).model_dump(mode='json'),
        'request_key':str(uuid4())}),Model({1:'timeout'}),now=NOW)['question_ids']==[]
