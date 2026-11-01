#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在 SQLite 上执行真正的 import_long_question_bank.main()。

目的：验证导入器本身的批次、savepoint、稳定 ID、版本钩子和幂等逻辑，
不连接 PostgreSQL，也不代表正式入库。正式导入仍需在隔离 PostgreSQL 上执行。
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import types
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, func, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from backend.models.base import Base  # noqa: E402
from backend.models.learning import KnowledgePoint, Question, QuestionVersion  # noqa: E402
from backend.models.personal_generation import PersonalGenerationBatch  # noqa: E402


def digest(value: dict) -> str:
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def content_sha(question: Question) -> str:
    return digest({"question_type": question.question_type, "stem": question.stem,
                   "options": question.options, "kp_id": str(question.kp_id)})


def generation_hash(question: Question) -> str:
    config = question.grading_config or {}
    return digest({
        "content": content_sha(question), "answer": question.correct_answer,
        "explanation": question.explanation, "origin": question.question_provenance,
        "method": config.get("generated_practice_method"), "node": str(question.kp_id),
        "generation_metadata": {k: v for k, v in config.get("generation", {}).items()
                                if k not in {"verified_content_hash", "final_value"}},
    })


def main() -> int:
    db_path = Path(tempfile.gettempdir()) / "kaoyan_test"
    if db_path.exists():
        db_path.unlink()
    url = f"sqlite:///{db_path.as_posix()}"
    engine = create_engine(url)

    # 只建导入所需表；SQLite 外键默认不启用，足以验证 ORM 写入路径。
    Base.metadata.create_all(engine, tables=[
        KnowledgePoint.__table__, Question.__table__,
        QuestionVersion.__table__, PersonalGenerationBatch.__table__,
    ])

    # 假 config / db：不让导入器加载 pydantic/fastapi，也不碰真实库。
    config_module = types.ModuleType("backend.config")
    class _Settings:
        app_env = "test"
        active_database_url = url
    config_module.get_settings = lambda: _Settings()
    sys.modules["backend.config"] = config_module

    db_module = types.ModuleType("backend.db")
    db_module.create_db_engine = lambda _url: create_engine(_url)
    db_module.create_session_factory = lambda _engine: sessionmaker(
        bind=_engine, autoflush=False, expire_on_commit=False)
    sys.modules["backend.db"] = db_module

    import backend.services.long_question_bank as lqb
    lqb.finalize_generation_hash = lambda q: q.grading_config["generation"].__setitem__(
        "verified_content_hash", generation_hash(q)) or q.grading_config["generation"]["verified_content_hash"]
    lqb.binding_is_current = lambda q, node: bool(
        q.bank_scope == "personal" and q.question_provenance == "ai_generated_practice"
        and q.kp_id == node.id
        and q.grading_config["generation"].get("verified_content_hash") == generation_hash(q))

    # 知识点必须真实存在；用盘点清单里的 25 个 code。
    import csv
    inventory = {}
    with (ROOT / "docs" / "long-question-inventory-20261018.csv").open(encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            inventory[row["知识点ID（稳定code）"]] = row
    packs = ["pilot_20261018.json", "os_batch01_20261018.json", "ds_batch01_20261018.json",
             "co_batch01_20261018.json", "cn_batch01_20261018.json"]
    codes = set()
    for name in packs:
        data = json.loads((ROOT / "content" / "long_question_packs" / name).read_text(encoding="utf-8"))
        codes.update(item["kp_code"] for item in data["items"])
    session = sessionmaker(bind=engine)()
    for code in sorted(codes):
        row = inventory[code]
        session.add(KnowledgePoint(
            id=uuid5(NAMESPACE_URL, "smoke-kp:" + code), code=code,
            name=row["知识点名称"], subject=row["学科"], is_assessable=True,
            is_active=True, ordinal=1))
    session.commit()
    session.close()

    # 载入真正的导入器脚本。
    spec = importlib.util.spec_from_file_location(
        "import_long_question_bank", ROOT / "scripts" / "import_long_question_bank.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    tags = {"pilot_20261018.json": "pilot", "os_batch01_20261018.json": "os01",
            "ds_batch01_20261018.json": "ds01", "co_batch01_20261018.json": "co01",
            "cn_batch01_20261018.json": "cn01"}
    results = []

    def run_pack(name, extra):
        sys.argv = ["import_long_question_bank.py", "--pack",
                    str(ROOT / "content" / "long_question_packs" / name),
                    "--confirm-database", str(db_path), *extra]
        return module.main()

    def count_questions():
        with sessionmaker(bind=engine)() as check:
            return int(check.scalar(select(func.count(Question.id))) or 0)

    def triage(name):
        return str(ROOT / "docs" / f"long-question-triage-{tags[name]}-20261018.json")

    # 第一遍：只导 PASS（REVIEW 暂缓）
    for name in packs:
        results.append({"run": 1, "pack": name, "mode": "pass_only",
                        "exit": run_pack(name, ["--verdicts", triage(name)])})
    after_pass = count_questions()
    # 第二遍：同样只导 PASS，应全部 skip_existing
    for name in packs:
        results.append({"run": 2, "pack": name, "mode": "pass_only",
                        "exit": run_pack(name, ["--verdicts", triage(name)])})
    after_second = count_questions()
    # 第三遍：连同 REVIEW 一起导入
    for name in packs:
        results.append({"run": 3, "pack": name, "mode": "include_review",
                        "exit": run_pack(name, ["--verdicts", triage(name), "--include-review"])})
    after_review = count_questions()

    session = sessionmaker(bind=engine)()
    counts = {
        "questions": session.scalar(select(func.count(Question.id))),
        "versions": session.scalar(select(func.count(QuestionVersion.id))),
        "batches": session.scalar(select(func.count(PersonalGenerationBatch.id))),
        "after_pass_only": after_pass,
        "after_second_pass": after_second,
        "after_include_review": after_review,
        "per_kp": dict(session.execute(
            select(Question.kp_id, func.count(Question.id)).group_by(Question.kp_id)).all()),
        "all_personal": session.scalar(select(func.count(Question.id)).where(
            Question.bank_scope != "personal")),
        "versions_one": session.scalar(select(func.count(QuestionVersion.id)).where(
            QuestionVersion.version_number != 1)),
    }
    report = {
        "status": "PASS" if results[0]["exit"] == 0 and results[1]["exit"] == 0
                  and counts["questions"] == 50 and counts["versions"] == 50
                  and counts["after_pass_only"] == 39 and counts["after_second_pass"] == 39
                  and counts["all_personal"] == 0 and counts["versions_one"] == 0 else "FAIL",
        "database": "sqlite_temp (not the project database)",
        "runs": results,
        "counts": {**counts, "per_kp": {str(k): v for k, v in counts["per_kp"].items()}},
        "note": "第二次运行应全部 skip_existing，题数与版本数都不增加。",
    }
    session.close()
    out = ROOT / "docs" / "long-question-importer-sqlite-smoke-20261018.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
