"""Launch current local backend with a non-secret Phase 4 process manifest."""
from pathlib import Path
import argparse,json,os,sys
from datetime import datetime,timezone
from hashlib import sha256
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--manifest",type=Path,required=True);args=parser.parse_args()
    manifest=args.manifest.resolve()
    if not manifest.is_relative_to(ROOT/"tmp") or manifest.exists(): parser.error("new manifest under tmp required")
    from backend.main import app
    from backend.services.learning_qa_service import PROMPT_VERSION as qa
    from backend.services.learning_task_service import PROMPT_VERSION as planner
    paths=("backend/services/learning_qa_service.py","backend/services/learning_task_service.py","backend/services/learning_task_tools.py",
        "backend/services/learning_assistant_service.py","backend/services/study_context_service.py","backend/services/assistant_router.py",
        "backend/services/question_availability.py","backend/chat/service.py","backend/chat/evidence.py","backend/api/routes/chat.py",
        "backend/schemas/learning_assistant.py","frontend/src/components/LearningTaskPanel.vue","frontend/src/pages/ChatPage.vue",
        "backend/app.py","backend/models/chat.py","backend/models/practice_request.py","backend/services/practice_request_service.py",
        "backend/services/deep_qa_handoff_service.py","backend/services/qa_information_router.py","backend/services/web_search_service.py",
        "backend/api/routes/practice_requests.py","frontend/src/components/PracticeRequestCard.vue","frontend/src/pages/MaterialsPage.vue","frontend/src/router.ts")
    files={p:sha256((ROOT/p).read_bytes()).hexdigest() for p in paths}
    data={"pid":os.getpid(),"parent_pid":os.getppid(),"started_at":datetime.now(timezone.utc).isoformat(),"workspace":str(ROOT),
        "module":"backend.main:app","qa_prompt_version":qa,"planner_prompt_version":planner,
        "workspace_phase4_sha256":sha256(json.dumps(files,sort_keys=True).encode()).hexdigest(),"workspace_files":files,
        "openapi_paths":len(app.openapi()["paths"]),"bind":"127.0.0.1:8000"}
    manifest.parent.mkdir(parents=True,exist_ok=True);manifest.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"pid":data["pid"],"qa_prompt_version":qa,"planner_prompt_version":planner,"openapi_paths":data["openapi_paths"]}),flush=True)
    import uvicorn
    uvicorn.run(app,host="127.0.0.1",port=8000)
if __name__=="__main__":main()
