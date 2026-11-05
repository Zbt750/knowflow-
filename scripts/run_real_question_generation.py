"""C2 authorized real calls, persistent eight-call ledger; offline replay never calls model."""
import argparse
from copy import deepcopy
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
from uuid import UUID
import hashlib
import json
import sys
from urllib.parse import urlsplit
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from pydantic import ValidationError
from sqlalchemy import select,text
from sqlalchemy.engine import make_url
from backend.config import get_settings
from backend.db import create_db_engine,create_session_factory
from backend.models.learning import Question,KnowledgePoint,KpMasteryPolicy
from backend.services.model_settings_service import load_local_settings
from backend.services.question_generation import Budget,generate,Output,assess_output,promote,configured_provider,PROMPT_VERSION,parse_generated_output,verify_explanation_step
from backend.services.question_verification_upgrade import snapshot
from backend.services.question_eligibility import question_eligibility
from backend.services.constant_expression import compare_constant_expressions,constant_expression
from backend.services.golden_learning_slice import digest
from backend.chat.call_trace import safe_failure_reason
from scripts.run_question_repair_pilot import isolated_factory,clone_inventory,business_check
from scripts.audit_question_quality import safe_output,json_input
from scripts.review_golden_slice import fingerprints

BASE=ROOT/"storage/quality-audits/phase45c2-20261008"
SOURCE=ROOT/"storage/quality-audits/phase45b3-20261008/frozen-inventory"
# C1 protocol remains fixed, constraints are separately versioned request data.
CASES=[
    ("A_math","completion","historic_fifth_derivative","e7d11002-551f-4ec5-8e2f-1a90d325bad5","math.exam.de439863790e","fill_blank"),
    ("B_tree","adapted","complete_tree","e4225412-c705-4439-97b0-593278e28da3","cs408.ds.topic.1efaf3d00b50","single_choice"),
    ("C_choice","adapted","historic_fifth_derivative","e7d11002-551f-4ec5-8e2f-1a90d325bad5","math.exam.de439863790e","single_choice"),
    ("D_math","original","power_integral",None,"math.exam.c431f98f817c","fill_blank"),
    ("A_cs","completion","signed_range","3caf2b53-4385-47a4-a5ee-48ddbe7b6011","cs408.co.topic.324b03e7b481","single_choice"),
    ("B_math","adapted","power_derivative","e7d11002-551f-4ec5-8e2f-1a90d325bad5","math.exam.de439863790e","single_choice"),
    ("C_integral","adapted","historic_rational_integral","1dbf2099-3c75-47d3-830f-aa585d7db9fb","math.exam.c431f98f817c","single_choice"),
    ("D_cs","original","binary_float",None,"cs408.co.topic.89cfd05c8418","single_choice"),
]
GUIDES={
 "complete_tree":"改变为一棵有N个结点的完全二叉树求叶结点数，N为5到100间整数。题干使用：一棵有N个结点的完全二叉树，其叶结点数为多少？替换N。不要改成树高或泛化证明。",
 "power_integral":"生成幂函数定积分基础题。题干使用：计算 ∫_0^b x^n dx。b和n都取1到5整数，以实际数字替换。使用清楚的参考解析。",
 "power_derivative":"同求导节点的基础变式，不保留父题高阶难度。题干使用：求函数 f(x)=x^n 在 x=t 处的导数。n为2到5、t为1到5，以实际数字替换。",
 "binary_float":"题干使用：下列数中不能由 IEEE754 二进制浮点格式精确表示的是？给四个互不等价的简单十进制数，其中只有一个不能精确表示，另三个应在单精度精度范围内精确表示。",
 "historic_fifth_derivative":"根据父题独立求值。补全必须原样保留stem和题型，options为null；改单选保持数学题意，给四个非等价常数选项。不要修改函数或求值点。",
 "signed_range":"原样保留父题stem和全部options，独立求出正确选项。final_value写正确选项的完整值，不写字母。",
 "historic_rational_integral":"保持父题原积分的数学条件与积分范围，把无选项题改成单选题；四个常数结果选项，必须唯一正确。不因缺答案改变原条件。",
}


def save(path,data):
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2,default=str),encoding="utf-8")


def live_read():
    settings=load_local_settings(get_settings())
    if settings.llm_model!="deepseek-flash" or settings.llm_base_url!="https://api.deepseek.com" or settings.teaching_practice_enabled:
        raise ValueError("Authorized endpoint/model/production flag changed")
    engine=create_db_engine(str(settings.active_database_url))
    try:
        with create_session_factory(engine)() as db:
            db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")); fp=fingerprints(db)
            nodes={n.code:n for n in db.scalars(select(KnowledgePoint))}
            parents={qid:db.get(Question,UUID(qid)) for _,_,_,qid,_,_ in CASES if qid}
            for p in parents.values():
                if not p or not p.is_active:raise ValueError("Missing/inactive parent")
            db.expunge_all()  # Preserve loaded read-only scalars across rollback.
            db.rollback()
    finally:engine.dispose()
    return settings,fp,nodes,parents


class CapturingProvider:
    """Observe the existing Provider, storing only allowed content/usage, no headers."""
    simulation=False
    def __init__(self,provider,ledger,root,case_id,prompt_version=PROMPT_VERSION):
        self.provider=provider;self.model=provider.model;self.max_tokens=provider.max_tokens
        self.ledger,self.root,self.case_id=ledger,root,case_id;self.last=None;self.prompt_version=prompt_version
    def complete(self,messages,*,attempt=1):
        if len(self.ledger["calls"])>=8 or self.ledger.get("stopped"):raise ValueError("Authorization calls exhausted/stopped")
        size=sum(len(m["content"].encode("utf-8")) for m in messages)
        reserve=size+512+3000; worst=(size+512)*2/1e6+3000*8/1e6
        if size>8000 or sum(c["reserved_tokens"] for c in self.ledger["calls"])+reserve>100000 or sum(c["reserved_peak_cny"] for c in self.ledger["calls"])+worst>1:
            self.ledger["stopped"]=True;save(self.root/"ledger.json",self.ledger);raise ValueError("Authorization budget exceeded")
        number=len(self.ledger["calls"])+1
        row={"number":number,"case_id":self.case_id,"status":"reserved","prompt_version":self.prompt_version,
             "messages":messages,"input_bytes":size,"reserved_tokens":reserve,"reserved_peak_cny":worst,
             "usage":None,"response":None,"model":self.model,"provider":"DeepSeek official",
             "timestamp":datetime.now(timezone.utc).isoformat()}
        row["model_request_options"]=self.provider._request_options() if callable(getattr(self.provider,"_request_options",None)) else {}
        self.ledger["calls"].append(row);save(self.root/"ledger.json",self.ledger)
        import backend.chat.service as service
        original=service.observe_payload
        def capture(payload):
            original(payload)
            choices=payload.get("choices",[])
            row["usage"]=deepcopy(payload.get("usage"))
            row["response"]={"model":payload.get("model"),"id":payload.get("id"),
                "content":choices[0].get("message",{}).get("content") if choices else None,
                "finish_reason":choices[0].get("finish_reason") if choices else None}
        service.observe_payload=capture
        started=__import__("time").perf_counter()
        try:
            result=self.provider.complete(messages,attempt=1)
            row["status"]="returned";return result
        except Exception as exc:
            row.update(status="provider_failed",error_code=getattr(exc,"code",type(exc).__name__),safe_reason=safe_failure_reason(getattr(exc,"detail",None)))
            raise
        finally:
            service.observe_payload=original
            row["elapsed_ms"]=round((__import__("time").perf_counter()-started)*1000,3)
            usages=[r["usage"] for r in self.ledger["calls"] if isinstance(r.get("usage"),dict)]
            if (row.get("usage",{}) or {}).get("completion_tokens",0)>3000 or sum(u.get("completion_tokens",0) for u in usages)>24000 or sum(u.get("total_tokens",0) for u in usages)>100000 or sum((u.get("prompt_tokens",0)*2+u.get("completion_tokens",0)*8)/1e6 for u in usages)>1:
                self.ledger["stopped"]=True;row["risk_stop"]="returned_usage_exceeds_authorized_limits"
            self.last=row;save(self.root/f"call-{number:02d}.json",row);save(self.root/"ledger.json",self.ledger)


def classify(candidate):
    errors=candidate["errors"]; ind=candidate["record"]["independent_verification"]
    if any(e in errors for e in ("completion_changed_original_content","false_authority_claim","generated_statement_outside_requested_skill","explanation_final_value_conflict","explanation_numeric_claim_conflict","requested_type_not_followed")) or ind["status"]=="FAIL":return "MODEL_CONTENT_ERROR"
    if "explanation_step_unverified_or_false" in errors:
        steps=candidate["output"]["steps"]
        if any(verify_explanation_step(s.get("expression"),s.get("value"))=="wrong" for s in steps):return "MODEL_CONTENT_ERROR"
        return "VERIFIER_UNSUPPORTED"
    if any("figure" in e or "stem_missing" in e for e in errors):return "SOURCE_INCOMPLETE"
    if ind["status"] in {"NOT_APPLICABLE","UNKNOWN","ERROR"} or "family_node_mapping_not_supported" in errors:return "VERIFIER_UNSUPPORTED"
    if errors or candidate["status"]!="AUTO_PASS":return "EVIDENCE_INSUFFICIENT"
    return "AUTO_PASS"


def initial_call_category(case,call):
    """Give a truncated response its observed format failure, not a provider failure label."""
    if call.get("safe_reason")=="output_limit" or call.get("error_code")=="answer_truncated":
        return "MODEL_FORMAT_ERROR"
    return case.get("category","PROVIDER_ERROR")


def generate_stage(root,count,prompt_version=PROMPT_VERSION,retry_output_limit=False):
    root=root.resolve()
    if root!=BASE.resolve():raise ValueError("Fixed authorization directory required")
    settings,fp,nodes,parents=live_read()
    source=json_input(SOURCE/"report.json")
    if fp!=source["protection"]["after"]:raise ValueError("Development fingerprint changed")
    raw=json_input(SOURCE/"inventory-snapshot.json")
    if digest(raw)!=source["inventory_snapshot_sha256"]:raise ValueError("Frozen inventory mismatch")
    if not root.exists():
        # Verify isolation before any paid request. No network inside this scope.
        url=str(settings.test_database_url) if settings.test_database_url else make_url(str(settings.database_url)).set(database="kaoyan_test").render_as_string(hide_password=False)
        with isolated_factory(url) as (factory,schema):clone_inventory(factory,raw)
        root.mkdir(parents=True,exist_ok=False)
        ledger={"authorization":"Explicit user authorization in current C2 thread","max_calls":8,"max_cny":1,"max_tokens":100000,
            "max_output_per_call":3000,"price_source":"https://api-docs.deepseek.com/zh-cn/quick_start/pricing/",
            "peak_input_miss_per_million_cny":2,"peak_output_per_million_cny":8,"calls":[],"stopped":False,"before":fp}
        save(root/"ledger.json",ledger)
    ledger=json_input(root/"ledger.json")
    selected=None
    if retry_output_limit:
        last=ledger["calls"][-1] if ledger["calls"] else {}
        if not (ledger["stopped"] and last.get("safe_reason")=="output_limit" and len(ledger["calls"])<8
                and not last.get("risk_stop") and not last.get("case_id","").endswith("_retry1")):
            raise ValueError("Only one recorded output-limit retry within original authorization is permitted")
        base=next(c for c in CASES if c[0]==last["case_id"])
        selected=[(base[0]+"_retry1",*base[1:])]
        ledger["stopped"]=False;ledger["retry_basis"]="original authorization: one failed request retry; counted in eight total"
        save(root/"ledger.json",ledger)
    if ledger["stopped"] or ledger["before"]!=fp:raise ValueError("Authorization session stopped or data drift")
    completed={r["case_id"] for r in ledger["calls"]}
    budget=Budget(max_calls=8,max_reserved_tokens=100000,max_output_tokens=3000,
        calls=len(ledger["calls"]),reserved_tokens=sum(r["reserved_tokens"] for r in ledger["calls"]))
    provider=configured_provider(settings,budget,real_call_authorized=True)
    if retry_output_limit:
        provider._request_options=lambda **kwargs:{"thinking":{"type":"disabled"}}
    for case_id,mode,family,qid,code,qt in (selected or [c for c in CASES if c[0] not in completed])[:count]:
        node=nodes[code];parent=parents.get(qid)
        request={"case_id":case_id,"mode":mode,"family":family,"question_type":qt,"knowledge_point":node.name,
            "subject":node.subject,"difficulty":"basic","constraints":GUIDES[family],
            "protocol":"stem为纯文本或原样父题，单选correct_answer为选项字母，final_value为该选项实际值；无选项options=null。steps只放可精确核对的常数算式，符号推导写explanation；可用steps=[]，不要自称验证通过。"}
        if parent:request["parent"]={"stem":parent.stem,"options":parent.options,"question_type":parent.question_type}
        case={"case_id":case_id,"mode":mode,"family":family,"kp_code":code,"parent_id":qid,
            "parent_snapshot_sha256":digest(snapshot(parent)) if parent else None,"request_sha256":digest(request),"prompt_version":prompt_version,"request_version":"c2-request-spec-v1"}
        capture=CapturingProvider(provider,ledger,root,case_id,prompt_version=prompt_version)
        try:
            out,trace=generate(capture,request,budget,max_retries=0,prompt_version=prompt_version)
            c=assess_output(out,node,request_id="C2_REAL-"+case_id,mode=mode,family=family,parent=parent,trace=trace)
            if out.question_type!=qt:
                c["status"]="REJECTED";c["errors"].append("requested_type_not_followed")
            case.update(category=classify(c),candidate={k:v for k,v in c.items() if k!="question"})
        except (json.JSONDecodeError,ValidationError) as exc:
            case.update(category="MODEL_FORMAT_ERROR",error_type=type(exc).__name__)
            # Preserve failure, continue a different case without an implicit retry.
            budget.stopped=False
        except Exception as exc:
            truncated=capture.last and capture.last.get("safe_reason")=="output_limit"
            case.update(category="MODEL_FORMAT_ERROR" if truncated else "BUDGET_STOPPED" if isinstance(exc,ValueError) else "PROVIDER_ERROR",
                failure_detail="output_limit_truncated_json" if truncated else None,
                error_type=type(exc).__name__,error_code=getattr(exc,"code",None))
            ledger["stopped"]=True
        save(root/(case_id+".json"),case);save(root/"ledger.json",ledger)
        print(json.dumps({"call":len(ledger["calls"]),"case":case_id,"category":case["category"],"candidate_status":case.get("candidate",{}).get("status")},ensure_ascii=False),flush=True)
        if ledger["stopped"]:break
    _,after,_,_=live_read()
    if after!=fp:raise ValueError("Development data drift after real calls")
    save(root/"generation-protection.json",{"before":fp,"after":after,"equal":True})


def offline_stage(root):
    ledger=json_input(root/"ledger.json");settings,fp,nodes,parents=live_read()
    if fp!=ledger["before"]:raise ValueError("Development data drift")
    cases=[json_input(root/(c["case_id"]+".json")) for c in ledger["calls"] if (root/(c["case_id"]+".json")).exists()]
    raw=json_input(SOURCE/"inventory-snapshot.json"); promoted=[]; analyzed=[]; previous=get_settings().teaching_practice_enabled
    url=str(settings.test_database_url) if settings.test_database_url else make_url(str(settings.database_url)).set(database="kaoyan_test").render_as_string(hide_password=False)
    output=root/("offline-"+datetime.now(timezone.utc).strftime("%H%M%S"))
    output=safe_output(output);output.mkdir(parents=True,exist_ok=False)
    try:
        with isolated_factory(url) as (factory,schema):
            clone_inventory(factory,raw);get_settings().teaching_practice_enabled=True
            with factory() as db:
                before_policy=[{c.name:str(getattr(p,c.name)) for c in KpMasteryPolicy.__table__.columns} for p in db.scalars(select(KpMasteryPolicy).order_by(KpMasteryPolicy.kp_id))]
            for case in cases:
                call=next(r for r in ledger["calls"] if r["case_id"]==case["case_id"])
                raw_content=(call.get("response") or {}).get("content")
                try:out,transforms=parse_generated_output(raw_content,compatibility=True)
                except Exception as exc:
                    analyzed.append({**case,"initial_category":initial_call_category(case,call),
                        "current_category":"MODEL_FORMAT_ERROR","offline_error_type":type(exc).__name__});continue
                with factory.begin() as db:
                    parent=db.get(Question,UUID(case["parent_id"])) if case["parent_id"] else None
                    node=db.scalar(select(KnowledgePoint).where(KnowledgePoint.code==case["kp_code"]))
                    trace=case.get("candidate",{}).get("trace") or {"model":"deepseek-flash","mode":"real_model","prompt_version":case["prompt_version"]}
                    c=assess_output(out,node,request_id="C2_REAL-"+case["case_id"],mode=case["mode"],family=case["family"],parent=parent,trace=trace)
                    updated={**case,"initial_category":initial_call_category(case,call),"current_category":classify(c),
                        "format_transformations":transforms,"reassessment":{k:v for k,v in c.items() if k!="question"}}
                    if c["status"]=="AUTO_PASS":
                        q,state=promote(db,c,node);assert promote(db,c,node)[1]=="NOOP"
                        promoted.append(str(q.id));updated["isolated_promotion"]=state
                    analyzed.append(updated)
            business=business_check(factory,promoted,None)
            with factory() as db:
                assert before_policy==[{c.name:str(getattr(p,c.name)) for c in KpMasteryPolicy.__table__.columns} for p in db.scalars(select(KpMasteryPolicy).order_by(KpMasteryPolicy.kp_id))]
                off=sum(question_eligibility(q,db.get(KnowledgePoint,q.kp_id),teaching_enabled=False).practice_eligible for q in db.scalars(select(Question)))
                on=sum(question_eligibility(q,db.get(KnowledgePoint,q.kp_id),teaching_enabled=True).practice_eligible for q in db.scalars(select(Question)))
                assert all(question_eligibility(q,db.get(KnowledgePoint,q.kp_id),teaching_enabled=True).evidence_capability!="verified_objective" for q in db.scalars(select(Question)))
        get_settings().teaching_practice_enabled=False
        _,after,_,_=live_read()
        if fp!=after:raise ValueError("Development fingerprint drift")
        usage=[r["usage"] for r in ledger["calls"] if r.get("usage")]
        totals={k:sum(u.get(k,0) for u in usage) for k in ("prompt_tokens","completion_tokens","total_tokens","prompt_cache_hit_tokens","prompt_cache_miss_tokens")}
        idle_cny=(totals["prompt_cache_miss_tokens"]*1+totals["prompt_cache_hit_tokens"]*0.02+totals["completion_tokens"]*4)/1_000_000
        peak_cny=(totals["prompt_cache_miss_tokens"]*2+totals["prompt_cache_hit_tokens"]*0.04+totals["completion_tokens"]*8)/1_000_000
        corrected_initial={c["case_id"]:initial_call_category(
            json_input(root/(c["case_id"]+".json")),c) for c in ledger["calls"]
            if (root/(c["case_id"]+".json")).exists()}
        call_summary=[{k:r.get(k) for k in ("number","case_id","status","prompt_version","model_request_options","input_bytes","reserved_tokens","usage","elapsed_ms","error_code","safe_reason","risk_stop")} for r in ledger["calls"]]
        report={"status":"PHASE45C2_REAL_MODEL_PILOT_BLOCKED" if ledger["stopped"] or not promoted else "PHASE45C2_REAL_MODEL_PILOT_COMPLETED",
            "actual_calls":len(ledger["calls"]),"usage":totals,"usage_complete":len(usage)==len(ledger["calls"]),
            "cost_estimate_cny":{"idle_published_rate":idle_cny,"peak_published_rate_upper":peak_cny,"provider_invoice_observed":False},
            "calls":call_summary,
            "initial_categories":dict(Counter(corrected_initial.get(c["case_id"],c["category"]) for c in cases)),"current_categories":dict(Counter(c.get("current_category",c["category"]) for c in analyzed)),
            "cases":analyzed,"promoted_in_isolation":len(promoted),"isolated_flag_off":off,"isolated_flag_on":on,"business":business,
            "protection":{"before":fp,"after":after,"equal":True,"schema_removed":True,"development_written":False},
            "real_planner_calls":0,"prompt_versions":sorted({c["prompt_version"] for c in cases}),"all_models":"deepseek-flash"}
        save(output/"report.json",report);print(json.dumps({"output":str(output),"status":report["status"],"calls":report["actual_calls"],"promoted":len(promoted),"categories":report["current_categories"],"usage":totals},ensure_ascii=False))
    finally:get_settings().teaching_practice_enabled=previous


if __name__=="__main__":
    if hasattr(sys.stdout,"reconfigure"):sys.stdout.reconfigure(encoding="utf-8")
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--stage",choices=["generate","offline"],required=True)
    p.add_argument("--count",type=int,default=4);p.add_argument("--authorized-c2-calls",action="store_true")
    p.add_argument("--prompt-v2",action="store_true")
    p.add_argument("--retry-output-limit",action="store_true")
    args=p.parse_args()
    if args.stage=="generate":
        if not args.authorized_c2_calls or not 1<=args.count<=8:p.error("Explicit C2 authorization flag and 1..8 count required")
        generate_stage(BASE,args.count,"question-generation-c2-v2" if args.prompt_v2 else PROMPT_VERSION,args.retry_output_limit)
    else:offline_stage(BASE)
