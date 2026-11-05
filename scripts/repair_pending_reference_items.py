"""Repair only untouched pointer-only items in a specified local development plan.

Preserve all submitted/history-bearing items. Write the recovery receipt before
the transaction commits; never change answers, attempts or knowledge state.
"""
import argparse
from datetime import date, datetime, timezone
import json
from pathlib import Path
import sys
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.config import get_settings
from backend.models.learning import DailyPlan, PracticeItem, QuestionAttempt, LearningEvent
from backend.services.practice_service import online_question_for_reference


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", type=date.fromisoformat, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    settings = get_settings()
    url = make_url(str(settings.active_database_url))
    if settings.app_env != "dev" or url.host not in {"127.0.0.1", "localhost"} or url.database != "kaoyan":
        raise ValueError("Only the local kaoyan development database is supported")
    if args.apply:
        if args.report is None:
            raise ValueError("A new local recovery receipt is required")
        path = args.report.resolve()
        if not path.is_relative_to((ROOT / "storage").resolve()) or path.exists():
            raise ValueError("Use a new receipt under ignored storage")
    result = {"date": args.date.isoformat(), "apply": args.apply, "changes": [], "preserved": []}
    with Session(create_engine(str(settings.active_database_url))) as db:
        plan = db.scalar(select(DailyPlan).where(DailyPlan.study_date == args.date.isoformat()).with_for_update())
        if plan:
            result["before_plan_status"] = plan.status
            items = list(db.scalars(select(PracticeItem).where(PracticeItem.plan_id == plan.id)
                .order_by(PracticeItem.ordinal).with_for_update()))
            existing = {i.question_id for i in items if i.question_id is not None}
            for item in items:
                if item.question_id is not None or item.exam_reference_id is None:
                    continue
                acted = (item.completed_at is not None or item.answer_revealed_at is not None
                    or db.scalar(select(QuestionAttempt.id).where(QuestionAttempt.practice_item_id == item.id).limit(1))
                    or db.scalar(select(LearningEvent.id).where(LearningEvent.source_id == item.id).limit(1)))
                if acted:
                    result["preserved"].append(str(item.id))
                    continue
                before = {c.name: getattr(item, c.name) for c in PracticeItem.__table__.columns}
                question = online_question_for_reference(db, item.exam_reference)
                action = "replace_with_online_question" if question and question.id not in existing else "remove_empty_pointer"
                result["changes"].append({"action": action, "before": before,
                    "question_id": str(question.id) if question else None})
                if args.apply:
                    if action == "replace_with_online_question":
                        item.question_id, item.kp_id, item.exam_reference_id = question.id, question.kp_id, None
                        existing.add(question.id)
                    else:
                        db.delete(item)
            if args.apply:
                db.flush()
                remaining = list(db.scalars(select(PracticeItem).where(PracticeItem.plan_id == plan.id)))
                plan.status = "active" if any(i.completed_at is None for i in remaining) else "completed"
                result["after_plan_status"] = plan.status
        if args.apply:
            result["saved_at"] = datetime.now(timezone.utc).isoformat()
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("x", encoding="utf-8") as stream:
                json.dump(result, stream, ensure_ascii=False, indent=2, default=str)
            db.commit()
        else:
            db.rollback()
    print(json.dumps({"date": result["date"], "apply": args.apply,
        "changed": len(result["changes"]), "preserved": len(result["preserved"]),
        "actions": [r["action"] for r in result["changes"]]}, ensure_ascii=True))


if __name__ == "__main__":
    main()
