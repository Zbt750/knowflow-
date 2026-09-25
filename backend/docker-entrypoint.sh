#!/bin/sh
# 后端容器启动脚本：等数据库 → 迁移 → 灌种子 → 启动服务。
#
# 为什么在容器里做迁移而不是宿主机：
# 部署形态是「一个 compose 起来就能用」，宿主机不保证有 Python 环境；
# 迁移与种子都是幂等的，重复启动不会产生重复数据。

set -e

echo "[entrypoint] 等待数据库就绪…"
python - <<'PY'
import os
import sys
import time

import psycopg
from sqlalchemy.engine import make_url

url = make_url(os.environ["DATABASE_URL"])
dsn = (
    f"host={url.host} port={url.port or 5432} user={url.username} "
    f"password={url.password or ''} dbname={url.database} connect_timeout=3"
)
deadline = time.time() + 60
while True:
    try:
        with psycopg.connect(dsn):
            pass
        print("[entrypoint] 数据库已就绪")
        break
    except Exception as error:  # noqa: BLE001 - 启动阶段只关心能不能连上
        if time.time() > deadline:
            print(f"[entrypoint] 等待数据库超时：{type(error).__name__}", file=sys.stderr)
            raise SystemExit(1)
        time.sleep(1)
PY

echo "[entrypoint] 执行数据库迁移…"
alembic upgrade head

echo "[entrypoint] 灌入知识点与题库（幂等）…"
python scripts/seed.py

echo "[entrypoint] 启动后端服务…"
exec uvicorn backend.app:create_app --factory --host 0.0.0.0 --port 8000