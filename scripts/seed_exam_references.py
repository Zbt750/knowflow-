"""仅导入历年题号与知识点来源关联，不运行其它题库或资料种子任务。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.config import get_settings  # noqa: E402
from backend.db import create_db_engine, create_session_factory  # noqa: E402
from backend.services.exam_reference_service import sync_exam_reference_index  # noqa: E402


def main() -> None:
    settings = get_settings()
    engine = create_db_engine(str(settings.active_database_url))
    try:
        with create_session_factory(engine)() as db:
            try:
                result = sync_exam_reference_index(db)
                db.commit()
            except Exception:
                db.rollback()
                raise
        print(
            "历年题号索引已同步："
            f"节点新建 {result['nodes_created']} / 更新 {result['nodes_updated']}，"
            f"题号关联新建 {result['references_created']} / 更新 {result['references_updated']}"
        )
        print("未复制题干或答案、未创建虚构 Question；索引叶子会建立掌握度策略供原卷自评计入毕业进度。")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
