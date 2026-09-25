"""查看本地开发环境状态：服务、后端健康检查、今日学习、毕业条件。

用法（项目根执行）：
    python scripts/status.py
或在 CMD 里：
    scripts\\status.cmd
"""

from __future__ import annotations

import json
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PORTS = {5433: "PostgreSQL", 8000: "后端 FastAPI", 5173: "前端 Vite"}


def port_open(port: int) -> bool:
    """尝试建立 TCP 连接判断端口是否在监听。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def http_json(url: str) -> dict | None:
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return json.load(response)
    except (urllib.error.URLError, TimeoutError, ValueError):
        return None


def show_services() -> None:
    print("=== 服务状态 ===")
    for port, label in PORTS.items():
        mark = "运行中" if port_open(port) else "未运行"
        print(f"  {label:<16} 127.0.0.1:{port}  {mark}")


def show_health() -> None:
    print("\n=== 后端健康检查 ===")
    data = http_json("http://127.0.0.1:8000/api/health")
    if data is None:
        print("  未响应（后端可能未启动）")
        return
    print(f"  status={data.get('status')}  database={data.get('database')}")


def show_today() -> None:
    print("\n=== 今日学习 ===")
    data = http_json("http://127.0.0.1:8000/api/plans/today")
    if data is None:
        print("  查询失败（后端未启动？）")
        return
    status = data.get("status")
    if status == "setup":
        print(f"  status = setup（还没有练习卷，推荐 {len(data.get('recommendations', []))} 个知识点）")
        return
    print(
        f"  status = {status}"
        f"  完成 {data.get('completed_count')} / {data.get('total_count')}"
    )
    for item in data.get("items", []):
        done = "已完成" if item["completed"] else "待做"
        variant = "变式题" if item["is_variant"] else "基础题"
        grade = item.get("latest_self_grade") or "-"
        print(f"    第{item['ordinal']}题 {variant} {done} 自评={grade} | {item['kp_name']}")


def show_graduation() -> None:
    print("\n=== 毕业条件 ===")
    from backend.config import get_settings
    from backend.db import create_db_engine, create_session_factory
    from scripts.shift_learning_days import report_graduation_state

    engine = create_db_engine(str(get_settings().active_database_url))
    try:
        with create_session_factory(engine)() as db:
            report_graduation_state(db)
    finally:
        engine.dispose()


def main() -> None:
    show_services()
    show_health()
    show_today()
    show_graduation()
    print("提示：把历史时间前移可以用 scripts\\shift-days.cmd 2（跨天毕业测试）。")


if __name__ == "__main__":
    main()