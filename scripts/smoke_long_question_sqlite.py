#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用真实 ORM 模型在 SQLite 内存库跑大题库导入冒烟测试。

不连接 PostgreSQL，只验证：
- build_question 能构造 Question；
- before_flush 钩子自动创建 QuestionVersion（版本 1）；
- 版本快照哈希与 content_hash 一致；
- 稳定 ID 唯一且可重算；
- 每知识点 2 题、字段为 personal/ai_generated_practice/原创题；
- 重复 build 同一 slug 会得到同一 ID（幂等基础）。

注意：SQLite 不是项目正式库；正式导入仍需在隔离 PostgreSQL 上跑
scripts/import_long_question_bank.py。
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from backend.models.base import Base  # noqa: E402
from backend.models.learning import KnowledgePoint, Question, QuestionVersion  # noqa: E402
from backend.services.long_question_bank import (  # noqa: E402
    Pack, build_question, stable_question_id,
)
from backend.services.question_versions import version_snapshot_hash  # noqa: E402

DEFAULT_PACKS = [
    "pilot_20261018.json",
    "os_batch01_20261018.json",
    "ds_batch01_20261018.json",
    "co_batch01_20261018.json",
    "cn_batch01_20261018.json",
]


def digest(value: dict) -> str:
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def question_content_sha256(question: Question) -> str:
    return digest({
        "question_type": question.question_type,
        "stem": question.stem,
        "options": question.options,
        "kp_id": str(question.kp_id),
    })


def generation_hash(question: Question) -> str:
    config = question.grading_config or {}
    return digest({
        "content": question_content_sha256(question),
        "answer": question.correct_answer,
        "explanation": question.explanation,
        "origin": question.question_provenance,
        "method": config.get("generated_practice_method"),
        "node": str(question.kp_id),
        "generation_metadata": {
            key: value for key, value in config.get("generation", {}).items()
            if key not in {"verified_content_hash", "final_value"}
        },
    })


def load_nodes() -> dict[str, dict]:
    path = ROOT / "docs" / "long-question-inventory-20261018.csv"
    rows = {}
    with path.open(encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            rows[row["知识点ID（稳定code）"]] = row
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path,
                        default=ROOT / "docs" / "long-question-sqlite-smoke-20261018.json")
    args = parser.parse_args()

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[
        KnowledgePoint.__table__, Question.__table__, QuestionVersion.__table__,
    ])
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()

    inventory = load_nodes()
    nodes: dict[str, KnowledgePoint] = {}
    packs = []
    for name in DEFAULT_PACKS:
        pack = Pack.load(ROOT / "content" / "long_question_packs" / name)
        packs.append(pack)
    codes = sorted({item.kp_code for pack in packs for item in pack.items})
    for code in codes:
        row = inventory.get(code)
        if row is None:
            raise SystemExit(f"知识点不在盘点清单：{code}")
        node = KnowledgePoint(
            id=uuid5(NAMESPACE_URL, "smoke-kp:" + code),
            code=code,
            name=row["知识点名称"],
            subject=row["学科"],
            is_assessable=True,
            is_active=True,
            ordinal=1,
        )
        session.add(node)
        nodes[code] = node
    session.flush()

    created: list[Question] = []
    try:
        for pack in packs:
            batch_id = uuid5(NAMESPACE_URL, "smoke-batch:" + pack.batch_key)
            for item in pack.items:
                question = build_question(item, nodes[item.kp_code], batch_id, pack.batch_key)
                # 与 importer 相同的顺序：写哈希后再 add/flush。
                question.grading_config["generation"]["verified_content_hash"] = generation_hash(question)
                session.add(question)
                session.flush()
                created.append(question)
        session.flush()

        per_kp = Counter(str(q.kp_id) for q in created)
        checks = {
            "questions": len(created),
            "versions": int(session.query(QuestionVersion).count()),
            "per_kp_two": all(count == 2 for count in per_kp.values()),
            "stable_ids_unique": len({q.id for q in created}) == len(created),
            "all_have_current_version": all(q.current_version_id is not None for q in created),
            "all_version_one": all(q.current_version.version_number == 1 for q in created),
            "all_hashes_match": all(
                q.current_version.content_hash == version_snapshot_hash(q.current_version.snapshot_json)
                for q in created),
            "all_personal": all(q.bank_scope == "personal" for q in created),
            "all_ai_provenance": all(q.question_provenance == "ai_generated_practice" for q in created),
            "all_answer_ai": all(q.answer_provenance == "ai_generated" for q in created),
            "all_source_na": all(q.source_status == "not_applicable" for q in created),
            "all_original_label": all(
                (q.grading_config.get("long_question") or {}).get("identity_label") == "原创题"
                for q in created),
            "all_generation_bound": all(
                (q.grading_config.get("generation") or {}).get("verified_content_hash")
                == generation_hash(q) for q in created),
        }
        # 幂等基础：同一 slug 重新构造得到同一 ID
        sample_pack = packs[0]
        sample_item = sample_pack.items[0]
        repeated = build_question(sample_item, nodes[sample_item.kp_code],
                                  uuid4(), sample_pack.batch_key)
        checks["stable_id_repeatable"] = repeated.id == created[0].id
        status = "PASS" if all(v for k, v in checks.items() if isinstance(v, bool)) else "FAIL"
    except Exception as exc:  # 保留真实异常，不伪装通过
        checks = {"exception": f"{type(exc).__name__}: {exc}"}
        status = "FAIL"
    finally:
        session.rollback()
        session.close()

    report = {
        "status": status,
        "database": "sqlite_in_memory (not the project database)",
        "packs": [pack.batch_key for pack in packs],
        "checks": checks,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
