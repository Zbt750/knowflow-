"""开发 / 测试辅助：清空「今日练习卷」与练习历史，让主流程可以重复演示。

用途：前端端到端测试或手工验收前，把今天恢复成“还没有练习卷”的状态。
注意：只删除计划、卷内题目引用、练习历史与审计事件；**知识点、题库与掌握度投影保留**。
生产代码不暴露任何重置接口，因此这个动作只能由本机脚本显式执行。

用法（仅测试环境、项目根执行）：
    APP_ENV=test ALLOW_TEST_DATA_RESET=1 python scripts/reset_today.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select, text  # noqa: E402

from backend.config import get_settings  # noqa: E402
from backend.db import create_db_engine, create_session_factory  # noqa: E402
from backend.models.learning import KnowledgePoint, KpState  # noqa: E402


def reset_today(db) -> dict[str, int]:
    """删除练习卷相关数据，并把所有叶子的状态投影复位为未学习。"""
    counts: dict[str, int] = {}
    for table in ("question_attempts", "learning_events", "practice_items", "daily_plans"):
        result = db.execute(text(f"DELETE FROM {table}"))
        counts[table] = result.rowcount or 0

    # 状态投影复位：窗口、基础确认、毕业时间都要一起清掉，否则会出现“没有练习卷但已毕业”。
    reset = 0
    for state in db.scalars(select(KpState)).all():
        state.state = "unseen"
        state.evidence_window = []
        state.review_stage = 0
        state.next_review_at = None
        state.mastered_at = None
        state.node_self_grade = None
        state.manual_credit_count = 0
        state.manual_confirmed_at = None
        reset += 1
    counts["kp_states_reset"] = reset
    counts["leaves"] = len(
        db.scalars(select(KnowledgePoint.id).where(KnowledgePoint.is_assessable.is_(True))).all()
    )
    return counts


def main() -> None:
    # 这是破坏性重置：测试夹具会显式传入两个开关；手工执行也必须明确承认
    # 自己面对的是测试库。不能只相信调用方，因为一条默认命令就可能清空开发学习记录。
    if os.environ.get("APP_ENV") != "test" or os.environ.get("ALLOW_TEST_DATA_RESET") != "1":
        raise SystemExit(
            "拒绝重置：仅允许 APP_ENV=test 且 ALLOW_TEST_DATA_RESET=1 时运行。"
        )
    settings = get_settings()
    engine = create_db_engine(str(settings.active_database_url))
    session_factory = create_session_factory(engine)
    try:
        with session_factory() as db:
            counts = reset_today(db)
            db.commit()
            print(
                "已重置今日数据："
                + "，".join(f"{key}={value}" for key, value in counts.items())
            )
    finally:
        engine.dispose()

if __name__ == "__main__":
    main()
