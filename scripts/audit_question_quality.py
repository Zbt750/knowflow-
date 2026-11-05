"""Version-bound, read-only shadow quality pilot; no paid model or apply mode."""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4, uuid5, NAMESPACE_URL
import hashlib
import json
import sys
import time
from copy import copy

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from sqlalchemy import select,text
from backend.config import get_settings
from backend.db import create_db_engine,create_session_factory
from backend.models.learning import Question,KnowledgePoint,QuestionAnswerConsistencyRun
from backend.services.golden_learning_slice import digest
from backend.services.question_pack import QuestionContent
from backend.services.question_production_pipeline import assess_question_quality,validate_question_content
from backend.services.question_quality import RULE_VERSION,duplicates,audit_teaching_question,TEACHING_RULE_VERSION
from backend.services.question_eligibility import question_eligibility
from backend.services.quality_sources import NativePageReader,material_descriptor,inspect_source
from backend.services.quality_verifiers import verify_problem
from scripts.review_golden_slice import fingerprints

PRIORITY_IDS=("d1691564-0c42-43c0-8ab2-b011fd88ac65","2aa85cd9-baed-493d-b79b-f3174f6016c0","ab961f2c-8e24-4068-9bfc-effc9ea876e9")


def json_input(path):
    if path.stat().st_size>16*1024*1024: raise ValueError("Input exceeds 16 MiB")
    return json.loads(path.read_text(encoding="utf-8"))


def rule_build_sha():
    paths=["backend/services/"+name+".py" for name in ("question_quality","quality_sources","quality_verifiers",
        "question_production_pipeline","question_attestation","answer_consistency","answer_grading","constant_expression","question_eligibility","question_pack","answer_submission_service")]
    paths.extend(["backend/config.py", "scripts/audit_question_quality.py"])
    import pypdf,sympy
    return digest({"files":{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths},
        "pypdf":pypdf.__version__,"sympy":sympy.__version__})


def select_pilot(rows,nodes,limit):
    selected={}
    def add(q):
        if q and len(selected)<limit: selected[str(q.id)]=q
    indexed={str(q.id):q for q in rows}
    for qid in PRIORITY_IDS: add(indexed.get(qid))
    pools=(
        [q for q in rows if validate_question_content(q).status=="INCOMPLETE"],
        [q for q in rows if verify_problem(q)["status"] in {"PASS","FAIL"}],
        [q for q in rows if q.answer_reliability=="ai_disagreement"],
        [q for q in rows if q.question_type in {"proof","subjective"}],
        [q for q in rows if q.question_provenance=="legacy_unknown"],
        [q for q in rows if question_eligibility(q,nodes.get(q.kp_id)).practice_eligible],
    )
    for pool in pools:
        for q in pool[:5]: add(q)
    for q in rows: add(q)
    return list(selected.values())


def registry_from_existing():
    package=ROOT/"storage/answer-trust/phase45a3-20261008/human-review-package.json"
    registry={}
    if package.is_file():
        for q in json_input(package).get("questions",[]):
            import re
            locator=q.get("original_page_locator","") or ""
            match=re.search(r"p\.(\d+)",locator)
            registry[q["question_id"]]={"path":q.get("declared_original_source_file"),
                "expected_sha256":q.get("declared_original_source_sha256"),
                "page":int(match.group(1)) if match else None,"question_number":q.get("question_number"),
                "locator_note":locator,"origin":"existing_local_review_locator_not_human_verification"}
    return registry


def add_q6_correction_observation(q,descriptor):
    path=ROOT/"storage/answer-trust/phase45a3-20261008/human-review-q6-corrected-v2.json"
    if str(q.id)!=PRIORITY_IDS[0] or not path.is_file(): return descriptor
    source=json_input(path)["source"]
    descriptor={**descriptor,"path":source["pdf_path"],"expected_sha256":source["pdf_sha256"],"page":source["page"],"question_number":6}
    # A fact from the prior explicit content correction, NOT the new/current
    # question snapshot copied back and labelled as original-paper evidence.
    revisions=(q.grading_config or {}).get("content_revisions",[])
    for rev in revisions:
        opts=rev.get("changes",{}).get("options")
        before=rev.get("before",{})
        if isinstance(opts,dict) and "C" in opts and isinstance(before.get("options"),dict):
            context={"stem":before["stem"],"question_type":before["question_type"],"kp_id":before["kp_id"],
                "options":{k:v for k,v in before["options"].items() if k!="C"}}
            descriptor["partial_observations"]=[{"field":"options.C","value":opts["C"],
                "context_sha256":digest(context),"revision_reason":rev.get("basis"),
                "scope":"previous approved correction only; other fields not certified"}]
    return descriptor


def candidate_rows(payload,nodes):
    indexed={n.code:n for n in nodes.values()}
    result=[]
    for raw in payload.get("questions",[]):
        content=QuestionContent.model_validate(raw["content"])
        node=indexed.get(content.kp_code)
        if node is None: raise ValueError("Candidate target node missing: "+content.kp_code)
        source=raw.get("source",{})
        input_kind=raw.get("input_kind","new_exam_candidate")
        if input_kind not in {"new_exam_candidate","ai_variant_candidate","ai_original_candidate"}:
            raise ValueError("Unknown candidate input kind")
        generated=input_kind.startswith("ai_")
        if generated and (source.get("source_type") in {"exam","mock"} or raw.get("proposed_origin")=="real_exam"):
            raise ValueError("AI candidate cannot claim real_exam/mock authenticity")
        # Candidate IDs are stable audit IDs, never claim a persisted Question.
        cid=uuid5(NAMESPACE_URL,"quality-candidate:"+content.source_id)
        q=Question(id=cid,kp_id=node.id,**content.model_dump(exclude={"kp_code","source_id","grading_method"}),
            grading_mode="self_assessed",grading_config={"verified":False,"method":None,
                "provenance":{"source":source,"content_status":"source_transcribed"}},
            is_active=True,question_provenance=raw.get("proposed_origin","ai_generated_practice" if generated else "legacy_unknown"),
            content_trust="unreviewed",source_status="unknown",answer_provenance="unknown",answer_reliability="unverified")
        result.append(q)
    if not result or len({str(q.id) for q in result})!=len(result): raise ValueError("Empty/duplicate candidate IDs")
    return result


def safe_output(path):
    resolved=path.resolve()
    if not any(resolved.is_relative_to(ROOT/f) for f in ("storage/quality-audits","eval/reports")):
        raise ValueError("Keep raw exams/quality reports in ignored private directories")
    if resolved.exists(): raise ValueError("Refuse to overwrite earlier audit/history")
    return resolved


def render(report):
    lines=["# 题目质量只读试点", "", f"规则：{report['rule_version']}；模式：shadow/dry-run；模型调用：0；业务写入：0。",
        "原卷文字可提取/文件可访问不等于原题逐字准确，独立验证只证明给定题面范围内的答案。", "",
        "## 统计", "", "```json",json.dumps(report["summary"],ensure_ascii=False,indent=2),"```", "",
        "## 逐题", "", "| ID | 题目来源 | 当前可练 | shadow结果 | 用途 | 人工风险候选 |", "|---|---|---|---|---|---|"]
    for r in report["questions"]:
        s=r["source_declaration"]
        lines.append(f"| {r['binding']['audit_subject_id']} | {s.get('subject','未知')} {s.get('year','未知')} Q{s.get('question_number','未知')} | {r['current_practice_eligible']} | {r['status']} | {', '.join(r['allowed_uses'])} | {r['manual_review_candidate']} |")
    for r in report["questions"]:
        lines += ["",f"### {r['binding']['audit_subject_id']}", "", f"题干：{r['stem']}",f"现存答案：{r['stored_answer']}",
            "| 阶段 | 结果 | 原因 |","|---|---|---|"]
        lines += [f"| {key} | {v['status']} | {v['reason']} |" for key,v in r["stages"].items()]
        lines += ["",f"当前资格原因：{', '.join(r['current_eligibility']['blocking_reasons']) or '现有资格已满足'}",
            "这是私有审核报告，不是题目激活、人工签核或学习确认。"]
    return "\n".join(lines)+"\n"


def run(args):
    args=copy(args)  # Replays must not mutate the caller's selection arguments.
    output=safe_output(args.output_dir)
    comparison = json_input(args.compare_report) if getattr(args,"compare_report",None) else None
    if comparison:
        ids=[r["binding"]["audit_subject_id"] for r in comparison["questions"]]
        if len(ids)!=30 or len(set(ids))!=30 or args.candidates or args.kp_code or args.question_id:
            raise ValueError("Comparison requires the unchanged exact 30-ID dataset, no alternative scope")
        args.question_id=ids
        if args.limit!=30: raise ValueError("Comparison limit must be exactly 30")
    registry=registry_from_existing()
    if args.source_manifest:
        registry.update(json_input(args.source_manifest).get("questions",{}))
    started=time.perf_counter()
    engine=create_db_engine(str(get_settings().active_database_url))
    reader=NativePageReader()
    build=rule_build_sha()
    try:
        with create_session_factory(engine)() as db:
            db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
            before=fingerprints(db)
            nodes={n.id:n for n in db.scalars(select(KnowledgePoint))}
            all_rows=list(db.scalars(select(Question).where(Question.is_active.is_(True)).order_by(Question.id)))
            rows=all_rows
            if args.kp_code:
                ids={n.id for n in nodes.values() if n.code in args.kp_code}
                if len(ids)!=len(set(args.kp_code)): raise ValueError("Unknown knowledge code")
                rows=[q for q in rows if q.kp_id in ids]
            if args.question_id:
                requested=set(args.question_id)
                rows=[q for q in rows if str(q.id) in requested]
                if len(rows)!=len(requested): raise ValueError("Unknown/inactive/out-of-scope Question ID")
                if len(rows)>args.limit: raise ValueError("Explicit IDs exceed limit; no silent omission")
            elif args.candidates:
                rows=candidate_rows(json_input(args.candidates),nodes)
                if len(rows)>args.limit: raise ValueError("Candidate count exceeds limit")
            else: rows=select_pilot(rows,nodes,args.limit)
            if not rows: raise ValueError("Empty audit scope")
            if comparison:
                by_id={str(q.id):q for q in rows}
                rows=[by_id[qid] for qid in ids]
            runs=list(db.scalars(select(QuestionAnswerConsistencyRun).where(
                QuestionAnswerConsistencyRun.question_id.in_([q.id for q in rows])).order_by(QuestionAnswerConsistencyRun.id)))
            duplicates_by_id=duplicates([*all_rows,*rows] if args.candidates else all_rows)
            results=[]
            for q in rows:
                question_start=time.perf_counter()
                descriptor=add_q6_correction_observation(q,material_descriptor(q,registry,args.source_root))
                source=inspect_source(q,descriptor,reader)
                row=assess_question_quality(q,nodes.get(q.kp_id),source_check=source,runs=runs,
                    duplicate=duplicates_by_id[str(q.id)],rule_version=args.rule_version,build_sha=build,candidate=bool(args.candidates))
                if comparison:
                    prior=next(r for r in comparison["questions"] if r["binding"]["audit_subject_id"]==str(q.id))
                    row["previous_rule_result"]={"status":prior["status"],"decision_sha256":prior["decision_sha256"],
                        "content_unchanged":prior["binding"]["question_content_sha256"]==row["binding"]["question_content_sha256"],
                        "answer_unchanged":prior["binding"]["answer_version_sha256"]==row["binding"]["answer_version_sha256"]}
                    row["teaching_quality"]=audit_teaching_question(q,nodes.get(q.kp_id),source_check=source,runs=runs,
                        duplicate=duplicates_by_id[str(q.id)],old_audit=row,build_sha=build)
                    row["enabled_runtime_eligibility"]=question_eligibility(q,nodes.get(q.kp_id),teaching_enabled=True).public_dict()
                row.update(stem=q.stem,stored_answer=q.correct_answer,source_declaration=(q.grading_config or {}).get("provenance",{}).get("source",{}),
                    checked_at=datetime.now(timezone.utc).isoformat(),elapsed_ms=round((time.perf_counter()-question_start)*1000,3))
                results.append(row)
            current_eligible=sum(question_eligibility(q,nodes.get(q.kp_id)).practice_eligible for q in all_rows)
            if comparison:
                baseline=[question_eligibility(q,nodes.get(q.kp_id),teaching_enabled=False) for q in all_rows]
                enabled=[question_eligibility(q,nodes.get(q.kp_id),teaching_enabled=True) for q in all_rows]
                if get_settings().teaching_practice_enabled:
                    raise ValueError("Real audit requires feature flag OFF; do not activate production")
            revision=db.scalar(text("SELECT version_num FROM alembic_version"))
            database=db.scalar(text("SELECT current_database()"))
            after=fingerprints(db)
            db.rollback()
        with create_session_factory(engine)() as db:
            db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
            fresh=fingerprints(db)
            db.rollback()
        if before!=after or before!=fresh: raise ValueError("Development fingerprints changed during audit; do not publish an unchanged claim")
    finally: engine.dispose()
    test_data=database.endswith("_test")
    summary={"actual_audited":len(results),"real_inventory_audited":0 if args.candidates or test_data else len(results),
        "test_fixture_inventory_audited":len(results) if test_data and not args.candidates else 0,
        "candidate_only":bool(args.candidates),"status_counts":{s:sum(r["status"]==s for r in results) for s in ("AUTO_PASS","NEEDS_REVIEW","QUARANTINED")},
        "source_traceable":sum(r["source_traceable"] for r in results),
        "source_full_concordance_verified":sum(r["source_full_concordance_verified"] for r in results),
        "only_ai_consistency":sum(r["stages"]["answer_consistency"]["status"]=="PASS" and not r["independent_standard_answer_verified"] for r in results),
        "independent_answer_verified":sum(r["independent_standard_answer_verified"] for r in results),
        "reference_practice_only_potential":sum("PRACTICE_REFERENCE" in r["allowed_uses"] for r in results),
        "objective_candidate_potential":sum("OBJECTIVE_EVIDENCE_CANDIDATE" in r["allowed_uses"] for r in results),
        "current_eligible_in_pilot":sum(r["current_practice_eligible"] for r in results),
        "current_eligible_total":current_eligible,"active_inventory_total":len(all_rows),
        "potential_practice_count":sum(r["potential_practice_reference"] for r in results),
        "blocked_or_requires_further_verification":sum(r["status"]!="AUTO_PASS" for r in results),
        "actually_activated":0,"manual_review_candidates":sum(r["manual_review_candidate"] for r in results),
        "stage_counts":{s:{status:sum(r["stages"][s]["status"]==status for r in results) for status in
            ("PASS","FAIL","UNKNOWN","NOT_APPLICABLE","ERROR")} for s in results[0]["stages"]},
        "risk_counts":dict(Counter(x["reason"] for r in results for x in r["risks"])),"model_calls":0}
    report={"format":"question-quality-shadow-report-v1","rule_version":args.rule_version,"rule_build_sha256":build,
        "checked_at":datetime.now(timezone.utc).isoformat(),"elapsed_seconds":round(time.perf_counter()-started,3),
        "schema_revision":revision,"database":database,"dataset_environment":"test_fixture" if test_data else "development_inventory",
        "mode":"dry_run","summary":summary,"questions":results,
        "protection":{"database_written":False,"fingerprints_equal":True,"before":before,"after":fresh},
        "decision_set_sha256":digest([r["decision_sha256"] for r in results])}
    if comparison:
        report["teaching_rule_version"]=TEACHING_RULE_VERSION
        report["comparison_dataset_sha256"]=digest(ids)
        report["comparison"]={"same_ids_in_same_order":True,"feature_flag_enabled":False,
            "old_result_counts":{s:sum(r["previous_rule_result"]["status"]==s for r in results) for s in ("AUTO_PASS","NEEDS_REVIEW","QUARANTINED")},
            "new_use_counts":{s:sum(r["teaching_quality"]["primary_use"]==s for r in results) for s in (
                "TEACHING_PRACTICE_ELIGIBLE","REFERENCE_ONLY","OBJECTIVE_GRADING_ELIGIBLE","BLOCKED_MATERIAL_ERROR","INSUFFICIENT_EVIDENCE")},
            "material_errors":sum(r["teaching_quality"]["material_error"] for r in results),
            "insufficient_evidence":sum(r["teaching_quality"]["primary_use"]=="INSUFFICIENT_EVIDENCE" for r in results),
            "manual_risk_candidates":sum(r["teaching_quality"]["manual_review_candidate"] for r in results),
            "strict_source_verified":sum(r["teaching_quality"]["strict_source_verified"] for r in results),
            "strict_graduation_eligible":sum(r["teaching_quality"]["strict_graduation_evidence_eligible"] for r in results),
            "objective_feedback_candidates":sum(r["teaching_quality"]["objective_grading_eligible"] for r in results),
            "potential_new_pilot_questions":sum((r["teaching_quality"]["teaching_practice_eligible"] or
                r["teaching_quality"]["reference_practice_eligible"]) and not r["current_practice_eligible"] for r in results),
            "baseline_eligible_total":sum(e.practice_eligible for e in baseline),
            "enabled_runtime_candidate_total":sum(e.practice_eligible for e in enabled),
            "runtime_potential_additions":sum(b.practice_eligible and not a.practice_eligible for a,b in zip(baseline,enabled)),
            "runtime_withheld":sum(a.practice_eligible and not b.practice_eligible for a,b in zip(baseline,enabled)),
            "actually_activated":0,"runtime_scope":"metadata + bounded current-content checks; full native source comparison only for fixed pilot"}
        report["comparison_decision_sha256"]=digest([r["teaching_quality"]["decision_sha256"] for r in results])
    output.mkdir(parents=True,exist_ok=False)
    with (output/"report.json").open("x",encoding="utf-8") as f: json.dump(report,f,ensure_ascii=False,indent=2)
    with (output/"report.md").open("x",encoding="utf-8") as f: f.write(render(report))
    if comparison:
        lines=["# 同30题用途分层对照（私有）","",json.dumps(report["comparison"],ensure_ascii=False,indent=2),"",
            "| ID | 旧规则 | 新用途 | 当前可练 | 潜在可练 | 可靠反馈 | 严格来源 | 严格毕业 | 阻断 |",
            "|---|---|---|---|---|---|---|---|---|"]
        for r in results:
            v=r["teaching_quality"]
            lines.append(f"| {r['binding']['audit_subject_id']} | {r['previous_rule_result']['status']} | {v['primary_use']} | {r['current_practice_eligible']} | {v['teaching_practice_eligible'] or v['reference_practice_eligible']} | {v['objective_grading_eligible']} | {v['strict_source_verified']} | {v['strict_graduation_evidence_eligible']} | {', '.join(v['blocking_reasons'])} |")
        with (output/"comparison.md").open("x",encoding="utf-8") as f: f.write("\n".join(lines)+"\n")
    print(json.dumps({"output":str(output),"summary":summary,"elapsed_seconds":report["elapsed_seconds"]},ensure_ascii=False,indent=2))
    return report


def main(argv=None):
    for stream in (sys.stdout,sys.stderr):
        if hasattr(stream,"reconfigure"): stream.reconfigure(encoding="utf-8",errors="backslashreplace")
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dry-run",action="store_true",required=True)
    p.add_argument("--limit",type=int,default=30)
    p.add_argument("--question-id",action="append")
    p.add_argument("--kp-code",action="append")
    p.add_argument("--candidates",type=Path)
    p.add_argument("--rule-version",default=RULE_VERSION,choices=[RULE_VERSION])
    p.add_argument("--source-manifest",type=Path)
    p.add_argument("--compare-report",type=Path,help="Reaudit exact 30 IDs from B1; no alternate sample")
    p.add_argument("--source-root",action="append",type=Path)
    p.add_argument("--output-dir",type=Path)
    args=p.parse_args(argv)
    if not 1<=args.limit<=100: p.error("limit must be 1..100")
    if args.candidates and (args.question_id or args.kp_code): p.error("Candidate and stored-question scopes cannot be mixed")
    args.output_dir=args.output_dir or ROOT/"storage/quality-audits"/(datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")+"-"+uuid4().hex[:8])
    args.source_root=args.source_root or [Path("C:/Users/ZBT/Desktop/数学二与408逐题知识点索引_2000至今/个人复习原卷"),Path("C:/Users/ZBT/Desktop/考研知识点")]
    return run(args)


if __name__=="__main__":
    try: main()
    except (ValueError,OSError) as exc:
        print("Audit stopped: "+str(exc),file=sys.stderr)
        raise SystemExit(2)
