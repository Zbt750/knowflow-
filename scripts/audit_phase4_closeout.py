"""Read-only Phase 4 inventory, protected-data fingerprints and runtime evidence."""
from __future__ import annotations
import argparse,json,sys,subprocess
from pathlib import Path
from hashlib import sha256
from datetime import datetime,timezone
from collections import Counter
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from sqlalchemy import select,text
from backend.config import get_settings
from backend.db import create_db_engine,create_session_factory
from backend.models.learning import Question,KnowledgePoint
from backend.services.question_availability import question_availability
from backend.services.learning_qa_service import PROMPT_VERSION as QA_VERSION
from backend.services.learning_task_service import PROMPT_VERSION as PLANNER_VERSION
from scripts.expand_phase3b_inventory import protected_fingerprints

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--runtime",action="store_true")
    parser.add_argument("--process-manifest",type=Path,default=ROOT/"tmp/phase4_20261006/runtime-manifest.json");args=parser.parse_args()
    output=args.output.resolve()
    if not output.is_relative_to(ROOT/"tmp") or output.exists(): parser.error("new output under project tmp required")
    settings=get_settings();factory=create_session_factory(create_db_engine(str(settings.active_database_url)))
    now=datetime.now(timezone.utc)
    with factory() as db:
        db.execute(text("SET TRANSACTION READ ONLY"))
        inventory=question_availability(db,now=now,limit=0)
        protected=protected_fingerprints(db)
        questions=list(db.scalars(select(Question).order_by(Question.id)))
        trust_fields=("question_provenance","answer_provenance","answer_reliability","grading_method","content_reviewed_by","content_reviewed_at","answer_reviewed_by","answer_reviewed_at")
        trust_rows=[{"id":str(q.id),**{k:str(getattr(q,k,None)) for k in trust_fields}} for q in questions]
        protected["question_trust_fields"]=sha256(json.dumps(trust_rows,sort_keys=True).encode()).hexdigest()
        policy_sources={path:sha256((ROOT/path).read_bytes()).hexdigest() for path in (
            "backend/services/evidence_pool.py","backend/services/question_eligibility.py","backend/mastery/rules.py","backend/mastery/policy.py")}
        boundary={k:inventory[k] for k in ("practice_eligible_count","eligible_node_count","subject_counts","question_provenance_counts","answer_provenance_counts","grading_capability_counts","evidence_capability_counts")}
        boundary["question_answer_reliability_counts"]=dict(Counter(q.answer_reliability for q in questions))
        boundary["active_assessable_nodes"]=len(list(db.scalars(select(KnowledgePoint.id).where(KnowledgePoint.is_active.is_(True),KnowledgePoint.is_assessable.is_(True)))))
        migration=list(db.execute(text("SELECT version_num FROM alembic_version")).scalars())
    paths=("backend/services/learning_qa_service.py","backend/services/learning_task_service.py","backend/services/learning_task_tools.py",
        "backend/services/learning_assistant_service.py","backend/services/study_context_service.py","backend/services/assistant_router.py",
        "backend/services/question_availability.py","backend/chat/service.py","backend/chat/evidence.py","backend/api/routes/chat.py",
        "backend/schemas/learning_assistant.py","frontend/src/components/LearningTaskPanel.vue","frontend/src/pages/ChatPage.vue",
        "backend/app.py","backend/models/chat.py","backend/models/practice_request.py","backend/services/practice_request_service.py",
        "backend/services/deep_qa_handoff_service.py","backend/services/qa_information_router.py","backend/services/web_search_service.py",
        "backend/api/routes/practice_requests.py","frontend/src/components/PracticeRequestCard.vue","frontend/src/pages/MaterialsPage.vue","frontend/src/router.ts")
    files={p:sha256((ROOT/p).read_bytes()).hexdigest() for p in paths}
    from backend.main import app
    schema=app.openapi();schema_hash=sha256(json.dumps(schema,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    result={"created_at":now.isoformat(),"git_head":subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip(),
        "workspace_files":files,"workspace_phase4_sha256":sha256(json.dumps(files,sort_keys=True).encode()).hexdigest(),
        "qa_prompt_version":QA_VERSION,"planner_prompt_version":PLANNER_VERSION,"snapshot_version":"actual-model-evidence-v2",
        "migration_head":migration,"inventory":boundary,"protected_fingerprints":protected,"policy_source_sha256":policy_sources,
        "expected_openapi_paths":len(schema["paths"]),"expected_openapi_sha256":schema_hash,"runtime":None}
    if args.runtime:
        import httpx
        with httpx.Client(base_url="http://127.0.0.1:8000",trust_env=False,timeout=10) as client:
            health=client.get("/api/health");actual=client.get("/openapi.json");available=client.get("/api/question-availability")
            # A missing conversation is rejected before message/task/model creation.
            probe=client.post("/api/chat/sessions/00000000-0000-4000-8000-000000000000/assistant:stream",
                json={"question":"检查学习位置","study_context":{"surface":"study"}})
        actual_schema=actual.json();health_data=health.json()
        result["runtime"]={"checked_at":datetime.now(timezone.utc).isoformat(),"health_http":health.status_code,
            "health":{k:health_data.get(k) for k in ("status","database","retrieval","worker","llm_configured")},
            "openapi_http":actual.status_code,"openapi_paths":len(actual_schema["paths"]),
            "openapi_matches_workspace":sha256(json.dumps(actual_schema,sort_keys=True,ensure_ascii=False).encode()).hexdigest()==schema_hash,
            "assistant_endpoint_present":"/api/chat/sessions/{session_id}/assistant:stream" in actual_schema["paths"],
            "availability_http":available.status_code,"practice_eligible_count":available.json().get("practice_eligible_count"),
            "assistant_validation_http":probe.status_code,"assistant_validation_error_code":probe.json().get("error",{}).get("code"),
            "eligible_node_count_api":"not_exposed_by_existing_response_schema; database count recorded separately"}
        manifest=args.process_manifest
        if manifest.exists():
            loaded=json.loads(manifest.read_text(encoding="utf-8"))
            result["runtime"]["process_manifest"]={k:loaded[k] for k in ("pid","parent_pid","started_at","workspace","module","qa_prompt_version","planner_prompt_version","bind")}
            result["runtime"]["loaded_backend_hashes_match_workspace"]=all(
                files[k]==v for k,v in loaded["workspace_files"].items() if k.startswith("backend/"))
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"output":str(output),"inventory":boundary,"runtime":result["runtime"]},ensure_ascii=True))
if __name__=="__main__":main()
