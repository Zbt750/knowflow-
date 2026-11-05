#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""只读统计大题库批次在 PostgreSQL 中的实际数量、版本与节点分布。

用法：
    $env:APP_ENV="test"; $env:TEST_DATABASE_URL="postgresql+psycopg://.../kaoyan_test"
    python scripts/long_question_db_report.py --batch-key longbank-20261018-pilot `
        --batch-key longbank-20261018-os01 --out docs/long-question-db-report.json
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-key", action="append", default=[])
    parser.add_argument("--out", type=Path, default=Path("docs/long-question-db-report.json"))
    args = parser.parse_args()
    keys = args.batch_key or [
        "longbank-20261018-pilot", "longbank-20261018-os01",
        "longbank-20261018-ds01", "longbank-20261018-co01",
        "longbank-20261018-cn01",
    ]

    url = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("缺少 TEST_DATABASE_URL")
    dsn = url.replace("postgresql+psycopg://", "postgresql://")
    parts = urlsplit(dsn)
    database = parts.path.lstrip("/")
    if database == "kaoyan" or not database.endswith("_test"):
        raise SystemExit(f"拒绝：目标 {database!r} 不是隔离 *_test 库")

    try:
        import psycopg
    except ImportError as exc:
        raise SystemExit(f"缺少 psycopg：{exc}")

    report = {
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "database": database,
        "client_host": parts.hostname,
        "client_port": parts.port,
        "batches": {},
        "total_questions": 0,
        "total_versions": 0,
        "personal_scope": 0,
        "public_leak": 0,
    }
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        identity = conn.execute(
            "select current_database(), coalesce(inet_server_addr()::text,'local'), "
            "coalesce(inet_server_port(),0)").fetchone()
        report.update(database=identity[0], server_addr=identity[1], server_port=identity[2])
        for key in keys:
            batch = conn.execute(
                "select id, status, input_sha256, study_date from personal_generation_batches "
                "where request_key=%s", (key,)).fetchone()
            if batch is None:
                report["batches"][key] = {"found": False, "questions": 0, "versions": 0}
                continue
            batch_id, status, sha, study_date = batch
            questions = conn.execute(
                "select count(*), count(distinct kp_id) from questions where generation_batch_id=%s",
                (batch_id,)).fetchone()
            versions = conn.execute(
                "select count(*) from question_versions v join questions q "
                "on q.id=v.question_id where q.generation_batch_id=%s", (batch_id,)).fetchone()[0]
            personal = conn.execute(
                "select count(*) from questions where generation_batch_id=%s and bank_scope='personal'",
                (batch_id,)).fetchone()[0]
            leak = conn.execute(
                "select count(*) from questions where generation_batch_id=%s and bank_scope<>'personal'",
                (batch_id,)).fetchone()[0]
            per_kp = conn.execute(
                "select k.code, k.name, count(q.id) from questions q "
                "join knowledge_points k on k.id=q.kp_id "
                "where q.generation_batch_id=%s group by k.code, k.name order by k.code",
                (batch_id,)).fetchall()
            non_one = conn.execute(
                "select count(*) from question_versions v join questions q "
                "on q.id=v.question_id where q.generation_batch_id=%s and v.version_number<>1",
                (batch_id,)).fetchone()[0]
            report["batches"][key] = {
                "found": True, "status": status, "input_sha256": sha, "study_date": str(study_date),
                "questions": questions[0], "distinct_kps": questions[1],
                "versions": versions, "personal_scope": personal, "public_leak": leak,
                "non_first_versions": non_one,
                "per_kp": [{"code": row[0], "name": row[1], "questions": row[2]} for row in per_kp],
            }
            report["total_questions"] += questions[0]
            report["total_versions"] += versions
            report["personal_scope"] += personal
            report["public_leak"] += leak

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("database", "total_questions",
                      "total_versions", "personal_scope", "public_leak")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
