"""校验前端类型与后端 OpenAPI 是否已经漂移。

为什么需要它（第 17 篇 §4.1 的验收口径是「前端类型来自或校验于当前 OpenAPI」）：

导出快照与生成类型都是**手工触发的**动作，而手工动作会忘。一旦忘掉：
后端加了字段、前端类型还是旧的，`vue-tsc` 照样通过，直到运行时才发现
字段不存在 —— 那正是「手抄接口表」的老问题换了个形式。

本脚本做三段校验，任一不一致就以非零码退出：

1. 后端当前 OpenAPI  ↔  `frontend/openapi.json`
2. `frontend/openapi.json` ↔ `frontend/src/api/types.ts`
3. 快照里必须包含契约表里的关键端点（少一条说明路由没注册上）

用法：
    python scripts/check_openapi_drift.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SNAPSHOT = ROOT / "frontend" / "openapi.json"
GENERATED_TYPES = ROOT / "frontend" / "src" / "api" / "types.ts"

# 契约表里必须存在的端点。少了一条通常意味着 app.py 忘了 include_router。
REQUIRED_PATHS = (
    "/api/learning-tasks/{task_id}/confirm",
    "/api/learning-tasks",
    "/api/learning-tasks/{task_id}",
    "/api/learning-tasks/{task_id}/run",
    "/api/learning-tasks/{task_id}/cancel",
    "/api/health",
    "/api/plans/today",
    "/api/plans/today/generate",
    "/api/plans/{plan_id}/items",
    "/api/plans/{plan_id}/questions",
    "/api/practice-items/{item_id}/answer",
    "/api/practice-items/{item_id}/answer-submissions",
    "/api/practice-items/{item_id}/process-reviews",
    "/api/practice-items/{item_id}/process-reviews/latest",
    "/api/practice-items/{item_id}/answer-reveal",
    "/api/practice-items/{item_id}/self-assessments",
    "/api/knowledge/tree",
    "/api/knowledge/{kp_id}/self-assessment",
    "/api/materials",
    "/api/materials/{material_id}/chunks",
    "/api/chat/sessions",
    "/api/chat/sessions/{session_id}/answers:stream",
)


def fail(message: str) -> int:
    print(f"[漂移校验] {message}", file=sys.stderr)
    return 1


def check_snapshot_matches_app() -> int:
    """后端当前 OpenAPI 与快照是否一致（不落盘，避免校验顺手改文件）。"""
    from backend.main import app

    current = app.openapi()
    if not SNAPSHOT.exists():
        return fail(f"{SNAPSHOT.relative_to(ROOT)} 不存在；先运行 python scripts/export_openapi.py")

    stored = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    current_paths = set(current.get("paths", {}))
    stored_paths = set(stored.get("paths", {}))

    added = sorted(current_paths - stored_paths)
    removed = sorted(stored_paths - current_paths)
    if added or removed:
        detail = []
        if added:
            detail.append(f"后端新增未导出：{added}")
        if removed:
            detail.append(f"快照里多出：{removed}")
        return fail("快照已过期 —— " + "；".join(detail) + "\n  → 运行 python scripts/export_openapi.py")

    # 路径集合相同还不够：字段也可能变（例如响应多了一个属性）。
    # 直接比整份 JSON 的规范化字符串，任何差异都会被发现。
    if json.dumps(stored, sort_keys=True, ensure_ascii=False) != json.dumps(
        current, sort_keys=True, ensure_ascii=False
    ):
        return fail(
            "快照与后端 schema 内容不一致（路径相同但字段/描述已变）\n"
            "  → 运行 python scripts/export_openapi.py"
        )
    print(f"[漂移校验] 快照与后端 OpenAPI 一致（{len(current_paths)} 个端点）")
    return 0


def check_required_paths() -> int:
    if not SNAPSHOT.exists():
        return fail("快照不存在，无法校验端点完整性")
    paths = set(json.loads(SNAPSHOT.read_text(encoding="utf-8")).get("paths", {}))
    missing = [path for path in REQUIRED_PATHS if path not in paths]
    if missing:
        return fail("快照缺少契约表里的端点：" + "、".join(missing))
    print(f"[漂移校验] 契约表要求的 {len(REQUIRED_PATHS)} 个端点都在")
    return 0


def check_generated_types() -> int:
    """把 types.ts 重新生成到临时文件，与仓库里的逐字节比较。"""
    if not GENERATED_TYPES.exists():
        return fail(
            f"{GENERATED_TYPES.relative_to(ROOT)} 不存在；"
            "先运行 cd frontend && npm run generate:types"
        )
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_target = Path(temp_dir) / "types.ts"
        # 参数一律传**相对路径**：cwd 已经是 frontend/。
        # 曾传绝对路径，而项目根含中文，经 shell 传递时被百分号编码成
        # `d:\%E8%80%83...\frontend\openapi.json`，openapi-typescript 直接 ENOENT。
        # 相对路径不含非 ASCII，从根上绕开这个问题。
        result = subprocess.run(
            ["npx", "openapi-typescript", "openapi.json", "-o", str(temp_target)],
            cwd=ROOT / "frontend",
            capture_output=True,
            # 必须显式指定 UTF-8：Windows 默认用 GBK 解码子进程输出，
            # 而 npx 的输出里带 UTF-8 字符（openapi-typescript 会打印 ✨🚀）。
            # 不指定时 text=True 会在读取线程里抛 UnicodeDecodeError，
            # 结果是 stderr 变成 None，随后 .strip() 直接把脚本自己搞崩 ——
            # 报错信息完全指向"校验失败"，而真实原因只是编码。
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=True,  # Windows 上 npx 是 .cmd，必须经过 shell
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()[:400]
            return fail("重新生成类型失败：\n" + detail)
        fresh = temp_target.read_text(encoding="utf-8")
    stored = GENERATED_TYPES.read_text(encoding="utf-8")
    if fresh != stored:
        return fail(
            f"{GENERATED_TYPES.relative_to(ROOT)} 与快照不一致（已漂移）\n"
            "  → 运行 cd frontend && npm run generate:types"
        )
    print("[漂移校验] 生成的类型与快照一致")
    return 0


def main() -> int:
    for check in (check_snapshot_matches_app, check_required_paths, check_generated_types):
        code = check()
        if code != 0:
            return code
    print("[漂移校验] 通过：前端类型来自当前 OpenAPI")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
