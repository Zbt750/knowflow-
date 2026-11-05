"""mastery 纯函数测试的公共工具。

关键点：所有时间都显式带时区。上海 2026-01-01 10:00 == UTC 2026-01-01 02:00。
"""

from __future__ import annotations

from datetime import datetime, timezone

# 上海 2026-01-01 10:00（学习日 01-01）
DAY1 = datetime(2026, 1, 1, 2, tzinfo=timezone.utc)
# 上海 2026-01-02 10:00（学习日 01-02）
DAY2 = datetime(2026, 1, 2, 2, tzinfo=timezone.utc)
# 上海 2026-01-03 10:00（学习日 01-03）
DAY3 = datetime(2026, 1, 3, 2, tzinfo=timezone.utc)