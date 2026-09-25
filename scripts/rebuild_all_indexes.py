"""通过接口重建所有资料的索引。

什么时候需要它：
向量库（`storage/chroma`）是可重建的派生索引。如果它损坏或被删掉
（上面那种「进程被强杀导致 HNSW 文件不一致」的情况就会这样），
正文与分块都还在 PostgreSQL 里，重跑索引即可完整恢复，不需要重新上传。

用法（项目根执行，需后端已启动）：
    python scripts\\rebuild_all_indexes.py
    python scripts\\rebuild_all_indexes.py --only failed
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8000"
READY_TIMEOUT_SECONDS = 600
POLL_INTERVAL_SECONDS = 2


def call(method: str, path: str) -> tuple[int, dict | None]:
    request = urllib.request.Request(f"{BASE}{path}", method=method)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            raw = response.read()
            return response.status, (json.loads(raw.decode("utf-8")) if raw else None)
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8", "replace")
        try:
            return error.code, json.loads(raw)
        except json.JSONDecodeError:
            return error.code, {"raw": raw}


def main() -> int:
    parser = argparse.ArgumentParser(description="重建所有资料的索引")
    parser.add_argument("--only", default="all", help="all | ready | failed")
    args = parser.parse_args()

    status, payload = call("GET", "/api/materials")
    if status != 200 or payload is None:
        print(f"读取资料列表失败：HTTP {status}", file=sys.stderr)
        return 1

    targets = [
        item
        for item in payload["items"]
        if args.only == "all" or item["status"] == args.only
    ]
    if not targets:
        print("没有需要重建的资料。")
        return 0

    print(f"将重建 {len(targets)} 份资料的索引：")
    for item in targets:
        print(f"  - {item['title']}（当前 {item['status']}）")
        code, _ = call("POST", f"/api/materials/{item['id']}/reindex")
        if code >= 400:
            print(f"    提交失败：HTTP {code}")

    deadline = time.time() + READY_TIMEOUT_SECONDS
    pending = {item["id"]: item["title"] for item in targets}
    while pending and time.time() < deadline:
        time.sleep(POLL_INTERVAL_SECONDS)
        code, listing = call("GET", "/api/materials")
        if code != 200 or listing is None:
            continue
        by_id = {item["id"]: item for item in listing["items"]}
        for material_id in list(pending):
            current = by_id.get(material_id)
            if current is None:
                pending.pop(material_id)
                continue
            if current["status"] in {"ready", "failed"}:
                chunks = call("GET", f"/api/materials/{material_id}")[1] or {}
                print(
                    f"  [{current['status']}] {current['title']}："
                    f"块数 {chunks.get('chunk_count')}，版本 {current['active_index_version']}"
                )
                pending.pop(material_id)

    if pending:
        print(f"仍有 {len(pending)} 份未完成（超时）：{list(pending.values())}", file=sys.stderr)
        return 1
    print("全部完成。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
