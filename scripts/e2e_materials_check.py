"""阶段 C 端到端验收：真实模型 + 真实向量库 + 真实 HTTP 接口。

**这个脚本绝不删除用户自己的资料。** 它只清理自己创建的那一条（带测试前缀），
并在开始时记录基线数量、结束时核对用户的资料一份都没少。

做五件事：
1. 健康检查：确认数据库、检索栈与后台任务线程都就绪；
2. 记录基线：当前有哪些资料（用户自己的数据）；
3. 上传内置讲义（真实 md 文件），轮询到 ready，并核对 chunks 与知识点关联；
4. 用真实混合检索跑几个语义查询，打印命中的标题路径与出处；
5. 清理自己创建的资料，并断言用户原有资料没有被动过。

用法：
    python scripts/e2e_materials_check.py
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[1]
BASE_URL = "http://127.0.0.1:8000"
LECTURE = ROOT / "seed" / "materials" / "gaoshu-lecture-01.md"

# 测试资料的标题前缀：既是清理时的识别标记，也让用户一眼看出哪些是测试产物。
# 前端 e2e 夹具用的是同一个前缀（frontend/e2e/fixtures.ts 的 E2E_PREFIX）。
TEST_TITLE_PREFIX = "E2E-验收脚本-"

# 用真实语义提问，而不是直接复制原文：这样才检验得到向量路是否有效。
QUERIES = (
    "什么时候不能用洛必达法则",
    "加减法里能不能直接替换等价无穷小",
    "隐函数怎么求切线方程",
    "等比级数什么时候收敛",
    "行列式数乘以后怎么变化",
)

READY_TIMEOUT_SECONDS = 300
# 轮询间隔要足够小：`indexing` 是个**短命中间态**，小文档可能在 1 秒内就变成
# ready。间隔太大就会整个错过它，让人误以为「中间态不可见」——
# 而实际只是没采样到（这一点在修复 P4 时踩过一次）。
POLL_INTERVAL_SECONDS = 0.1


def request(method: str, path: str, *, body: bytes | None = None, headers: dict | None = None):
    url = f"{BASE_URL}{path}"
    req = urllib.request.Request(url, data=body, method=method)
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    try:
        with urllib.request.urlopen(req, timeout=300) as response:
            raw = response.read()
            if not raw:
                return response.status, None
            return response.status, json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8", "replace")
        try:
            return error.code, json.loads(raw)
        except json.JSONDecodeError:
            return error.code, {"raw": raw}


def multipart(field: str, filename: str, content: bytes) -> tuple[bytes, str]:
    boundary = f"----kaoyan{uuid.uuid4().hex}"
    parts = [
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'.encode(),
        b"Content-Type: application/octet-stream\r\n\r\n",
        content,
        f"\r\n--{boundary}--\r\n".encode(),
    ]
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def step(number: int, title: str) -> None:
    print(f"\n=== {number}. {title} ===")


def list_materials() -> list[dict]:
    _, payload = request("GET", "/api/materials")
    return (payload or {}).get("items") or []


def main() -> int:
    failures: list[str] = []

    def check(condition: bool, label: str) -> None:
        print(f"  [{'OK ' if condition else 'FAIL'}] {label}")
        if not condition:
            failures.append(label)

    step(1, "健康检查")
    status, health = request("GET", "/api/health")
    print(f"  HTTP {status} {health}")
    check(status == 200, "健康检查返回 200")
    check(bool(health) and health.get("database") == "connected", "数据库已连接")
    check(
        bool(health) and health.get("retrieval") == "ready",
        "检索栈已就绪（真实 embedding 已加载）",
    )
    check(bool(health) and health.get("worker") == "running", "后台任务线程在运行")

    if failures:
        print("\n前置条件不满足，后续步骤无法执行。")
        return 1

    step(2, "记录基线（用户已有资料）")
    baseline = list_materials()
    baseline_user = [
        item for item in baseline if not item["title"].startswith(TEST_TITLE_PREFIX)
    ]
    print(f"  当前共 {len(baseline)} 份，其中用户自己的 {len(baseline_user)} 份")
    for item in baseline_user:
        print(f"    - {item['title']}（{item['status']}）")

    step(3, "上传内置讲义并等待处理完成")
    test_title = f"{TEST_TITLE_PREFIX}高等数学核心考点讲义"
    content = LECTURE.read_bytes()
    body, content_type = multipart("file", LECTURE.name, content)
    query = urllib.parse.urlencode({"title": test_title, "source_type": "builtin"})
    status, uploaded = request(
        "POST", f"/api/materials?{query}", body=body, headers={"Content-Type": content_type}
    )
    print(f"  HTTP {status} material={uploaded and uploaded['material']['id']}")
    check(status == 201, "上传返回 201")
    material_id = uploaded["material"]["id"]

    deadline = time.time() + READY_TIMEOUT_SECONDS
    detail = None
    # 顺便记录观察到的状态轨迹：它是「indexing 中间态可见」的直接证据。
    seen_states: list[str] = []
    while time.time() < deadline:
        _, detail = request("GET", f"/api/materials/{material_id}")
        state = detail["status"]
        if not seen_states or seen_states[-1] != state:
            seen_states.append(state)
        if state in {"ready", "failed"}:
            break
        time.sleep(0.5)
    print(f"  状态轨迹：{' → '.join(seen_states)}")
    print(
        f"  最终状态：{detail['status']}，索引版本 {detail['active_index_version']}，"
        f"块数 {detail['chunk_count']}"
    )
    check(detail["status"] == "ready", "资料处理完成且状态为 ready")
    check(bool(detail["active_index_version"]), "已激活索引版本")
    check(detail["chunk_count"] > 0, "产生了 chunk")
    # 中间态必须真实可见，否则前端「建立索引中」标签是死代码。
    check("indexing" in seen_states, "观察到 indexing 中间态（对 API 可见）")
    if detail.get("latest_job"):
        print(
            f"  最近任务：{detail['latest_job']['job_type']} {detail['latest_job']['status']}"
            f" 尝试 {detail['latest_job']['attempts']}/{detail['latest_job']['max_attempts']}"
        )

    step(4, "核对 chunk 与知识点关联")
    _, chunks = request("GET", f"/api/materials/{material_id}/chunks?limit=100")
    print(f"  块总数 {chunks['total']}，前 3 块：")
    for item in chunks["items"][:3]:
        path = " / ".join(item["heading_path"])
        print(f"    #{item['ordinal']:>2} [{path}] kp={item['kp_hint_code']} {item['char_count']} 字")
    check(chunks["total"] > 0, "块列表非空")
    with_kp = [item for item in chunks["items"] if item["kp_hint_code"]]
    check(len(with_kp) > 0, "至少有一个块带知识点标记")

    step(5, "真实混合检索")
    for text in QUERIES:
        status, payload = request(
            "POST",
            "/api/materials/search",
            body=json.dumps({"query": text, "top_k": 3}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        print(
            f"\n  查询：{text}  → HTTP {status}，命中 {len(payload['hits'])} 条"
            f"（向量候选 {payload['vector_candidates']}，"
            f"关键词候选 {payload['keyword_candidates']}，降级 {payload['degraded']}）"
        )
        check(status == 200 and len(payload["hits"]) > 0, f"查询有结果：{text}")
        for hit in payload["hits"]:
            path = " / ".join(hit["heading_path"])
            excerpt = hit["content"].replace("\n", " ")[:64]
            print(
                f"    - [{path}] 向量名次={hit['vector_rank']} "
                f"关键词名次={hit['keyword_rank']} 知识点={len(hit['kp_ids'])} {excerpt}…"
            )

    step(6, "只清理本次创建的测试资料，并确认用户资料未被触碰")
    status, _ = request("DELETE", f"/api/materials/{material_id}")
    print(f"  删除测试资料返回 HTTP {status}")
    check(status == 204, "删除测试资料返回 204")

    after = list_materials()
    after_ids = {item["id"] for item in after}
    check(material_id not in after_ids, "测试资料已从列表移除")

    # 用户原有资料必须一份不少、状态不变。
    for item in baseline_user:
        still = next((x for x in after if x["id"] == item["id"]), None)
        check(still is not None, f"用户资料仍在：{item['title']}")
        if still is not None:
            check(still["status"] == item["status"], f"用户资料状态未变：{item['title']}")
    print(f"  结束时共 {len(after)} 份（基线里用户自己的 {len(baseline_user)} 份）")

    print("\n" + "=" * 60)
    if failures:
        print(f"验收失败：{len(failures)} 项")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("阶段 C 端到端验收全部通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
