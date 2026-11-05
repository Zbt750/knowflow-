"""跑测试前的环境检查。

这个脚本区分两种前提相反的测试：

1. 后端单元/集成测试（pytest）使用独立的 ``kaoyan_test`` 库，根本不需要后端在跑。
2. 前端端到端测试（Playwright）必须连接一套 ``APP_ENV=test`` 的独立后端；
   它会重置今日练习数据，因此绝不能指向开发或生产服务。

这里只做检查与提醒，不自动启停进程 —— 擅自结束用户正在用的服务比资源竞争更糟。

用法：
    python scripts/check_test_env.py                # 提醒模式，永远返回 0
    python scripts/check_test_env.py --strict       # 要求开发后端未运行
    python scripts/check_test_env.py --need-backend # 要求 8001 上的 test 后端已运行
"""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request

DEV_BASE = "http://127.0.0.1:8000"
E2E_BASE = "http://127.0.0.1:8001"

BACKEND_BUSY_WARNING = (
    "[环境检查] 检测到开发后端正在运行（127.0.0.1:8000）。\n"
    "  pytest 使用独立的 kaoyan_test 库，不需要开发后端；\n"
    "  后端会占用嵌入模型与 Chroma 的内存，建议先停掉开发后端，再跑 pytest。"
)

E2E_BACKEND_MISSING_WARNING = (
    "[环境检查] 隔离测试后端不可用（127.0.0.1:8001，APP_ENV=test）。\n"
    "  Playwright 会重置测试库里的今日练习数据，拒绝连接开发/生产服务。\n"
    "  请启动 APP_ENV=test、TEST_DATABASE_URL 指向 *_test 的独立后端后再运行 e2e。"
)


def backend_environment(base: str) -> str | None:
    try:
        with urllib.request.urlopen(f"{base}/api/health", timeout=2) as response:
            if response.status != 200:
                return None
            payload = json.loads(response.read().decode("utf-8"))
            environment = payload.get("environment")
            return environment if isinstance(environment, str) else None
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="测试前环境检查")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--strict",
        action="store_true",
        help="要求开发后端未运行；若在跑则以非零码退出（pytest 的前提）",
    )
    mode.add_argument(
        "--need-backend",
        action="store_true",
        help="要求 8001 上 APP_ENV=test 的后端已运行（e2e 的前提）",
    )
    args = parser.parse_args()

    if args.need_backend:
        if backend_environment(E2E_BASE) == "test":
            print("[环境检查] 隔离 test 后端已运行，符合 e2e 前提。")
            return 0
        print(E2E_BACKEND_MISSING_WARNING)
        return 1

    development_running = backend_environment(DEV_BASE) is not None
    if not development_running:
        print("[环境检查] 开发后端未运行，符合 pytest 前提。")
        return 0

    print(BACKEND_BUSY_WARNING)
    return 1 if args.strict else 0


if __name__ == "__main__":
    raise SystemExit(main())
