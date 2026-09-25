"""静态校验 Docker/Compose 配置引用的文件是否都存在。

不是 Docker 构建本身，而是「在无法运行 Docker 的环境里能做的最大程度检查」：
Dockerfile 的 COPY 路径写错、compose 引用的脚本不存在，都会在真正构建时才暴露，
而一旦本机没有 Docker，这些错误就会被拖到最晚才发现。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(r"D:\考研跑通项目")

failures: list[str] = []


def check(condition: bool, label: str) -> None:
    print(f"  [{'OK ' if condition else 'FAIL'}] {label}")
    if not condition:
        failures.append(label)


def check_dockerfile(path: Path, context: Path) -> None:
    """校验一个 Dockerfile 的 COPY 源。

    `context` 是该 Dockerfile 的构建上下文：前后端 Dockerfile 放在各自目录下，
    但 compose 里前端用的 context 是项目根、后端也是项目根，
    因此调用方必须显式给出上下文，不能假设「和 Dockerfile 同目录」。
    """
    print(f"\n--- {path.relative_to(ROOT)}（上下文 {context.relative_to(ROOT) or '.'}）---")
    if not path.exists():
        check(False, f"{path.name} 存在")
        return
    text = path.read_text(encoding="utf-8")

    for raw in text.splitlines():
        line = raw.strip()
        if not line.startswith("COPY"):
            continue
        parts = line.split()[1:]
        # --from=xxx 表示从另一个构建阶段拷贝，源路径在镜像内，不能按宿主路径校验。
        if any(part.startswith("--from") for part in parts):
            continue
        sources = [part for part in parts if not part.startswith("--")]
        if len(sources) < 2:
            continue
        for source in sources[:-1]:
            if source in {".", "./"}:
                continue
            if "*" in source:
                exists = (context / source.split("*")[0]).exists()
            else:
                exists = (context / source).exists()
            check(exists, f"COPY 源存在：{source}")

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(("ENTRYPOINT", "CMD")):
            for token in re.findall(r'"([^"]+)"', stripped):
                if "/" in token and not token.startswith("http"):
                    resolved = context / token.lstrip("./")
                    if path.name == "Dockerfile" and path.parent.name == "backend":
                        # 后端 Dockerfile 的 COPY 目标就是 WORKDIR /app 下的路径。
                        check(resolved.exists(), f"入口脚本存在：{token}")


def main() -> int:
    print("=== 校验 Dockerfile ===")
    # compose 里两个服务的 context 都是项目根，所以上下文都取 ROOT。
    check_dockerfile(ROOT / "backend" / "Dockerfile", ROOT)
    # 前端上下文是自己的目录：package.json 与 src 都在 frontend/ 下。
    check_dockerfile(ROOT / "frontend" / "Dockerfile", ROOT / "frontend")

    print("\n=== 校验 compose 引用 ===")
    compose = ROOT / "docker-compose.yml"
    text = compose.read_text(encoding="utf-8")
    check("services:" in text, "compose 有 services 段")
    for name in ("db", "backend", "frontend"):
        check(f"{name}:" in text, f"包含服务 {name}")
    for referenced in ("backend/Dockerfile", "frontend/Dockerfile", "scripts/seed.py", "alembic.ini"):
        check((ROOT / referenced).exists(), f"compose 引用的 {referenced} 存在")
    check("POSTGRES_PASSWORD:?" in text, "数据库密码强制从环境变量注入（缺省即报错）")
    check("pg_isready" in text, "数据库健康检查用 pg_isready")
    check("condition: service_healthy" in text, "后端等待数据库健康后再启动")
    check("storage_data:" in text, "上传文件与向量库挂载到卷（重建容器不丢）")
    check("db_data:" in text, "数据库数据挂载到卷")

    print("\n=== 校验必需文件 ===")
    for rel in (
        "backend/docker-entrypoint.sh",
        "frontend/nginx/default.conf.template",
        "requirements.txt",
        "requirements-embed.txt",
        ".dockerignore",
        ".env.compose.example",
        "frontend/package-lock.json",
    ):
        check((ROOT / rel).exists(), f"存在：{rel}")

    print("\n=== 校验 entrypoint 脚本 ===")
    entry = ROOT / "backend" / "docker-entrypoint.sh"
    if entry.exists():
        raw = entry.read_bytes()
        check(b"\r\n" not in raw, "行尾是 LF（CRLF 会让容器报 not found）")
        text = raw.decode("utf-8")
        check(text.startswith("#!/bin/sh"), "有 shebang")
        for step in ("alembic upgrade head", "scripts/seed.py", "uvicorn"):
            check(step in text, f"包含步骤：{step}")

    print("\n=== 校验 nginx 模板 ===")
    nginx = ROOT / "frontend" / "nginx" / "default.conf.template"
    if nginx.exists():
        text = nginx.read_text(encoding="utf-8")
        for item in ("try_files", "upstream kaoyan_backend", "proxy_buffering off"):
            check(item in text, f"包含：{item}")
        # $host 之类的 nginx 变量在 envsubst 下必须保留：模板里若还混用
        # ${VAR} 这种占位变量，就必须配白名单，否则 nginx 变量可能被替换成空。
        check("$host" in text, "保留了 nginx 自身变量 $host")
        # 只看非注释行：注释里出现 ${...} 只是说明文字，envsubst 不会处理注释。
        effective = "\n".join(
            line for line in text.splitlines() if not line.strip().startswith("#")
        )
        check("${" not in effective, "有效配置里没有 envsubst 占位变量（避免误替换 nginx 变量）")

    print("\n=== 校验 .dockerignore 覆盖运行期数据 ===")
    ignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
    for item in ("storage", "node_modules", ".pgdata", ".git"):
        check(item in ignore, f"忽略：{item}")

    print("\n" + "=" * 60)
    if failures:
        print(f"静态校验失败：{len(failures)} 项")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("静态校验全部通过（注意：这不等于 Docker 构建成功，本机无 Docker）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
