#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""导入后闭环核验：版本、资格、节点题库、今日学习绑定与作答事件。

默认只读；--exercise 会在嵌套事务里临时建计划/练习项/作答，
验证 PracticeItem→QuestionVersion 绑定与 Attempt/LearningEvent 落库，
结束后回滚，不留下测试数据。

用法：
    APP_ENV=test TEST_DATABASE_URL=postgresql+psycopg://.../kaoyan_test \
      python scripts/verify_long_question_bank.py --batch-key longbank-20261018-pilot --exercise
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.engine import make_url

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.config import get_settings  # noqa: E402
from backend.db import create_db_engine, create_session_factory  # noqa: E402
from backend.models.learning import (  # noqa: E402
    DailyPlan, KnowledgePoint, KpState, LearningEvent, PracticeItem, Question,
    QuestionAttempt, QuestionVersion,
)
from backend.models.personal_generation import PersonalGenerationBatch  # noqa: E402
from backend.services.answer_submission_service import submit_answer  # noqa: E402
from backend.services.question_availability import question_availability  # noqa: E402
from backend.services.question_eligibility import question_eligibility  # noqa: E402
from backend.services.question_versions import version_snapshot_hash  # noqa: E402

SHANGHAI = ZoneInfo("Asia/Shanghai")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-key", default="longbank-20261018-pilot")
    parser.add_argument("--exercise", action="store_true", help="执行临时练习项+作答闭环后回滚")
    parser.add_argument("--exercise-count", type=int, default=1,
                        help="最多选几道代表题做闭环（建议 5）")
    parser.add_argument("--allow-partial", action="store_true",
                        help="PASS-only 导入时允许每节点 0/1 题，不强制 2 题")
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args()

    settings = get_settings()
    url = str(settings.active_database_url)
    parsed_url = make_url(url)
    database_name = parsed_url.database or ""
    if database_name == "kaoyan" or not database_name.endswith("_test"):
        raise SystemExit(f"拒绝核验：{database_name!r} 不是隔离测试库（*_test）")
    print(f"[target] host={parsed_url.host} port={parsed_url.port} database={database_name}")

    engine = create_db_engine(url)
    session = create_session_factory(engine)()
    now = datetime.now(SHANGHAI)
    checks: dict[str, object] = {}
    failures: list[str] = []
    try:
        batch = session.scalar(select(PersonalGenerationBatch).where(
            PersonalGenerationBatch.request_key == args.batch_key))
        if batch is None:
            raise SystemExit(f"找不到批次 {args.batch_key}")
        questions = list(session.scalars(select(Question).where(
            Question.generation_batch_id == batch.id).order_by(Question.kp_id, Question.created_at)))
        checks["batch_status"] = batch.status
        checks["questions"] = len(questions)

        by_kp: dict = {}
        for question in questions:
            by_kp.setdefault(question.kp_id, []).append(question)
        checks["kps"] = len(by_kp)
        checks["per_kp_counts"] = {str(kp): len(items) for kp, items in by_kp.items()}
        if not args.allow_partial and any(len(items) != 2 for items in by_kp.values()):
            failures.append("per_kp_count_not_2")

        version_ok = 0
        eligibility_ok = 0
        scope_ok = 0
        source_ok = 0
        for question in questions:
            node = session.get(KnowledgePoint, question.kp_id)
            version = session.get(QuestionVersion, question.current_version_id) if question.current_version_id else None
            if (version is not None and version.question_id == question.id
                    and version.version_number >= 1
                    and version_snapshot_hash(version.snapshot_json) == version.content_hash):
                version_ok += 1
            else:
                failures.append(f"version_missing_or_broken:{question.id}")
            eligibility = question_eligibility(question, node)
            if eligibility.practice_eligible and eligibility.evidence_capability == "personal_practice_only":
                eligibility_ok += 1
            else:
                failures.append(f"not_practice_eligible:{question.id}:{eligibility.blocking_reasons}")
            if question.bank_scope == "personal":
                scope_ok += 1
            if (question.question_provenance == "ai_generated_practice"
                    and question.answer_provenance == "ai_generated"):
                source_ok += 1
        checks["version_ok"] = version_ok
        checks["practice_eligible"] = eligibility_ok
        checks["personal_scope"] = scope_ok
        checks["ai_source_label"] = source_ok

        # 节点题库可见性（沿用现有 availability 汇总，不另写查询口径）
        availability = question_availability(session, now=now, kp_ids=list(by_kp),
                                             limit=500, bank_scope="personal")
        node_rows = {row["kp_id"]: row for row in availability.get("eligible_nodes", [])}
        visible = sum(node_rows.get(str(kp), {}).get("active_question_count", 0)
                      for kp in by_kp)
        checks["node_bank_visible_questions"] = visible
        if visible < len(questions):
            failures.append(f"node_bank_visibility_{visible}_of_{len(questions)}")

        # 不能混入公共正式题：本批次所有题必须 personal
        public_leak = session.scalar(select(func.count(Question.id)).where(
            Question.generation_batch_id == batch.id, Question.bank_scope != "personal")) or 0
        checks["public_leak"] = public_leak
        if public_leak:
            failures.append("public_leak")

        if args.exercise and questions:
            def category(question: Question) -> str:
                node = session.get(KnowledgePoint, question.kp_id)
                code = node.code if node else ""
                if code.startswith("math."):
                    return {"proof": "math_proof", "calculation": "math_calc"}.get(
                        question.question_type, "math_other")
                if code.startswith("cs408.ds."):
                    return "ds_algorithm"
                if code.startswith("cs408.os."):
                    return "os"
                if code.startswith("cs408.co."):
                    return "co"
                if code.startswith("cs408.cn."):
                    return "cn"
                return "other"

            buckets: dict[str, list[Question]] = {}
            for question in questions:
                buckets.setdefault(category(question), []).append(question)
            order = ["math_calc", "math_proof", "ds_algorithm", "os", "co", "cn",
                     "math_other", "other"]
            selected: list[Question] = []
            for key in order:
                if buckets.get(key) and len(selected) < args.exercise_count:
                    selected.append(buckets[key][0])
            for question in questions:
                if len(selected) >= args.exercise_count:
                    break
                if question not in selected:
                    selected.append(question)

            savepoint = session.begin_nested()
            exercise: list[dict] = []
            try:
                study_date = "2099-01-01"
                for day in range(1, 29):
                    candidate = f"2099-01-{day:02d}"
                    if session.scalar(select(DailyPlan.id).where(DailyPlan.study_date == candidate)) is None:
                        study_date = candidate
                        break
                plan = DailyPlan(study_date=study_date, status="active")
                session.add(plan)
                session.flush()
                for ordinal, question in enumerate(selected, 1):
                    node = session.get(KnowledgePoint, question.kp_id)
                    if session.get(KpState, node.id) is None:
                        session.add(KpState(kp_id=node.id))
                        session.flush()
                    item = PracticeItem(plan_id=plan.id, question_id=question.id,
                                        kp_id=question.kp_id, ordinal=ordinal)
                    session.add(item)
                    session.flush()
                    row = {
                        "question_id": str(question.id),
                        "kp_code": node.code,
                        "type": question.question_type,
                        "item_version_bound": str(item.question_version_id) == str(question.current_version_id),
                        "attempt_version_bound": False,
                        "learning_events": 0,
                    }
                    if not row["item_version_bound"]:
                        failures.append(f"practice_item_version_mismatch:{question.id}")
                    response = submit_answer(session, item_id=item.id,
                                             raw_answer=question.correct_answer, selected_option=None,
                                             idempotency_key=f"longbank-verify:{args.batch_key}:{question.id}:{uuid4()}",
                                             now=now)
                    attempt = session.get(QuestionAttempt, response.attempt_id)
                    row["attempt_version_bound"] = bool(
                        attempt and attempt.question_version_id == question.current_version_id)
                    if not row["attempt_version_bound"]:
                        failures.append(f"attempt_version_not_bound:{question.id}")
                    events = session.scalar(select(func.count(LearningEvent.id)).where(
                        LearningEvent.question_version_id == question.current_version_id)) or 0
                    row["learning_events"] = events
                    if events == 0:
                        failures.append(f"learning_event_missing:{question.id}")
                    exercise.append(row)
                checks["exercise"] = exercise
                checks["exercise_count"] = len(exercise)
                checks["exercise_categories"] = [category(q) for q in selected]
            except Exception as exc:
                checks["exercise_error"] = f"{type(exc).__name__}: {exc}"
                failures.append("exercise_failed")
            finally:
                savepoint.rollback()
    finally:
        session.close()

    report = {"batch_key": args.batch_key, "database": database_name,
              "checks": checks, "failures": failures, "passed": not failures}
    path = args.report or Path(f"docs/long-question-verify-{args.batch_key}.json")
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
