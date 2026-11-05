"""统一锁顺序：计划 -> 练习项，串行维护整卷完成状态。"""
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.orm import Session
from backend.models.learning import DailyPlan, PracticeItem


def lock_practice_item(db: Session, item_id: UUID) -> PracticeItem:
    plan_id = db.scalar(select(PracticeItem.plan_id).where(PracticeItem.id == item_id))
    if plan_id is None:
        source_id = db.scalar(select(PracticeItem.retry_source_id).where(PracticeItem.id == item_id))
        if source_id is None: raise ValueError("practice_item_not_found")
        lock_practice_item(db, source_id)
    else:
        db.scalar(select(DailyPlan).where(DailyPlan.id == plan_id).with_for_update())
    # Keep caller changes such as answer_revealed_at before refreshing a cached
    # item. Flush only after the plan lock, preserving the global lock order.
    db.flush()
    item = db.scalar(select(PracticeItem).where(PracticeItem.id == item_id).with_for_update()
                     .execution_options(populate_existing=True))
    if item is None:
        raise ValueError("practice_item_not_found")
    if item.removed_at is not None:
        raise ValueError("practice_item_not_found")
    return item
