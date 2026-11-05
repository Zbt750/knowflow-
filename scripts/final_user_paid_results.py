"""Read-only final evidence collection and explicit non-model scoring. No Provider."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.final_user_paid_server import OUT, PLAN, snapshot, hashes


def main():
    from scripts.final_user_acceptance import configure, URL
    configure()
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from backend.models.learning_task import LearningTask
    from backend.models.chat import ChatMessage
    from backend.models.learning import KpState
    from backend.models.rag import DocumentChunk
    ledger = json.loads((OUT / "provider-ledger.json").read_text(encoding="utf-8"))
    assert len(ledger["requests"]) == 8 <= 20
    assert ledger["summary"]["usage_missing_requests"] == 0
    assert hashes() == json.loads((OUT / "runtime-hashes.json").read_text(encoding="utf-8"))
    before = json.loads((OUT / "truth-before.json").read_text(encoding="utf-8"))
    after = snapshot()
    assert before == after, "Do not hide unexpected business mutations"
    assert not json.loads((OUT.parent / "paid-v1/provider-ledger.json").read_text(encoding="utf-8"))["requests"]
    expected = {
        "cases.json": "ca05b1758f8f946c9cd679e15c6c1eb3f111d1349d67d1fafb80bad5b610df4e",
        "fixtures.json": "97fd401c2cfd94311a61757fdf81b449449c569d66516d945eca5b81c073b6db",
        "rubric.md": "906219799c5167541fe94cf8a91f8598bee265949dc2128ece98d3bea3b9c713"}
    assert all(hashlib.sha256((ROOT / "eval/phase5-closeout-v1" / f).read_bytes()).hexdigest() == sha for f, sha in expected.items())
    decisions = {
        "USER-R1": ("PASS", "真实资料回答，C1-C3绑定上传文件实际chunk，解释首项相消与高阶项，未编造页码；引用可在Chrome打开原文。"),
        "USER-R2": ("PARTIAL", "同会话及限定资料保持，未误入库存路由；诚实说明资料没有二阶展开，未计算要求的1/2。不能把省略数值评分为完整答对。"),
        "USER-A1": ("BLOCKED", "真实Agent发送3次请求并读取学习状态/库存/题目，但下一轮超过60000字节守卫，无最终规划、无草案、无计划写入。"),
        "USER-A2": ("FAIL", "明确询问可练题及真题/原创来源却进入普通QA；模型未读库存，称无法查看，未满足题目来源工具链要求。没有虚构全库均为AI题。"),
        "USER-A3": ("BLOCKED", "同一学习会话追问发送2次模型请求，随后再次context_limit，未交付独立/辅助证据清单或20分钟顺序。未重试A1，也未改Prompt。"),
        "USER-A4": ("PARTIAL", "确定性毕业后复习分支，无模型调用；未撤销真实毕业，但回复只说熟练度证据不足，未明确回答已毕业和毕业事实不撤销。0次应注明是毕业后窗口，避免误读为没有历史练习。")}
    result = []
    engine = create_engine(URL, connect_args={"options": "-c default_transaction_read_only=on"})
    with Session(engine) as db:
        nodes = json.loads((OUT.parent / "fixture.json").read_text(encoding="utf-8"))["nodes"]
        state = db.get(KpState, UUID(nodes["determinant"]["id"]))
        assert state.state == "mastered" and state.mastered_at is not None
        mastered = {"state": state.state, "mastered_at": state.mastered_at, "kp_id": str(state.kp_id)}
        for turn in json.loads(PLAN.read_text(encoding="utf-8"))["turns_in_priority_order"]:
            cid = turn["id"]
            directory = OUT / cid
            history = json.loads((directory / "restored-history.json").read_text(encoding="utf-8"))
            answer = history[-1]
            row = db.get(ChatMessage, UUID(answer["message_id"]))
            (directory / "saved-message-metadata.json").write_text(json.dumps(row.metadata_, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            task_id = answer.get("planner_task_id")
            if task_id and not (directory / "agent-task.json").exists():
                task = db.get(LearningTask, UUID(task_id))
                (directory / "agent-task.json").write_text(json.dumps({c.name: getattr(task, c.key) for c in task.__table__.columns}, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            citation_checks = []
            for card in answer.get("citations", []):
                chunk = db.get(DocumentChunk, UUID(card["chunk_id"]))
                assert chunk and str(chunk.material_id) == card["material_id"] == "68302cb5-e3df-4610-b11b-23f0242a9f38"
                citation_checks.append({"label": card["label"], "chunk_id": card["chunk_id"],
                    "content_sha256": hashlib.sha256(chunk.content.encode()).hexdigest(), "correct_selected_material": True})
            calls = [r for r in ledger["requests"] if r["case_id"] == cid]
            result.append({"id": cid, "score": decisions[cid][0], "reason": decisions[cid][1],
                "saved_status": answer["status"], "model_requests": len(calls),
                "input_tokens": sum(r["usage"]["prompt_tokens"] for r in calls),
                "output_tokens": sum(r["usage"]["completion_tokens"] for r in calls),
                "finish_reasons": [r["finish_reason"] for r in calls],
                "provider_latency_seconds": sum(r["latency_seconds"] for r in calls),
                "citation_checks": citation_checks, "answer": answer["content"]})
    engine.dispose()
    import sympy as sp
    x = sp.symbols("x")
    oracle = sp.limit((sp.exp(x) - 1 - x) / x**2, x, 0)
    assert oracle == sp.Rational(1, 2)
    summary = {"status": "PHASE5_BLOCKED", "completed_at": datetime.now(timezone.utc).isoformat(),
        "scoring_method": "逐例核对冻结期望、真实用户回答、数据库/工具轨迹；本地SymPy复核；无收费裁判或human_verified资格声明",
        "results": result, "score_counts": dict(Counter(r["score"] for r in result)),
        "meter": ledger["summary"], "remaining_physical_requests_not_automatically_reused": 12,
        "observed_finish_reasons": dict(Counter(r["finish_reason"] for r in ledger["requests"])),
        "average_provider_latency_seconds": sum(r["latency_seconds"] for r in ledger["requests"]) / 8,
        "peak_uncached_cost_estimate_cny": ledger["summary"]["peak_uncached_cost_upper_estimate_cny"],
        "offpeak_uncached_cost_estimate_cny": ledger["summary"]["peak_uncached_cost_upper_estimate_cny"] / 2,
        "offpeak_cache_aware_cost_estimate_cny": sum(r["peak_cache_aware_estimate_cny"] for r in ledger["requests"]) / 2,
        "billing_basis": "2026-10-15上海晚间；官方空闲价输入未缓存1/百万、命中0.02/百万、输出4/百万。峰值2/0.04/8用于保守守卫。供应商账单未核对。",
        "business_fingerprints_unchanged": before == after, "business_after": after,
        "graduation_fact_preserved": mastered, "original_40_assets_unchanged": expected,
        "runtime_hashes_unchanged": True, "real_database_accessed": False,
        "full_40_retest": False, "new_formal_questions": 0, "r2_symbolic_oracle": str(oracle)}
    (OUT / "final-results.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("status", "score_counts", "meter", "average_provider_latency_seconds", "offpeak_uncached_cost_estimate_cny", "offpeak_cache_aware_cost_estimate_cny", "business_fingerprints_unchanged")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
