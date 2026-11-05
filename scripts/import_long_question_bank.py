#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把大题库内容包写入现有 Question / QuestionVersion / 生成批次。

安全边界：
- 默认只允许 APP_ENV=test 且数据库名以 _test 结尾；开发库必须显式双开关才允许写。
- 不删除、不覆盖任何已有题目；题目 ID 由 batch_key+slug 稳定派生，重跑幂等。
- 每题写入后立即用 current_general_binding 复核；不通过则只回滚该题。

用法（隔离测试库）：
    APP_ENV=test TEST_DATABASE_URL=postgresql+psycopg://.../kaoyan_test \
      python scripts/import_long_question_bank.py --pack content/long_question_packs/pilot_20261018.json
    # 加 --dry-run 只检查不提交
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.config import get_settings  # noqa: E402
from backend.db import create_db_engine, create_session_factory  # noqa: E402
from backend.models.learning import KnowledgePoint, Question  # noqa: E402
from backend.models.personal_generation import PersonalGenerationBatch  # noqa: E402
from backend.services.long_question_bank import (  # noqa: E402
    Pack, batch_request_payload, binding_is_current, build_question,
    finalize_generation_hash, stable_question_id, summarize_items,
)
from backend.services.question_service import (  # noqa: E402
    DuplicateQuestionStemError, assert_not_duplicate_stem,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")


def guard_database(args) -> str:
    from sqlalchemy.engine import make_url

    settings = get_settings()
    url = str(settings.active_database_url)
    parsed = make_url(url)
    database_name = parsed.database or ""
    host, port = parsed.host, parsed.port
    # 不打印密码；只显示可核对的主机/端口/库名。
    print(f"[target] host={host} port={port} database={database_name}")
    if database_name == "kaoyan":
        raise SystemExit("拒绝写入：目标库名为 kaoyan（正式开发库）。请显式使用隔离的 *_test 库。")
    if settings.app_env != "test" and not args.allow_non_test:
        raise SystemExit(
            "拒绝写入：当前 APP_ENV 不是 test。批量验证必须使用隔离测试库；"
            "确需写开发库时显式加 --allow-non-test --confirm-dev-write。"
        )
    if not database_name.endswith("_test") and not args.confirm_dev_write:
        raise SystemExit(
            f"拒绝写入：目标数据库 {database_name!r} 不是 *_test。"
            "请设置 TEST_DATABASE_URL 指向隔离库，或显式加 --confirm-dev-write。"
        )
    if not args.dry_run and args.confirm_database != database_name:
        raise SystemExit(
            f"拒绝写入：请用 --confirm-database {database_name} 明确确认目标库；"
            "仅设置 APP_ENV=test 不足以证明库身份。"
        )
    return url


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path,
                        default=Path("content/long_question_packs/pilot_20261018.json"))
    parser.add_argument("--batch-key", default=None, help="覆盖内容包内的 batch_key（仅调试用）")
    parser.add_argument("--limit", type=int, default=0, help="只处理前 N 题（0=全部）")
    parser.add_argument("--dry-run", action="store_true", help="完整检查后回滚，不提交")
    parser.add_argument("--allow-non-test", action="store_true")
    parser.add_argument("--confirm-dev-write", action="store_true")
    parser.add_argument("--confirm-database", default=None,
                        help="正式写入时必须显式填写目标库名（与连接串中的 database 一致）")
    parser.add_argument("--verdicts", type=Path, default=None,
                        help="三级审核 JSON；默认只导入 PASS，REVIEW 暂缓")
    parser.add_argument("--include-review", action="store_true",
                        help="连同 REVIEW 题一起导入（仍保留 PENDING 状态）")
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args()

    url = guard_database(args)
    pack = Pack.load(args.pack)
    batch_key = args.batch_key or pack.batch_key
    items = pack.items[: args.limit] if args.limit else pack.items
    verdicts: dict[str, str] = {}
    if args.verdicts:
        triage = json.loads(args.verdicts.read_text(encoding="utf-8"))
        verdicts = {row["slug"]: row.get("verdict", "UNKNOWN")
                    for row in triage.get("results", []) if isinstance(row, dict) and row.get("slug")}
    codes = sorted({item.kp_code for item in items})

    engine = create_db_engine(url)
    factory = create_session_factory(engine)
    session = factory()
    started_at = datetime.now(SHANGHAI).isoformat(timespec="seconds")
    outcomes: list[dict] = []
    try:
        nodes = {node.code: node for node in session.scalars(
            select(KnowledgePoint).where(KnowledgePoint.code.in_(codes)))}
        missing = [code for code in codes if code not in nodes]
        if missing:
            raise SystemExit(f"知识树中不存在这些 code：{missing}")

        batch = session.scalar(
            select(PersonalGenerationBatch).where(PersonalGenerationBatch.request_key == batch_key))
        if batch is None:
            batch = PersonalGenerationBatch(
                request_key=batch_key,
                input_sha256=pack.sha256,
                status="running",
                study_date=datetime.now(SHANGHAI).date().isoformat(),
                reserved_calls=0,
                request=batch_request_payload(pack),
                result={},
            )
            session.add(batch)
            session.flush()
        batch.status = "running"

        counts = {"created": 0, "skipped_existing": 0, "duplicate": 0,
                  "invalid": 0, "failed": 0, "deferred_review": 0}
        for item in items:
            outcome = {"slug": item.slug, "kp_code": item.kp_code, "status": None, "detail": ""}
            if verdicts and not args.include_review and verdicts.get(item.slug) != "PASS":
                outcome["status"] = "deferred_review"
                outcome["detail"] = f"verdict={verdicts.get(item.slug, 'UNKNOWN')}; 用 --include-review 可一并导入"
                counts["deferred_review"] += 1
                outcomes.append(outcome)
                continue
            try:
                with session.begin_nested():
                    node = nodes[item.kp_code]
                    if not (node.is_active and node.is_assessable):
                        raise ValueError("kp_not_active_assessable_leaf")
                    if node.is_reference_only:
                        raise ValueError("kp_is_reference_only")
                    question_id = stable_question_id(batch_key, item)
                    existing = session.get(Question, question_id)
                    if existing is not None:
                        if existing.kp_id != node.id or existing.generation_batch_id != batch.id:
                            raise ValueError("stable_id_collision_with_different_question")
                        outcome["status"] = "skipped_existing"
                        outcome["question_id"] = str(existing.id)
                        counts["skipped_existing"] += 1
                        outcomes.append(outcome)
                        continue
                    existing_stems = list(session.scalars(
                        select(Question.stem).where(Question.kp_id == node.id)))
                    try:
                        assert_not_duplicate_stem(item.stem, existing_stems)
                    except DuplicateQuestionStemError as exc:
                        outcome["status"] = "duplicate"
                        outcome["detail"] = str(exc)
                        counts["duplicate"] += 1
                        outcomes.append(outcome)
                        continue
                    question = build_question(item, node, batch.id, batch_key)
                    # 必须在 add/flush 前写哈希：否则改动 grading_config 会触发第二个版本快照。
                    finalize_generation_hash(question)
                    session.add(question)
                    session.flush()
                    if not binding_is_current(question, node):
                        raise ValueError("personal_general_binding_invalid_after_flush")
                    outcome["status"] = "created"
                    outcome["question_id"] = str(question.id)
                    outcome["version_id"] = str(question.current_version_id)
                    counts["created"] += 1
            except ValueError as exc:
                outcome["status"] = "invalid"
                outcome["detail"] = str(exc)
                counts["invalid"] += 1
            except Exception as exc:  # 单题失败不拖垮整批
                outcome["status"] = "failed"
                outcome["detail"] = f"{type(exc).__name__}: {exc}"
                counts["failed"] += 1
            outcomes.append(outcome)

        batch.result = {
            "started_at": started_at,
            "finished_at": datetime.now(SHANGHAI).isoformat(timespec="seconds"),
            "pack": str(args.pack),
            "pack_sha256": pack.sha256,
            "dry_run": bool(args.dry_run),
            "counts": counts,
            "items": outcomes,
        }
        batch.status = "completed" if counts["failed"] == 0 and counts["invalid"] == 0 else "partial"
        session.flush()
        if args.dry_run:
            session.rollback()
        else:
            session.commit()
    finally:
        session.close()

    report = {
        "batch_key": batch_key,
        "database": url.rsplit("/", 1)[-1],
        "dry_run": bool(args.dry_run),
        "pack": str(args.pack),
        "pack_sha256": pack.sha256,
        "summary": summarize_items(items),
        "counts": counts,
        "items": outcomes,
    }
    report_path = args.report or Path(f"docs/long-question-import-{batch_key}.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("batch_key", "database", "dry_run", "counts")},
                     ensure_ascii=False, indent=2))
    print("report ->", report_path)
    return 0 if counts["failed"] == 0 and counts["invalid"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
