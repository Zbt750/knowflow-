"""Default read-only full inventory diagnosis. No apply, paid calls or activation."""
import argparse
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
import json
import sys
import hashlib
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from sqlalchemy import select,text
from backend.config import get_settings
from backend.db import create_db_engine,create_session_factory
from backend.models.learning import Question,KnowledgePoint,QuestionAnswerConsistencyRun,KpMasteryPolicy,QuestionSourceAttestation
from backend.services.question_repair import local_pack_registry,identity_counts,diagnose,VERSION
from backend.services.question_quality import duplicates
from backend.services.golden_learning_slice import digest
from scripts.audit_question_quality import safe_output,rule_build_sha
from scripts.review_golden_slice import fingerprints


def rows_json(rows):
    return [{c.name:getattr(row,c.name) for c in row.__table__.columns} for row in rows]


def run(output):
    output=safe_output(output)
    registry,rejected=local_pack_registry(ROOT)
    engine=create_db_engine(str(get_settings().active_database_url))
    try:
        with create_session_factory(engine)() as db:
            db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
            before=fingerprints(db)
            nodes=list(db.scalars(select(KnowledgePoint))); ns={n.id:n for n in nodes}
            qs=list(db.scalars(select(Question).where(Question.is_active.is_(True)).order_by(Question.id)))
            runs=list(db.scalars(select(QuestionAnswerConsistencyRun).where(QuestionAnswerConsistencyRun.question_id.in_([q.id for q in qs]))))
            identities=identity_counts(qs); dup=duplicates(qs)
            grouped={q.id:[] for q in qs}
            for r in runs: grouped[r.question_id].append(r)
            results=[diagnose(q,ns.get(q.kp_id),runs=grouped[q.id],registry=registry,identities=identities,duplicate=dup[str(q.id)]) for q in qs]
            blocked=[r for r in results if not r["production_eligibility"]["practice_eligible"]]
            # Frozen complete rows for a fresh _test schema; no private learner history copied.
            snapshot={"knowledge_points":rows_json(nodes),"questions":rows_json(qs),
                "kp_mastery_policies":rows_json(list(db.scalars(select(KpMasteryPolicy)))),
                "question_source_attestations":rows_json(list(db.scalars(select(QuestionSourceAttestation).where(QuestionSourceAttestation.question_id.in_([q.id for q in qs]))))),
                "question_answer_consistency_runs":rows_json(runs),"learning_history_copied":False}
            info={"database":db.scalar(text("SELECT current_database()")),"revision":db.scalar(text("SELECT version_num FROM alembic_version"))}
            snapshot=json.loads(json.dumps(snapshot,ensure_ascii=False,default=str))
            db.rollback()
        with create_session_factory(engine)() as db:
            db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
            after=fingerprints(db); db.rollback()
        if before!=after: raise ValueError("Development data changed during diagnosis")
    finally: engine.dispose()
    summary={"active":len(results),"production_eligible":len(results)-len(blocked),"production_blocked":len(blocked),
        "teaching_use_counts":dict(Counter(r["teaching_quality"]["primary_use"] for r in results)),
        "blocked_primary_counts":dict(Counter(r["primary_blocker"] for r in blocked)),
        "blocked_multilabel_counts":dict(Counter(label for r in blocked for label in r["blocker_labels"])),
        "blocked_category_counts":{c:sum(r["category"]==c for r in blocked) for c in "ABCD"},
        "exact_pack_repair_candidates":sum(bool(r["pack_link"] and r["pack_link"]["usable"]) for r in blocked),
        "independent_proof_available":sum(r["automatic_answer_proof_available"] for r in blocked),
        "known_material_errors":sum(r["known_material_error"] for r in blocked),
        "manual_risk_candidates":sum(r["manual_risk_candidate"] for r in blocked),
        "bounded_verifier_outside_scope":sum(r["independent_answer"]["status"] in {"NOT_APPLICABLE","UNKNOWN","ERROR"} for r in blocked),
        "category_work":{"A":{"total":sum(r["category"]=="A" for r in blocked),"link_rebuild_candidates":sum(r["category"]=="A" and bool(r["pack_link"] and r["pack_link"]["usable"]) for r in blocked),
            "independent_answer_proved":sum(r["category"]=="A" and r["automatic_answer_proof_available"] for r in blocked)},
            "B":{"total":sum(r["category"]=="B" for r in blocked),"independent_answer_proved":sum(r["category"]=="B" and r["automatic_answer_proof_available"] for r in blocked)},
            "C":{"total":sum(r["category"]=="C" for r in blocked),"reference_candidates_not_admitted":sum(r["category"]=="C" for r in blocked)},
            "D":{"total":sum(r["category"]=="D" for r in blocked),"material_errors":sum(r["category"]=="D" and r["known_material_error"] for r in blocked)}},
        "model_calls":0,"development_written":False,"actually_activated":0}
    build_paths=["backend/services/question_repair.py","scripts/diagnose_question_blockers.py","scripts/run_question_repair_pilot.py"]
    report={"version":VERSION,"checked_at":datetime.now(timezone.utc).isoformat(),**info,"feature_flag":get_settings().teaching_practice_enabled,
        "inventory_snapshot_sha256":digest(snapshot),
        "repair_build_sha256":digest({p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in build_paths}),
        "rule_build_sha256":rule_build_sha(),"summary":summary,"questions":results,"pack_parse_errors":rejected,
        "protection":{"before":before,"after":after,"equal":True}}
    output.mkdir(parents=True,exist_ok=False)
    (output/"report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str),encoding="utf-8")
    (output/"inventory-snapshot.json").write_text(json.dumps(snapshot,ensure_ascii=False,indent=2,default=str),encoding="utf-8")
    lines=["# 全库阻塞诊断（私有）","",json.dumps(summary,ensure_ascii=False,indent=2),"",
        "多标签数量相加不等于不可练数量。A是关联修复候选，不表示答案已可靠验证。B范围外项暂缓自动验证，不全部送人工。", "",
        "| ID | 科目 | 节点 | 当前可练 | 新用途 | 分类 | 主要阻塞 | 所有阻塞 |","|---|---|---|---|---|---|---|---|"]
    for r in results:
        lines.append(f"| {r['question_id']} | {r['subject']} | {r['node_name']} | {r['production_eligibility']['practice_eligible']} | {r['teaching_quality']['primary_use']} | {r['category']} | {r['primary_blocker']} | {', '.join(r['blocker_labels'])} |")
    (output/"report.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    print(json.dumps(summary,ensure_ascii=False,indent=2)); return report


if __name__=="__main__":
    if hasattr(sys.stdout,"reconfigure"): sys.stdout.reconfigure(encoding="utf-8")
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir",type=Path,required=True)
    parser.add_argument("--dry-run",action="store_true",default=True)
    args=parser.parse_args()
    run(args.output_dir)
