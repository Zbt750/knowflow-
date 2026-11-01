"""Replay paid-v2 A1/A3 input guards offline; original evidence is immutable."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SOURCE = ROOT / "storage/quality-audits/final-real-user-20261015/paid-v2"
OUT = ROOT / "storage/quality-audits/core-ux-stabilization-20261015"


def replay():
    from backend.services.learning_task_context import compact_model_messages, compact_tool_result, expand_records
    from backend.services.learning_task_service import SYSTEM_PROMPT, PROMPT_VERSION, _model_turn, _parse_conclusion
    ledger = json.loads((SOURCE / "provider-ledger.json").read_text(encoding="utf-8"))
    checks = []
    for cid in ("USER-A1", "USER-A3"):
        task = json.loads((SOURCE / cid / "agent-task.json").read_text(encoding="utf-8"))
        last = [r for r in ledger["requests"] if r["case_id"] == cid][-1]
        messages = deepcopy(last["request"]["messages"])
        calls = json.loads(last["response_text"])["choices"][0]["message"]["tool_calls"]
        rows = [t for t in task["trace"] if t["round"] == task["metrics"]["calls"][-1]["round"]]
        assert len(calls) == len(rows)
        messages.append({"role":"assistant", "content":None, "tool_calls":calls})
        for call, row in zip(calls, rows):
            assert call["function"]["name"] == row["tool"]
            messages.append({"role":"tool", "tool_call_id":call["id"], "content":json.dumps(row["result"],ensure_ascii=False)})
        original_bytes = len(json.dumps({"messages":messages,"tools":last["request"]["tools"]},ensure_ascii=False,separators=(",", ":")).encode())
        messages[0]["content"] = SYSTEM_PROMPT
        compact = compact_model_messages(messages)
        by_id = {m["tool_call_id"]: json.loads(m["content"]) for m in compact if m["role"] == "tool"}
        for old in messages:
            if old["role"] not in {"tool", "user"}: continue
            try: value = json.loads(old["content"])
            except ValueError: continue
            new = next(m for m in compact if m.get("tool_call_id") == old["tool_call_id"]) if old["role"] == "tool" else compact[messages.index(old)]
            restored = json.loads(new["content"])
            if "same_result_as_tool_call_id" in restored:
                restored = by_id[restored["same_result_as_tool_call_id"]]
            restored = expand_records(restored)
            expected = compact_tool_result(value) if old["role"] == "tool" else value
            assert restored == expected, "A source/version/evidence fact was lost"
        captured = []
        class OfflineFinalStage:
            model = "OFFLINE_PROTOCOL_PROBE_NOT_DEEPSEEK"
            def tool_turn(self, messages, tools, *, timeout):
                captured.append(messages)
                return {"message":{"content":json.dumps({"message":"离线工程探针：可进入最终回答，尚未证明真实模型能规划。", "needs_clarification":True})},"model":self.model,"finish_reason":"stop"}
        response = _model_turn(OfflineFinalStage(), messages, [], turn=4, timeout=1)
        assert captured and _parse_conclusion(response["message"]["content"]).needs_clarification
        size = len(json.dumps({"messages":compact,"tools":last["request"]["tools"]},ensure_ascii=False,separators=(",", ":")).encode())
        assert size <= 60000 and size + 2143 <= 64000
        checks.append({"case":cid, "reconstructed_v18_bytes":original_bytes, "new_request_bytes":size,
            "all_json_facts_roundtrip":True,"references_resolve":True,"offline_final_stage_reached":True,
            "real_provider_requests":0,"previous_real_response_unchanged":True})
    return {"prompt_version":PROMPT_VERSION, "real_model_verified":False, "results":checks,
        "source_ledger_sha256":hashlib.sha256((SOURCE/"provider-ledger.json").read_bytes()).hexdigest()}


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    result = replay()
    (OUT / "context-replay.json").write_text(json.dumps(result, ensure_ascii=False, indent=2),encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False,indent=2))
