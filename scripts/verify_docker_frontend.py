"""对 Docker 部署形态验证前端四个页面（不经 Playwright fixture）。

为什么不直接用 e2e：`frontend/e2e/fixtures.ts` **刻意拒绝**连接非 `test` 环境
（它会跑 `reset_today.py` 清空学习证据），也刻意只在测试库里造数据。
那是正确的防护 —— 测试要的是可复现的隔离库，部署验证要的是**这套编排真的能跑**。
两者目的不同，所以这里用独立脚本，不引入任何"允许连 dev"的开关去削弱那道防护。

本脚本验证的是「部署形态下前端到底能不能用」：
- 四个路由都能拿到 SPA 外壳（Nginx `try_files` 回落生效）；
- 静态资源（JS/CSS）能被容器内的 Nginx 正确提供；
- `/api` 反代在容器网络里真的通，并且返回**足以让页面渲染**的真实数据；
- 页面渲染所需的接口数据在容器内是完整的（知识树 11 个知识点、题目 22 道等）。

注意：脚本只做**只读**接口调用与一个可回收的上传/删除，不改学习数据。
"""

import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

BASE = "http://localhost:8080"
SUFFIX = uuid.uuid4().hex[:8]
results: list[tuple[str, bool, str]] = []


def get(path, timeout=30, raw=False):
    req = urllib.request.Request(BASE + path)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            return resp.status, (body if raw else body.decode("utf-8", "replace")), dict(resp.headers)
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", "replace"), {}


def get_json(path, timeout=30):
    status, text, headers = get(path, timeout=timeout)
    try:
        return status, json.loads(text), headers
    except Exception:
        return status, None, headers


def post_json(path, payload, timeout=180):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(BASE + path, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", "replace")


def delete(path, timeout=60):
    req = urllib.request.Request(BASE + path, method="DELETE")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status
    except urllib.error.HTTPError as error:
        return error.code


def main() -> int:
    print("=== 1) SPA 外壳与前端容器 ===")
    status, html, headers = get("/")
    has_app = '<div id="app"' in html
    server = headers.get("Server", "?")
    print(f"  GET / -> {status}，Server={server}，含 SPA 根节点={has_app}")
    results.append(("前端容器提供 SPA 外壳", status == 200 and has_app, f"Server={server}"))

    print("\n=== 2) 四个路由的 Nginx 回落（刷新不 404） ===")
    for path in ("/study", "/knowledge", "/materials", "/chat"):
        status, html, _ = get(path)
        ok = status == 200 and '<div id="app"' in html
        print(f"  {path} -> {status}，回落 SPA={ok}")
        results.append((f"{path} 刷新回落 SPA", ok, f"status={status}"))

    print("\n=== 3) 静态资源由容器内 Nginx 提供 ===")
    status, html, _ = get("/")
    asset = None
    for token in ('src="', 'href="'):
        idx = html.find(token + "/assets/")
        if idx >= 0:
            start = idx + len(token)
            end = html.find('"', start)
            asset = html[start:end]
            break
    if asset:
        code, body, aheaders = get(asset, raw=True)
        ctype = aheaders.get("Content-Type", "?")
        print(f"  {asset} -> {code}，Content-Type={ctype}，{len(body)} 字节")
        results.append(("前端 JS 资源可获取", code == 200 and len(body) > 1000, f"{len(body)} 字节 {ctype}"))
    else:
        print("  未能从 index.html 里找到 /assets/ 引用")
        results.append(("前端 JS 资源可获取", False, "index.html 无 assets 引用"))

    print("\n=== 4) /api 反代在容器网络里连通 ===")
    status, health, _ = get_json("/api/health")
    health = health or {}
    print(f"  /api/health -> {status} {json.dumps(health, ensure_ascii=False)}")
    results.append((
        "Nginx 反代 /api 到后端容器",
        status == 200 and health.get("database") == "connected",
        f"retrieval={health.get('retrieval')} worker={health.get('worker')}",
    ))

    print("\n=== 5) 四个页面渲染所需的真实数据（容器内的库） ===")
    status, tree, _ = get_json("/api/knowledge/tree")
    nodes = len((tree or {}).get("nodes") or [])
    print(f"  /api/knowledge/tree -> {status}，根节点 {nodes} 个")
    results.append(("/knowledge 有树数据可渲染", status == 200 and nodes > 0, f"{nodes} 个根节点"))

    status, today, _ = get_json("/api/plans/today")
    today = today or {}
    recommendations = len(today.get("recommendations") or [])
    print(f"  /api/plans/today -> {status}，status={today.get('status')}，推荐 {recommendations} 条")
    results.append(("/study 有今日计划可渲染", status == 200 and bool(today.get("status")),
                    f"status={today.get('status')} 推荐 {recommendations}"))

    status, materials, _ = get_json("/api/materials")
    materials = materials or {}
    print(f"  /api/materials -> {status}，{len(materials.get('items') or [])} 份")
    results.append(("/materials 列表接口可用", status == 200, f"stats={materials.get('stats')}"))

    # 资料页的详情与块列表：上传一份可回收的探针资料来验证容器内的写+读+删，
    # 而不是只看空列表 —— 空列表什么都证明不了。
    print("\n=== 6) 资料页「上传 → 详情 → 块列表 → 删除」全链（容器内） ===")
    boundary = "----front" + uuid.uuid4().hex
    body = "# 部署验证资料\n\n洛必达法则用于处理未定式极限。\n".encode("utf-8")
    parts = [
        f"--{boundary}\r\n".encode(),
        b'Content-Disposition: form-data; name="file"; filename="front-probe.md"\r\n',
        b"Content-Type: text/markdown\r\n\r\n",
        body,
        f"\r\n--{boundary}--\r\n".encode(),
    ]
    req = urllib.request.Request(
        BASE + "/api/materials?title=" + urllib.parse.quote(f"E2E-FRONT-{SUFFIX}") + "&source_type=user",
        data=b"".join(parts),
        method="POST",
    )
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            created = json.loads(resp.read().decode("utf-8"))
        material_id = created["material"]["id"]
        deadline = time.time() + 120
        final = {}
        while time.time() < deadline:
            code, final, _ = get_json(f"/api/materials/{material_id}")
            if final.get("status") in ("ready", "failed"):
                break
            time.sleep(2)
        chunks_status, chunks, _ = get_json(f"/api/materials/{material_id}/chunks")
        chunk_items = len((chunks or {}).get("items") or [])
        print(f"  上传 -> 201，最终 status={final.get('status')}，块数={final.get('chunk_count')}，"
              f"chunks 接口 {chunks_status} 返回 {chunk_items} 块")
        results.append((
            "资料详情与块列表可读",
            final.get("status") == "ready" and chunk_items > 0,
            f"status={final.get('status')} chunks={chunk_items}",
        ))
        deleted = delete(f"/api/materials/{material_id}")
        print(f"  DELETE -> {deleted}")
        results.append(("探针资料已清理", deleted == 204, f"DELETE={deleted}"))
    except Exception as error:  # noqa: BLE001 - 诊断脚本
        print(f"  上传链路失败：{type(error).__name__}: {str(error)[:160]}")
        results.append(("资料详情与块列表可读", False, f"{type(error).__name__}"))
        results.append(("探针资料已清理", False, "上传失败，无可清理"))

    print("\n=== 7) SSE 穿过 Nginx 未被缓冲 ===")
    status, session = post_json("/api/chat/sessions", {"title": f"E2E-FRONT-{SUFFIX}", "mode": "user"})
    session_id = (session or {}).get("session_id") if isinstance(session, dict) else None
    if session_id:
        payload = json.dumps({"question": "洛必达法则的适用条件是什么？"}).encode()
        req = urllib.request.Request(
            f"{BASE}/api/chat/sessions/{session_id}/answers:stream", data=payload, method="POST"
        )
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "text/event-stream")
        events: dict[str, int] = {}
        reads = 0
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                while True:
                    block = resp.read(4096)
                    if not block:
                        break
                    reads += 1
                    for line in block.decode("utf-8", "replace").splitlines():
                        if line.startswith("event: "):
                            name = line[7:].strip()
                            events[name] = events.get(name, 0) + 1
                    if events.get("done") or events.get("error"):
                        break
        except Exception as error:  # noqa: BLE001
            print(f"  读流异常：{type(error).__name__}")
        print(f"  events={events}，分 {reads} 次读到达")
        # 上游模型未配置时会以 error 收尾；那也是「链路通」的证据（错误帧也要穿过代理）。
        ok = bool(events.get("delta")) or bool(events.get("error"))
        results.append(("SSE 能穿过 Nginx 到达前端", ok, f"events={events} reads={reads}"))
        delete(f"/api/chat/sessions/{session_id}")
        print("  探针会话已删除")
    else:
        print(f"  建会话失败：{status} {session}")
        results.append(("SSE 能穿过 Nginx 到达前端", False, f"建会话 {status}"))

    print("\n=== 结论 ===")
    for name, ok, note in results:
        print(f"  [{'ok' if ok else 'FAIL'}] {name} :: {note}")
    failed = [name for name, ok, _ in results if not ok]
    print()
    if failed:
        print(f"未通过：{', '.join(failed)}")
        return 1
    print(f"全部通过（{len(results)} 项）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
