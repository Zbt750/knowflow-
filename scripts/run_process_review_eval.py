"""Four synthetic text/pseudocode review cases; live mode requires explicit approval."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
CASES = [
    ("calculation", "calculation", None, "计算定积分 ∫₀¹ 2x dx。",
     "我的过程：2x的原函数是x，代入上下限1和0，最终得到1。", ["最终数值碰巧一致，但原函数错误", "检查求导是否回到2x"]),
    ("proof", "proof", None, "证明：级数绝对收敛蕴含收敛。",
     "我证明：先假定sum(a_n)收敛，所以sum(abs(a_n))收敛，因此原命题成立。", ["偷换前提", "普通收敛不蕴含绝对收敛"]),
    ("concept", "subjective", "concept", "解释TCP可靠传输是否保证固定时延。",
     "我认为TCP可靠就是每个数据包必定在200毫秒内到达，超时重传保证这个上限。", ["可靠传输不保证固定时延", "重传不能保证200毫秒上限"]),
    ("algorithm", "subjective", "algorithm", "审阅升序数组二分查找：未找到返回-1。",
     "伪代码：l=0;r=n-1;while l<=r: mid=(l+r)//2; if a[mid]==x:return mid; if a[mid]<x:l=mid; else:r=mid; return -1。我认为必定终止。",
     ["边界应跨过mid", "可能不终止", "空数组与找不到目标"]),
]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--allow-synthetic-data", action="store_true")
    parser.add_argument("--limit", type=int, default=4)
    args = parser.parse_args()
    if not args.live or not args.allow_synthetic_data:
        parser.error("需事先获准，并显式传 --live --allow-synthetic-data")
    if not 1 <= args.limit <= 4: parser.error("最多四个合成审阅场景")
    os.environ["APP_ENV"] = "test"
    os.environ.setdefault("TEST_DATABASE_URL", "postgresql+psycopg://kaoyan:kaoyan_dev_pw@127.0.0.1:5433/kaoyan_test")
    from backend.config import get_settings
    from backend.services.model_settings_service import load_local_settings
    from backend.chat.service import provider_from_settings
    from backend.models.learning import KnowledgePoint, KpState, Question, DailyPlan, PracticeItem, LearningEvent, QuestionAttempt
    from backend.services.process_review_service import review_text_process, latest_text_process_review
    from scripts.run_learning_agent_eval import isolated_factory
    from sqlalchemy import select, func
    get_settings.cache_clear()
    settings = get_settings()
    provider = provider_from_settings(load_local_settings(settings.model_copy(update={"app_env": "dev"})))
    output = ROOT / "eval/reports" / f"process-review-live-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-{uuid4().hex[:6]}.json"
    records = []
    def save(complete=False):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps({"synthetic_only": True, "complete": complete, "cases": records,
            "quality_claim": "工程约束检查不是内容正确性评分；需人工对照expected_review_points"}, ensure_ascii=False, indent=2), encoding="utf-8")
    save()
    with isolated_factory(str(settings.active_database_url)) as factory:
        for index, (name, kind, subtype, stem, work, expected) in enumerate(CASES[:args.limit]):
            now = datetime.now(timezone.utc)
            with factory.begin() as db:
                kp = KnowledgePoint(code=f"eval.review.{name}", name=f"合成审阅{name}", subject="合成")
                db.add(kp); db.flush()
                db.add(KpState(kp_id=kp.id))
                q = Question(kp_id=kp.id, question_type=kind, stem=stem, correct_answer=None,
                             explanation="合成参考解析，不在未查看时发送", estimated_minutes=10)
                plan = DailyPlan(study_date=f"2099-01-{index+1:02d}", status="active")
                db.add_all([q, plan]); db.flush()
                item = PracticeItem(plan_id=plan.id, question_id=q.id, kp_id=kp.id, ordinal=1)
                db.add(item); db.flush(); item_id, kp_id = item.id, kp.id
            try:
                result = review_text_process(factory, item_id=item_id, work_text=work, subjective_kind=subtype,
                    idempotency_key=f"synthetic-review-{name}", now=now, provider=provider)
                with factory() as db:
                    event = db.scalar(select(LearningEvent).where(LearningEvent.source_id == item_id))
                    record = {"id": name, "feedback": result.feedback, "expected_review_points": expected,
                              "model_trace": event.payload["model_trace"], "engineering_checks": {
                        "item_not_completed": db.get(PracticeItem, item_id).completed_at is None,
                        "no_attempts": db.scalar(select(func.count()).select_from(QuestionAttempt)) == 0,
                        "no_mastery_confirmation": db.get(KpState, kp_id).evidence_window == [],
                        "raw_work_not_stored": event.payload["raw_work_stored"] is False,
                        "readonly_recovery": latest_text_process_review(factory, item_id=item_id).review_id == result.review_id}}
            except Exception as exc:
                record = {"id": name, "error_type": type(exc).__name__, "expected_review_points": expected}
            records.append(record); save(); print(f"{name}: {'error' if 'error_type' in record else 'reviewed'}", flush=True)
    save(True); print(f"Report: {output}")
    return 1 if any("error_type" in r or not all(r["engineering_checks"].values()) for r in records) else 0

if __name__ == "__main__": raise SystemExit(main())
