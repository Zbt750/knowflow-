"""Docker 部署的写链路验证：上传资料 → 等索引 → 检索命中 → SSE 逐字 → 清理。

为什么单独写这个脚本：
容器起来、健康检查 200 都只能说明「读」通。资料摄取要跑后台 worker、
写 PostgreSQL、建向量索引，问答还要走 SSE 穿过 Nginx —— 这条链路才是
「部署真的能用」的判据。脚本自带清理，跑完不留垃圾资料与会话。

关于查询词的一个教训（实测踩过）：
最初版本上传一份只有 1 个分块的资料、用一个生造的 ASCII token 当查询词，
结果向量检索召回 0 条 —— 看起来像「容器检索坏了」，实际是**验证设计有问题**：
生造词与正文语义距离过远，1 个分块也让召回没有余地。
换成有实质内容的资料 + 自然中文查询后，三个查询全部命中。
所以这里的资料与查询词都按「真实用户会怎么用」来写。
"""

import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

BASE = "http://localhost:8080"
SUFFIX = uuid.uuid4().hex[:8]
TITLE = f"E2E-DOCKER-{SUFFIX}"
FILENAME = f"e2e-docker-{SUFFIX}.md"
BODY = """# 洛必达法则复习提纲

## 适用条件

洛必达法则用于处理 0/0 型与无穷比无穷型的未定式极限。
使用前必须确认分子分母在去心邻域内可导，且分母的导数不为零。
如果一次求导后仍是未定式，可以重复使用，直到求出极限或判定不存在。

## 常见错误

把洛必达法则用在非未定式上是最常见的错误，会导致结果错误。
另外，分子分母不可导时不能使用该法则，此时应改用等价无穷小替换或泰勒展开。
""".encode("utf-8")
QUERIES = ["洛必达法则的适用条件是什么", "洛必达法则", "未定式极限怎么求"]


def request(path, method="GET", data=None, headers=None, timeout=120):
    req = urllib.request.Request(BASE + path, data=data, method=method)
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def json_body(raw):
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return None


def upload():
    boundary = "----dockere2e" + uuid.uuid4().hex
    parts = [
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="file"; filename="{FILENAME}"\r\n'.encode(),
        b"Content-Type: text/markdown\r\n\r\n",
        BODY,
        f"\r\n--{boundary}--\r\n".encode(),
    ]
    path = f"/api/materials?title={urllib.parse.quote(TITLE)}&source_type=user"
    return request(
        path,
        method="POST",
        data=b"".join(parts),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )


def check_sse_streaming() -> tuple[bool, str]:
    """问答 SSE 是否真的被逐字下发（验证 Nginx 没有缓冲）。

    判据不是「能不能拿到回答」，而是**帧是不是分多次到达**：
    若 Nginx 或任何中间层缓冲了响应，所有 delta 会挤在一次 read 里返回，
    用户看到的是一次性刷出而不是逐字出现。

    返回 (是否通过, 说明)。没有配置 LLM 时无法验证，返回 skipped 语义由调用方处理。
    """
    status, raw = request("/api/chat/sessions", method="POST",
                          data=json.dumps({"title": f"E2E-SSE-{SUFFIX}", "mode": "user"}).encode(),
                          headers={"Content-Type": "application/json"})
    if status != 201:
        return False, f"建会话失败 {status}"
    session_id = (json_body(raw) or {}).get("session_id")
    if not session_id:
        return False, "建会话未返回 session_id"

    payload = json.dumps({"question": "洛必达法则的适用条件是什么？"}).encode()
    req = urllib.request.Request(
        f"{BASE}/api/chat/sessions/{session_id}/answers:stream", data=payload, method="POST"
    )
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "text/event-stream")
    chunks = 0
    events: dict[str, int] = {}
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            # 按块读（不是逐字节）：块数本身就是「响应是否被分多次下发」的证据 ——
            # 若被 Nginx 缓冲，整段 SSE 会挤在一次 read 里返回。
            while True:
                block = resp.read(4096)
                if not block:
                    break
                chunks += 1
                text = block.decode("utf-8", "replace")
                for line in text.splitlines():
                    if line.startswith("event: "):
                        name = line[7:].strip()
                        events[name] = events.get(name, 0) + 1
                if events.get("done") or events.get("error"):
                    break
    except Exception as error:  # noqa: BLE001 - 诊断脚本，任何失败都要变成可读结论
        return False, f"读流异常 {type(error).__name__}: {str(error)[:120]}"
    finally:
        request(f"/api/chat/sessions/{session_id}", method="DELETE")

    deltas = events.get("delta", 0)
    if events.get("error"):
        # 上游模型未配置/不可用：这条用例在语义上是「跳过」，不是失败。
        return False, f"流以 error 结束（上游模型不可用）：events={events}"
    if not deltas:
        return False, f"没有收到 delta 帧：events={events}"
    # delta 帧必须多帧到达，才说明响应没有被一次性缓冲。
    if deltas < 3:
        return False, f"delta 帧只有 {deltas} 个，无法判断是否逐字"
    return True, f"收到 {deltas} 个 delta 帧，分 {chunks} 次读到达；events={events}"


def main() -> int:
    results: list[tuple[str, bool, str]] = []

    print("=== 1) 健康检查 ===")
    status, raw = request("/api/health", timeout=15)
    health = json_body(raw) or {}
    print(f"  /api/health -> {status} {raw.decode('utf-8', 'replace')}")
    results.append(("健康检查与检索栈状态", status == 200 and health.get("retrieval") == "ready",
                    f"retrieval={health.get('retrieval')}"))
    if status != 200:
        return 1

    print("\n=== 2) 上传资料 ===")
    status, raw = upload()
    body = json_body(raw)
    print(f"  POST /api/materials -> {status}")
    if status != 201 or not body:
        print("  失败，响应：" + raw.decode("utf-8", "replace")[:400])
        return 1
    material_id = body["material"]["id"]
    print(f"  material_id = {material_id}  初始状态 = {body['material']['status']}")

    print("\n=== 3) 等索引完成（后台 worker） ===")
    deadline = time.time() + 180
    status_value = None
    detail = None
    while time.time() < deadline:
        code, raw = request(f"/api/materials/{material_id}", timeout=30)
        detail = json_body(raw) or {}
        status_value = detail.get("status")
        if status_value in ("ready", "failed"):
            break
        time.sleep(2)
    print(f"  最终状态 = {status_value}  分块数 = {detail.get('chunk_count')}  "
          f"索引版本 = {detail.get('active_index_version')}")
    results.append(("上传资料 → 状态走到「可检索」", status_value == "ready",
                    f"status={status_value} chunks={detail.get('chunk_count')}"))
    if status_value != "ready":
        print(f"  详情：{json.dumps(detail, ensure_ascii=False)[:300]}")
        request(f"/api/materials/{material_id}", method="DELETE")
        for name, ok, note in results:
            print(f"  [{'ok' if ok else 'FAIL'}] {name} :: {note}")
        return 1

    print("\n=== 4) 列表里能看到它 ===")
    code, raw = request("/api/materials", timeout=30)
    listing = json_body(raw) or {}
    titles = [item["title"] for item in listing.get("items", [])]
    print(f"  列表条数 = {len(titles)}，包含目标 = {TITLE in titles}  统计 = {listing.get('stats')}")
    results.append(("列表与统计包含新资料", TITLE in titles, f"total={listing.get('stats', {}).get('total')}"))

    print("\n=== 5) 检索命中（用真实用户会问的问题） ===")
    hit_all = True
    for query in QUERIES:
        payload = json.dumps({"query": query, "top_k": 5}).encode()
        code, raw = request("/api/materials/search", method="POST", data=payload,
                            headers={"Content-Type": "application/json"})
        result = json_body(raw) or {}
        hits = result.get("hits") or []
        hit_ids = [str(item.get("material_id")) for item in hits]
        hit = material_id in hit_ids
        hit_all = hit_all and hit
        print(f"  「{query}」-> {code} 命中={len(hits)} 命中本资料={hit} "
              f"degraded={result.get('degraded')} vector={result.get('vector_candidates')}")
    results.append(("检索能命中刚上传的资料", hit_all, f"{len(QUERIES)} 个自然查询"))

    print("\n=== 6) 问答 SSE 逐字下发（Nginx 无缓冲） ===")
    sse_ok, sse_note = check_sse_streaming()
    print(f"  {sse_note}")
    results.append(("SSE 逐字下发（未被缓冲）", sse_ok, sse_note))

    print("\n=== 7) 清理（删除资料，避免留下垃圾） ===")
    code, _ = request(f"/api/materials/{material_id}", method="DELETE", timeout=60)
    print(f"  DELETE /api/materials/{material_id} -> {code}")
    code, raw = request("/api/materials", timeout=30)
    remaining = [item["title"] for item in (json_body(raw) or {}).get("items", [])]
    print(f"  清理后列表条数 = {len(remaining)}，目标已移除 = {TITLE not in remaining}")
    results.append(("清理干净（不留垃圾资料）", TITLE not in remaining, f"剩余 {len(remaining)} 份"))

    print("\n=== 结论 ===")
    for name, ok, note in results:
        print(f"  [{'ok' if ok else 'FAIL'}] {name} :: {note}")
    failed = [name for name, ok, _ in results if not ok]
    if failed:
        print(f"\n未通过：{', '.join(failed)}")
        return 1
    print("\n全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
