"""P5 before/after evidence evaluation. Offline by default; paid calls require approval."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import time
from unittest.mock import patch
from uuid import UUID, uuid4, uuid5, NAMESPACE_URL

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.run_learning_agent_eval import isolated_factory, CheckedProvider, snapshot, summarize

CASES = [
    {"id": "math_independent", "subject": "math2", "outcome": "independent"},
    {"id": "math_wrong", "subject": "math2", "outcome": "wrong"},
    {"id": "tree_assisted", "subject": "408", "outcome": "solution"},
    {"id": "tree_ungraded", "subject": "408", "outcome": "unknown"},
]
ASSET = ROOT / "eval/golden/integral_binary_tree_v1.json"


class EvidencePlanner:
    """Conditional protocol double. Does not demonstrate model planning quality."""
    def __init__(self): self.turn = 0
    def tool_turn(self, messages, tools, *, timeout):
        self.turn += 1
        if self.turn == 1:
            body = json.loads(messages[1]["content"])
            self.budget = body["budget_minutes"]
            actions = [("search_knowledge", {"query": body["goal"].split("，")[0]})]
        elif self.turn == 2:
            ids = [n["kp_id"] for n in json.loads(messages[-1]["content"])["nodes"]]
            actions = [("get_learning_state", {"kp_ids": ids})]
        elif self.turn == 3:
            self.state = json.loads(messages[-1]["content"])["states"][0]
            actions = [("find_questions", {"kp_ids": [self.state["kp_id"]]})]
        elif self.turn == 4:
            candidates = [q for q in json.loads(messages[-1]["content"])["questions"]
                          if not q["in_today_plan"] and q["minutes"] <= self.budget]
            recent = self.state["recent_attempts"]
            pending = self.state["pending_review_question_ids"]
            independent = {a["question_id"] for a in recent if a["result"] == "right"
                           and a["assisted"] is False and a["confidence"] != "guess"
                           and a["sequence_category"] in {"first_independent_correct", "independent_retest_correct", "repeat_correct"}}
            weak = [a["question_id"] for a in recent if a["question_id"] not in independent]
            if pending:
                preferred, reason = pending, "客观错题优先复测"
            elif weak:
                preferred, reason = weak, "辅助或未判定结果不是独立证据，重新验证"
            else:
                preferred, reason = [q["question_id"] for q in candidates if q["question_id"] not in independent], "补充不同题目的证据，不把一道题当全面掌握"
            chosen = next((q for q in candidates if q["question_id"] in preferred), None)
            actions = [("validate_plan", {"question_ids": [chosen["question_id"]] if chosen else [], "rationale": reason})]
        else:
            valid = json.loads(messages[-1]["content"]).get("valid", False)
            return {"message": {"content": json.dumps({"message": "草案已校验，等待确认" if valid else "预算或题量不足，需要调整", "needs_clarification": not valid})}}
        return {"message": {"tool_calls": [{"id": f"p5-{self.turn}-{i}", "type": "function",
            "function": {"name": name, "arguments": json.dumps(args)}} for i, (name, args) in enumerate(actions)]}}


def seed_slice(factory, case):
    """Only the caller's new isolated schema. Never attests/changes the source asset."""
    from sqlalchemy import delete, text
    from backend.models.base import Base
    from backend.models.learning import KnowledgePoint, Question, KpState, KpMasteryPolicy
    from backend.services.golden_learning_slice import GoldenSlice
    asset = GoldenSlice.model_validate_json(ASSET.read_text(encoding="utf-8"))
    topic = next(t for t in asset.topics if t.subject == case["subject"])
    kept = {"M01", "M03"} if case["subject"] == "math2" else {"T01", "T02"}
    with factory.begin() as db:
        database, schema, marker = db.execute(text("SELECT current_database(), current_schema(), obj_description(oid, 'pg_namespace') FROM pg_namespace WHERE nspname=current_schema()")).one()
        if not database.endswith("_test") or not re.fullmatch(r"agent_eval_[0-9a-f]{16}", schema) or marker != "kaoyan-agent-eval:v1":
            raise ValueError("P5 fixture requires a marked isolated evaluation schema")
        for table in reversed(Base.metadata.sorted_tables): db.execute(delete(table))
        node = KnowledgePoint(code=topic.kp_code, name=topic.name, subject="408" if topic.subject == "408" else "数学二",
                              is_active=True, is_assessable=True, is_reference_only=False)
        db.add(node); db.flush()
        db.add(KpState(kp_id=node.id))
        db.add(KpMasteryPolicy(kp_id=node.id, min_confirmations=3, min_real_questions=3,
                              required_variant_count=1, min_day_span=2, note="P5 isolated synthetic policy"))
        for entry in asset.questions:
            c = entry.content
            if c.source_id not in kept: continue
            q = Question(id=uuid5(NAMESPACE_URL, "p5-isolated:" + c.source_id), kp_id=node.id,
                **c.model_dump(exclude={"source_id", "kp_code", "grading_method"}),
                grading_config={"verified": True, "method": c.grading_method,
                                "version": "p5-SIMULATED-VERIFICATION-NOT-HUMAN-REVIEW"})
            db.add(q)
    return topic


def run_at(factory, goal, provider, now):
    from backend.schemas.learning_task import CreateTask
    from backend.services import learning_task_service as service
    class EvalDateTime(datetime):
        @classmethod
        def now(cls, tz=None): return now if tz else now.replace(tzinfo=None)
    before = snapshot(factory)
    with patch.object(service, "datetime", EvalDateTime):
        task = service.create_task(factory, CreateTask(goal=goal, budget_minutes=5))
        result = service.run_task(factory, task.task_id, CheckedProvider(provider))
    return result, snapshot(factory) == before


def confirm_once(factory, result, now):
    from backend.schemas.learning_task import ConfirmTask
    from backend.services.learning_task_service import confirm_task
    first = confirm_task(factory, result.task_id, ConfirmTask(draft_version=result.draft_version), now=now)
    before_replay = snapshot(factory)
    second = confirm_task(factory, result.task_id, ConfirmTask(draft_version=result.draft_version), now=now)
    return first.metrics["commit"] == second.metrics["commit"] and snapshot(factory) == before_replay


def run_journeys(factory, provider_factory, cases=CASES, on_record=None):
    from sqlalchemy import select
    from backend.models.learning import PracticeItem, Question
    from backend.services.answer_submission_service import submit_answer, record_answer_reveal
    from backend.services.learning_task_service import get_task
    records = []
    for case in cases:
        topic = seed_slice(factory, case)
        now = datetime(2026, 1, 1, 2, tzinfo=timezone.utc)
        goal = topic.name + "，正好1道题，5分钟，不安排知识复习。读取实际学习证据后安排。"
        record = {"case": case["id"], "runs": [], "checks": {}, "passed": False,
                  "manual_review": {"status": "pending", "items": ["证据解释是否准确", "理由是否符合目标", "未把最终答案等同过程掌握"]}}
        # Save before any model request so interruption cannot hide an attempted case.
        records.append(record)
        if on_record: on_record(records)
        try:
            first, readonly = run_at(factory, goal, provider_factory(case), now)
            record["runs"].append(first.model_dump(mode="json"))
            record["checks"].update(first_ready=first.status == "ready", first_no_business_write=readonly)
            if on_record: on_record(records)
            if first.status != "ready": continue
            record["checks"]["first_confirmation_idempotent"] = confirm_once(factory, first, now)
            qid = UUID(first.draft["questions"][0]["question_id"])
            with factory.begin() as db:
                item = db.scalar(select(PracticeItem).where(PracticeItem.question_id == qid))
                q = db.get(Question, qid)
                if case["outcome"] == "solution": record_answer_reveal(db, item_id=item.id, now=now)
                raw = "999" if case["outcome"] == "wrong" else "SYNTHETIC_RAW_ANSWER_DO_NOT_SEND" if case["outcome"] == "unknown" else q.correct_answer
                answer = submit_answer(db, item_id=item.id, raw_answer=raw, selected_option=None,
                    idempotency_key="p5-eval-" + case["id"], now=now, confidence="certain")
                replay = submit_answer(db, item_id=item.id, raw_answer=raw, selected_option=None,
                    idempotency_key="p5-eval-" + case["id"], now=now, confidence="certain")
                record["checks"]["answer_idempotent"] = replay == answer
                record["submission"] = answer.model_dump(mode="json", exclude={"raw_answer", "selected_option"})
            suffix = "优先补充另一道未验证的题，不重复上一道" if case["outcome"] == "independent" else "优先重新验证上次那道题；区分客观答错、看解析后完成和无法判定，不把未判定当错误"
            second, readonly = run_at(factory, topic.name + "，正好1道题，5分钟，不安排知识复习。根据上次真实学习记录安排下一次，" + suffix, provider_factory(case), now + timedelta(days=1))
            record["runs"].append(second.model_dump(mode="json"))
            states = [s for t in second.trace if t["tool"] == "get_learning_state" for s in t["result"].get("states", [])]
            chosen = [q["question_id"] for q in (second.draft or {}).get("questions", [])]
            dimensions = [d for s in states for d in (s.get("capability_profile") or {}).get("dimensions", []) if d["key"] == "final_result"]
            record["checks"].update(second_ready=second.status == "ready", second_no_business_write=readonly,
                reads_actual_submission=any(a.get("sequence_category") == answer.sequence_category and a.get("question_id") == str(qid) for s in states for a in s["recent_attempts"]),
                capability_confirmation=bool(dimensions) and sum(d["independent_question_count"] for d in dimensions) == (1 if case["outcome"] == "independent" else 0),
                objective_pending=bool(states) and any(str(qid) in s["pending_review_question_ids"] for s in states) == (case["outcome"] == "wrong"),
                requested_adaptation=len(chosen) == 1 and ((chosen[0] != str(qid)) == (case["outcome"] == "independent")),
                first_receipt_preserved=get_task(factory, first.task_id).metrics["commit"]["added_count"] == 1)
            if second.status == "ready": record["checks"]["second_confirmation_idempotent"] = confirm_once(factory, second, now + timedelta(days=1))
            record["passed"] = all(record["checks"].values())
        except Exception as exc:
            # Type only: do not put credentials, driver messages or private paths in reports.
            record["error_type"] = type(exc).__name__
        finally:
            if on_record: on_record(records)
            print(f"{case['id']}: {'PASS' if record['passed'] else 'FAIL'}; tasks={len(record['runs'])}", flush=True)
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--allow-synthetic-data", action="store_true")
    parser.add_argument("--case", action="append", choices=[c["id"] for c in CASES],
                        help="Only run selected cases; duplicates never increase the task allowance")
    args = parser.parse_args()
    selected = [c for c in CASES if not args.case or c["id"] in args.case]
    if args.live and not args.allow_synthetic_data: parser.error("Live calls require fresh approval and --allow-synthetic-data")
    os.environ["APP_ENV"] = "test"
    os.environ.setdefault("TEST_DATABASE_URL", "postgresql+psycopg://kaoyan:kaoyan_dev_pw@127.0.0.1:5433/kaoyan_test")
    from backend.config import get_settings
    from backend.services.learning_task_service import PROMPT_VERSION, SYSTEM_PROMPT, MAX_ROUNDS, MAX_TOOL_CALLS, TIME_BUDGET_SECONDS
    from backend.services.learning_task_tools import tool_definitions
    get_settings.cache_clear()
    settings = get_settings()
    if args.live:
        from backend.services.model_settings_service import load_local_settings
        from backend.chat.service import provider_from_settings
        effective = load_local_settings(settings.model_copy(update={"app_env": "dev"}))
        provider = provider_from_settings(effective)
        make_provider = lambda case: provider
    else: make_provider = lambda case: EvidencePlanner()
    model_config = {"model": getattr(provider, "model", "unknown"),
                    "provider": type(provider).__name__, "configured_max_output_tokens": getattr(provider, "max_tokens", None),
                    "task_max_output_tokens": min(provider.max_tokens, 2000) if hasattr(provider, "max_tokens") else None} if args.live else {"model": "protocol-test-double", "provider": "EvidencePlanner"}
    path = ROOT / "eval/reports" / ("agent-evidence-" + ("live-" if args.live else "protocol-") + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid4().hex[:6] + ".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    def save(records, complete=False):
        runs = [{"metrics": r["metrics"]} for c in records for r in c["runs"]]
        report = {"version": "p5-evidence-journey-v1", "mode": "real_model" if args.live else "protocol_only", "complete": complete,
            "code_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
            "workspace_files": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in (
                "scripts/run_agent_evidence_journey.py", "backend/services/learning_task_tools.py", "backend/services/learning_task_service.py", "backend/services/answer_submission_service.py", "backend/services/capability_service.py",
                "backend/chat/service.py", "backend/services/answer_grading.py", "backend/mastery/attempt_sequence.py", "backend/mastery/capability.py")},
            "dataset_sha256": hashlib.sha256(ASSET.read_bytes()).hexdigest(), "prompt_version": PROMPT_VERSION,
            "prompt_sha256": hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest(), "model_config": model_config,
            "tool_contract_sha256": hashlib.sha256(json.dumps(tool_definitions(), sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
            "limits": {"rounds": MAX_ROUNDS, "tool_calls": MAX_TOOL_CALLS, "task_seconds": TIME_BUDGET_SECONDS,
                       "max_attempts_per_round": 2},
            "content_review": "SIMULATED IN ISOLATED SCHEMA; SOURCE REMAINS GENERATED", "max_tasks": len(selected) * 2,
            "requested_cases": [c["id"] for c in selected],
            "duration_seconds": round(time.monotonic() - started, 2), "summary": summarize(runs),
            "passed": sum(c["passed"] for c in records), "total": len(records), "cases": records,
            "quality_claim": "Program constraints only; manual review pending; no claim of agent superiority or full subject coverage"}
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    save([])
    with isolated_factory(str(settings.active_database_url)) as factory:
        records = run_journeys(factory, make_provider, cases=selected, on_record=save)
    save(records, complete=True)
    print(f"Report: {path}")
    return 0 if len(records) == len(selected) and all(r["passed"] for r in records) else 1


if __name__ == "__main__": raise SystemExit(main())
