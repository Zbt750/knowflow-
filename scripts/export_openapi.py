"""把 FastAPI 的 OpenAPI 快照写成文件；前端类型生成只读这个文件。

为什么需要它（第 17 篇 §4.1）：
前端类型必须**来自或校验于当前 OpenAPI**，而不是某个人手抄的一份接口列表。
手抄的类型会在后端改字段时静默过期 —— 编译通过、运行时才发现字段没了。
导出一份快照并据此生成类型，前端与后端的字段字典就只有一个来源。

用法：
    python scripts/export_openapi.py
    python scripts/check_openapi_drift.py    # 校验快照是否已过期
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# 直接 `python scripts\export_openapi.py` 时，sys.path[0] 是 scripts\ 而不是项目根，
# 因此 `import backend` 会失败。本目录其它脚本都显式插入项目根，这里保持一致。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.main import app  # noqa: E402

TARGET = Path("frontend/openapi.json")


def main() -> None:
    schema = app.openapi()
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    # ensure_ascii=False 保留中文描述可读；indent=2 便于人工 diff。
    TARGET.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # 排序后打印路径：人眼核对契约表是否齐全，少一条就说明路由没注册上。
    for path in sorted(schema["paths"]):
        print(path)
    print(f"已写入 {TARGET}")


if __name__ == "__main__":
    main()
