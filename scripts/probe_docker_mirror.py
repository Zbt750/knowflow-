"""临时脚本：探测可用的 Docker 镜像加速站（用完即删）。

背景：`~/.docker/daemon.json` 里原来配的两个镜像站已失效（401 Unauthorized），
移除后直连 auth.docker.io 又超时（国内网络）。这里逐个试常见镜像站，
把第一个可用的写回 daemon.json 并重启 Docker Desktop。
"""

import json
import subprocess
import time
from pathlib import Path

DAEMON = Path.home() / ".docker" / "daemon.json"

CANDIDATES = [
    "https://docker.1ms.run",
    "https://docker.m.daocloud.io",
    "https://docker.1panel.live",
    "https://dockerpull.org",
    "https://docker.xuanyuan.me",
    "https://hub.rat.dev",
    "https://docker.registry.cyou",
]


def read_daemon() -> dict:
    return json.loads(DAEMON.read_text(encoding="utf-8"))


def write_daemon(mirrors: list[str]) -> None:
    data = read_daemon()
    data["registry-mirrors"] = mirrors
    DAEMON.write_text(json.dumps(data, indent=4, ensure_ascii=False), encoding="utf-8")


def restart_docker() -> bool:
    subprocess.run(
        ["taskkill", "/F", "/IM", "Docker Desktop.exe"],
        capture_output=True,
        check=False,
    )
    time.sleep(6)
    exe = Path.home() / "AppData/Local/Programs/DockerDesktop/Docker Desktop.exe"
    if exe.exists():
        subprocess.Popen([str(exe)])
    for _ in range(40):
        time.sleep(5)
        result = subprocess.run(["docker", "info"], capture_output=True, text=True)
        if "Server Version" in result.stdout:
            return True
    return False


def try_pull() -> tuple[bool, str]:
    result = subprocess.run(
        ["docker", "pull", "python:3.12-slim"],
        capture_output=True,
        text=True,
        timeout=300,
    )
    output = (result.stdout + result.stderr).strip().splitlines()
    tail = output[-1] if output else ""
    return result.returncode == 0, tail[:220]


def main() -> int:
    print("当前 daemon 镜像站：", read_daemon().get("registry-mirrors"))
    for mirror in CANDIDATES:
        print(f"\n=== 试 {mirror} ===")
        write_daemon([mirror])
        if not restart_docker():
            print("  daemon 未就绪，跳过")
            continue
        ok, tail = try_pull()
        print(f"  pull 成功={ok} :: {tail}")
        if ok:
            print(f"\n可用镜像站：{mirror}")
            write_daemon([mirror])
            print("已写回 daemon.json")
            return 0
    print("\n所有候选镜像站都不可用，需要用户提供可用的镜像源")
    write_daemon([])
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
