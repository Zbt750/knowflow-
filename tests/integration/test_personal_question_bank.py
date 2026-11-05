"""No real provider or development data. Fixtures inside marked temporary schemas."""
from datetime import datetime, timezone, timedelta
from uuid import uuid4, UUID, uuid5, NAMESPACE_URL
from copy import deepcopy
import json
import pytest
from sqlalchemy import select, func, text
from backend.models.learning import KnowledgePoint, Question, QuestionVersion, DailyPlan, PracticeItem, KpState, LearningEvent, QuestionAttempt
from backend.models.personal_generation import PersonalGenerationBatch
from backend.schemas.personal_questions import PersonalGenerationRequest, GenerationTarget
from backend.services.personal_question_service import run_generation, append_personal, bank_rows, node_activity
from backend.services.question_eligibility import question_eligibility
from backend.services.answer_submission_service import submit_answer
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
                "question_versions", "question_auto_review_events",
                "question_answer_verification_events", "kp_graduation_question_set_versions",
                "personal_generation_batches",
            ]}).all()
            assert rows and len(rows) == 5
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
