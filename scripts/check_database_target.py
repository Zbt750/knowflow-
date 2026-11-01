#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""只读确认目标 PostgreSQL 身份；不打印密码，不写库。

用法：
    $env:APP_ENV="test"; $env:TEST_DATABASE_URL="postgresql+psycopg://.../kaoyan_test"
    python scripts/check_database_target.py --expect-database kaoyan_test
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from urllib.parse import urlsplit


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expect-database", default=None)
    parser.add_argument("--allow-non-test", action="store_true")
    args = parser.parse_args()

    # In test mode never fall back to DATABASE_URL: the explicit test URL is
    # the security boundary, not a convenience alias.
    url = (os.environ.get("TEST_DATABASE_URL") if os.environ.get("APP_ENV") == "test"
           else os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL"))
    if not url:
        raise SystemExit("缺少 TEST_DATABASE_URL（或 DATABASE_URL）")
    if os.environ.get("APP_ENV") != "test" and not args.allow_non_test:
        raise SystemExit("APP_ENV 不是 test；拒绝确认非测试环境")

    dsn = url.replace("postgresql+psycopg://", "postgresql://")
    parts = urlsplit(dsn)
    database = parts.path.lstrip("/")
    if database == "kaoyan":
        raise SystemExit("拒绝：目标是正式开发库 kaoyan")
    if not database.endswith("_test") and not args.allow_non_test:
        raise SystemExit(f"拒绝：数据库 {database!r} 不是 *_test")
    if args.expect_database and database != args.expect_database:
        raise SystemExit(f"拒绝：连接串数据库 {database!r} 与 --expect-database {args.expect_database!r} 不一致")

    if os.environ.get("APP_ENV") == "test" and not args.allow_non_test:
        owned_port = os.environ.get("KAOYAN_OWNED_TEST_PORT") or os.environ.get("PHASE45E_OWNED_TEST_PORT")
        try:
            port = int(parts.port or 0)
            marker = int(owned_port or 0)
        except (TypeError, ValueError):
            raise SystemExit("拒绝：测试端口或所有权标记无效") from None
        if parts.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise SystemExit("拒绝：测试数据库必须通过 loopback 连接")
        if port <= 18000 or marker != port or port == 5433:
            raise SystemExit("拒绝：测试数据库端口必须匹配运行器所有权标记且大于 18000")

    try:
        import psycopg
    except ImportError as exc:
        raise SystemExit(f"缺少 psycopg：{exc}")

    try:
        with psycopg.connect(dsn, connect_timeout=5) as conn:
            row = conn.execute(
                "select current_database(), current_user, "
                "coalesce(inet_server_addr()::text, 'local'), "
                "coalesce(inet_server_port(), 0), version()"
            ).fetchone()
    except Exception as exc:
        # Driver exceptions can embed a DSN. Keep diagnostics useful without
        # risking credentials in terminal or audit output.
        raise SystemExit(f"连接失败：{type(exc).__name__}") from None

    report = {
        "client_host": parts.hostname,
        "client_port": parts.port,
        "database": row[0],
        "user": row[1],
        "server_addr": row[2],
        "server_port": row[3],
        "server_version": str(row[4]).split(",")[0],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if os.environ.get("APP_ENV") == "test" and not args.allow_non_test:
        if report["server_addr"] not in {"127.0.0.1", "::1"} or report["server_port"] != parts.port:
            raise SystemExit("拒绝：数据库实际监听地址或端口与测试目标不一致")
        if not str(report["database"]).endswith("_test") or report["user"] != "kaoyan_app":
            raise SystemExit("拒绝：测试数据库名称或应用角色不符合隔离约定")
    return 0 if report["database"] == database else 1


if __name__ == "__main__":
    raise SystemExit(main())
