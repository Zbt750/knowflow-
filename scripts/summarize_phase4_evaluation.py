"""Summarize retained Phase 4 reports without any database or model call."""
from pathlib import Path
from hashlib import sha256
import argparse,json
ROOT=Path(__file__).resolve().parents[1]
def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--output",type=Path,required=True);args=parser.parse_args()
    output=args.output.resolve()
    if not output.is_relative_to(ROOT/"tmp") or output.exists():parser.error("new output under tmp required")
    review=json.loads((ROOT/"eval/learning-assistant/phase4-human-review-2026-10-06.json").read_text(encoding="utf-8"))
    summary={"reports":[],"model_calls":0,"human_review":review,"additional_calls":0}
    for item in review["retained_reports"]:
        path=ROOT/item["path"];data=json.loads(path.read_text(encoding="utf-8"))
        if data["model_calls"]!=item["calls"]:raise ValueError("model count mismatch")
        summary["model_calls"]+=data["model_calls"]
        cases=[]
        for c in data["cases"]:
            trace=c.get("generation_trace") or {};metrics=(c.get("planner") or {}).get("metrics") or {}
            cases.append({"case_id":c["id"],"completion":c["status"],"calls":c["model_requests"],"error":c["error_code"],
                "retry":trace.get("retry_count",sum(x.get("attempt",1)>1 for x in metrics.get("calls",[]))),
                "call_failures":[{k:x.get(k) for k in ("attempt","status","finish_reason","error_code","duration_ms")} for x in trace.get("calls",[]) if x.get("status")=="failed"],
                "observed_usage":trace.get("observed_usage"),"planner_usage":[x.get("usage") for x in metrics.get("calls",[])],
                "generation_call_duration_ms":sum(x.get("duration_ms",0) for x in trace.get("calls",[])),
                "planner_duration_ms":metrics.get("duration_ms"),"first_visible_latency":"not separately observed by this evaluation harness",
                "quality_result":"see manual review; completion alone is not PASS"})
        summary["reports"].append({"path":item["path"],"sha256":sha256(path.read_bytes()).hexdigest(),"dataset_version":data["dataset_version"],
            "dataset_sha256":data.get("dataset_sha256","not recorded by original v1 harness; cannot backfill as actual evidence"),"model":data["model"],"rollback_verified":data["rollback_verified"],"temporary_conversation_remaining":data["temporary_conversation_remaining"],"cases":cases})
    if summary["model_calls"]>review["authorized_limit"]:raise ValueError("phase budget exceeded")
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"model_calls":summary["model_calls"],"reports":len(summary["reports"]),"additional_calls":0}))
if __name__=="__main__":main()
