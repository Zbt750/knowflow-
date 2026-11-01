"""Replay frozen D questions through isolated business APIs; never generate content."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
from uuid import UUID, uuid5, NAMESPACE_URL

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from backend.config import get_settings
from backend.db import create_db_engine, create_session_factory
from backend.models.learning import KnowledgePoint, KpMasteryPolicy, Question
from backend.services.question_eligibility import question_eligibility
from backend.services.question_generation import Output, assess_output, promote
from backend.services.question_attestation import question_content_sha256
from backend.services.golden_learning_slice import digest
from scripts.review_golden_slice import fingerprints
from scripts.run_question_repair_pilot import isolated_factory, clone_inventory, business_check
from scripts.audit_question_quality import safe_output

D_ROOT = ROOT / "storage/quality-audits/phase45d-20261009"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def live_audit():
    settings = get_settings()
    engine = create_db_engine(str(settings.active_database_url))
    try:
        with create_session_factory(engine)() as db:
            db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
            nodes = list(db.scalars(select(KnowledgePoint)))
            indexed = {n.id:n for n in nodes}
            policies = list(db.scalars(select(KpMasteryPolicy)))
            questions = list(db.scalars(select(Question)))
            off = [question_eligibility(q,indexed[q.kp_id],teaching_enabled=False) for q in questions if q.is_active]
            on = [question_eligibility(q,indexed[q.kp_id],teaching_enabled=True) for q in questions if q.is_active]
            strict = [q for q in questions if q.is_active and question_eligibility(q,indexed[q.kp_id],teaching_enabled=True).evidence_capability=="verified_objective"]
            result={"database":db.scalar(text("SELECT current_database()")),
                "revision":db.scalar(text("SELECT version_num FROM alembic_version")),
                "fingerprints":fingerprints(db),"nodes":len(nodes),
                "assessable_active_nodes":sum(n.is_active and n.is_assessable for n in nodes),
                "policy_count":len(policies),"policy_versions":dict(Counter(p.policy_version for p in policies)),
                "questions":len(questions),"active_questions":len(off),
                "practice_eligible_flag_off":sum(e.practice_eligible for e in off),
                "practice_eligible_flag_on":sum(e.practice_eligible for e in on),
                "strict_objective_questions":len(strict),
                "strict_questions_by_node":dict(Counter(indexed[q.kp_id].code for q in strict)),
                "teaching_flag":settings.teaching_practice_enabled,
                "multi_student_ownership_columns":{
                    table:[c.name for c in model.__table__.columns if c.name in {"user_id","student_id","owner_id"}]
                    for table,model in [("questions",Question)]},
                "policies":[{c.name:str(getattr(p,c.name)) for c in KpMasteryPolicy.__table__.columns} for p in policies]}
            db.rollback()
            return result
    finally:
        engine.dispose()


def rehydrate(factory, bank, report, diagnosis):
    """Revalidate saved text and rebuild its missing ORM metadata, not author new questions."""
    from backend.services.question_repair import local_pack_registry, identity_counts, restore_pack_binding
    registry,_=local_pack_registry(ROOT)
    plans={r["question_id"]:r for r in diagnosis["questions"]}
    for receipt in report["repair_receipts"]:
        with factory.begin() as db:
            q=db.get(Question,UUID(receipt["question_id"]))
            restore_pack_binding(db,q,db.get(KnowledgePoint,q.kp_id),plans[str(q.id)],registry,
                identity_counts(list(db.scalars(select(Question)))))
    candidates={r["candidate_id"]:r for r in report["candidates"]}
    for row in bank["questions"]:
        if not row["generation_version"]:
            continue
        metadata=candidates[row["question_id"]]
        family=row["generation_family"]
        requests=[f"phase45d-v3:{row['node_code']}:{family}:{ordinal}" for ordinal in range(64)]
        request_id=next((r for r in requests if str(uuid5(NAMESPACE_URL,"generated-candidate:"+r))==row["question_id"]),None)
        if request_id is None:
            raise ValueError("Frozen candidate request identity unavailable")
        with factory.begin() as db:
            node=db.scalar(select(KnowledgePoint).where(KnowledgePoint.code==row["node_code"]))
            parent=db.get(Question,UUID(row["parent_question_id"])) if row["parent_question_id"] else None
            value=(row["options"][row["correct_answer"]] if row["question_type"]=="single_choice" else row["correct_answer"])
            output=Output(**{k:row[k] for k in ("stem","options","question_type","correct_answer","explanation")},final_value=value)
            candidate=assess_output(output,node,request_id=request_id,mode=metadata["mode"],family=family,parent=parent,
                trace={"mode":"codex_assisted","model":"Codex-assisted deterministic content registry; no external model",
                    "prompt_version":"phase45d-codex-assisted-v3","model_calls":0},skill_tags=row["skill_tags"])
            if candidate["status"]!="AUTO_PASS" or candidate["generation_hash"]!=metadata["generation_hash"]:
                raise ValueError("Frozen generation binding drift: "+row["question_id"])
            q,_=promote(db,candidate,node)
            if question_content_sha256(q)!=row["content_sha256"]:
                raise ValueError("Frozen content hash drift")
    with factory() as db:
        for row in bank["questions"]:
            q=db.get(Question,UUID(row["question_id"]))
            if q is None or question_content_sha256(q)!=row["content_sha256"]:
                raise ValueError("Rehydrated bank content differs")
            e=question_eligibility(q,db.get(KnowledgePoint,q.kp_id),teaching_enabled=True)
            if not e.practice_eligible or e.evidence_capability=="verified_objective":
                raise ValueError("Frozen ordinary-practice eligibility differs")


def run(args):
    baseline_dir=args.output_dir.resolve()
    output=safe_output(baseline_dir if args.baseline_only else baseline_dir/"replay")
    bank_path=D_ROOT/"foundation-pilot-v5/bank-candidates.json"
    report_path=D_ROOT/"foundation-pilot-v5/report.json"
    sources={str(p.relative_to(ROOT)):sha(p) for p in (bank_path,report_path,D_ROOT/"diagnosis/inventory-snapshot.json")}
    if args.baseline_only:
        output.mkdir(parents=True,exist_ok=False)
        live = None if args.offline_baseline else live_audit()
        result={"created_at":datetime.now(timezone.utc).isoformat(),"live":live,"source_hashes":sources,
            "live_status":"BLOCKED_POSTGRES_STOPPED" if live is None else "VERIFIED_READ_ONLY"}
        (output/"before.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
        print(json.dumps({k:v for k,v in live.items() if k not in {"fingerprints","policies"}},ensure_ascii=False) if live else result["live_status"])
        return
    before=load(baseline_dir/"before.json")
    if before["source_hashes"]!=sources:
        raise ValueError("D artifacts changed since baseline")
    bank,report=load(bank_path),load(report_path)
    raw=load(D_ROOT/"diagnosis/inventory-snapshot.json")
    diagnosis=load(D_ROOT/"diagnosis/report.json")
    if len(bank["questions"])!=108 or digest(raw)!=bank["created_from_live_snapshot_sha256"]:
        raise ValueError("D dataset identity mismatch")
    settings=get_settings(); previous=settings.teaching_practice_enabled
    url=os.environ.get("PHASE45E_TEST_DATABASE_URL") or (str(settings.test_database_url) if settings.test_database_url else make_url(str(settings.database_url)).set(database="kaoyan_test").render_as_string(hide_password=False))
    result={"phase":"4.5E","model_calls":0,"new_question_content_generated":0,"formal_database_writes":0,"source_hashes":sources}
    output.mkdir(parents=True,exist_ok=False)
    try:
        with isolated_factory(url) as (factory,schema):
            result["isolated_schema"]=schema
            clone_inventory(factory,raw)
            settings.teaching_practice_enabled=True
            rehydrate(factory,bank,report,diagnosis)
            business=business_check(factory,[row["question_id"] for row in bank["questions"]],None)
            if len(business["cases"])!=108:
                raise ValueError("Not every frozen question was exercised")
            if any(case["progress"]!=case["agent_tool_progress"] for case in business["cases"]):
                raise ValueError("Knowledge and Agent progress disagree")
            result["ordinary_practice"]=business
            result["questions_reused"]=108
            result["status"]="PHASE45E_ISOLATED_PRACTICE_PASS"
    except Exception as exc:
        result.update(status="PHASE45E_BLOCKED",error_type=type(exc).__name__,error=str(exc))
        raise
    finally:
        settings.teaching_practice_enabled=previous
        after=live_audit() if before["live"] is not None else None
        result["protection"]={"before":before["live"]["fingerprints"] if before["live"] else None,"after":after["fingerprints"] if after else None,
            "equal":before["live"]["fingerprints"]==after["fingerprints"] if after else None,"live_status":before["live_status"],"source_artifacts_unchanged":sources=={
                str(p.relative_to(ROOT)):sha(p) for p in (bank_path,report_path,D_ROOT/"diagnosis/inventory-snapshot.json")},
            "feature_flag_restored":settings.teaching_practice_enabled==previous}
        (output/"acceptance.json").write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),encoding="utf-8")
    if result["protection"]["equal"] is False:
        raise ValueError("Development data changed during tests")
    print(json.dumps({"status":result["status"],"questions_reused":108,
        "api_cases":len(result["ordinary_practice"]["cases"]),"attempts":result["ordinary_practice"]["attempt_count"],
        "development_fingerprints_equal":result["protection"]["equal"],"model_calls":0},ensure_ascii=False))


if __name__=="__main__":
    if hasattr(sys.stdout,"reconfigure"):sys.stdout.reconfigure(encoding="utf-8")
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir",type=Path,required=True)
    parser.add_argument("--baseline-only",action="store_true")
    parser.add_argument("--offline-baseline",action="store_true",help="Explicitly record original DB as unavailable, never claim current row fingerprints")
    run(parser.parse_args())
