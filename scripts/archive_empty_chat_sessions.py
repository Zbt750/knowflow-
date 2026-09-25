"""开发 / 验收辅助：归档「一条消息都没有」的问答会话。

为什么需要它：页面早期是「点新建对话 / 切换资料范围就立刻创建会话」，
用户每点一次就留下一条空会话。真实开发库跑下来积累了 94 条未归档会话，
其中 **46 条完全没有任何消息**（builtin 23 条 / user 23 条）——
历史列表一半是噪声，人工验收时根本翻不动。

怎么处理：**归档**（只置 `archived_at`），归档后不再出现在会话列表里。

⚠️ 注意：这里**不再**与 `DELETE /api/chat/sessions/{id}` 同语义 —— 该端点自
2026-09-20 起改为**物理删除**（见 `docs/reference-build-changes.md` D-28）。
本脚本**仍然刻意选择归档**：它清理的是「一条消息都没有」的空壳，
归档足以让它们从列表消失，而且万一判断有误也仍然可回溯。
代价是这些归档行会永久不再出现、也没有 UI 能看到；是否需要一并硬删由后续决定。

页面侧已同步修正为「会话推迟到发出第一条问题时才落库」，所以这个脚本是
一次性的历史清理；同时它保持幂等，可以随时重跑。

用法（项目根执行）：
    python scripts/archive_empty_chat_sessions.py          # 先看会归档哪些
    python scripts/archive_empty_chat_sessions.py --apply  # 真的归档
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from backend.config import get_settings  # noqa: E402
from backend.db import create_db_engine, create_session_factory  # noqa: E402
from backend.models.chat import ChatMessage, ChatSession  # noqa: E402


def empty_sessions(db: Session) -> list[ChatSession]:
    """未归档、且没有任何消息的会话。

    用 EXISTS 而不是先查全部再过滤：会话数量会随使用增长，不该全量拉进内存。
    """
    no_message = ~(
        select(ChatMessage.id)
        .where(ChatMessage.session_id == ChatSession.id)
        .exists()
    )
    return list(
        db.scalars(
            select(ChatSession)
            .where(ChatSession.archived_at.is_(None), no_message)
            .order_by(ChatSession.created_at)
        ).all()
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply",
        action="store_true",
        help="真的写归档时间；不加这个参数只做预演（不修改任何数据）",
    )
    args = parser.parse_args()

    settings = get_settings()
    engine = create_db_engine(str(settings.active_database_url))
    session_factory = create_session_factory(engine)
    try:
        with session_factory() as db:
            targets = empty_sessions(db)
            total = db.scalar(
                select(func.count())
                .select_from(ChatSession)
                .where(ChatSession.archived_at.is_(None))
            )
            by_mode = Counter(row.mode for row in targets)
            print(f"未归档会话共 {total} 条，其中没有任何消息的 {len(targets)} 条：")
            for mode, count in sorted(by_mode.items()):
                print(f"    {mode}: {count} 条")
            if not targets:
                print("没有需要归档的空会话。")
                return 0

            if not args.apply:
                print("\n预演结束，未修改任何数据。确认后加 --apply 执行。")
                return 0

            now = datetime.now(timezone.utc)
            for row in targets:
                row.archived_at = now
            db.commit()
            print(f"\n已归档 {len(targets)} 条空会话（不物理删除，问答与引用记录仍可追溯）。")
            return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
