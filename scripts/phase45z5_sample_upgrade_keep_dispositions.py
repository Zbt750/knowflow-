"""Read-only, snapshot-bound decisions for the five retained sample candidates."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.models.learning import Question
from backend.services.auto_question_review import (
    assess_auto_qualification,
    current_auto_review,
    question_snapshot_sha256,
)

OUT = ROOT / "storage/quality-audits/phase45z5-20261013/sample-upgrades/remaining-kept/decisions.json"
DATABASE_URL = "postgresql+psycopg://postgres@127.0.0.1:59227/phase45z5_work_20261013_test"
EXPECTED_IDENTITY = ("phase45z5_work_20261013_test", 59227, 7694698872540080852)

DECISIONS = {
    "989723eb-4fc7-5e2a-ba42-d4aa421f7ba7": (
        "交集由坐标约束求出，再用维数公式计算和空间；并列生成矩阵秩提供独立核对。"
        "保留其子空间交与和的核心概念覆盖。"
    ),
    "c1a29da5-8bb7-5c89-95cc-d37e1828831d": (
        "场景要求区分FCS、IP、TCP与HTTP各自保证的条件，结论聚焦应用层语义错误，"
        "适合作为网络分层边界的情境辨析题。"
    ),
    "6a4072d0-f080-5cd1-af68-51332991dbdf": (
        "需从CPU占比不等式求整数批量下界，再独立检查10微秒延迟上界；"
        "两个约束共同决定可行区间。"
    ),
    "93096536-06fb-5e4f-9ab9-fbf63c27ab20": (
        "题目检验定义域不连通时原函数常数可在各连通分支独立取值这一关键条件；"
        "保留为不定积分部分的边界概念题，不将其单独视作高难度代表。"
    ),
    "7b9af966-9f0f-54f4-82eb-3e54c4b1253a": (
        "需先判断远端IP不在本地子网，再区分ARP下一跳、以太帧目的MAC与端到端IP目的地址，"
        "能够检验网络层与链路层地址语义。"
    ),
}


def main() -> None:
    if OUT.exists():
        raise SystemExit(f"refusing_to_overwrite:{OUT}")
    engine = create_engine(
        DATABASE_URL,
        connect_args={"options": "-c default_transaction_read_only=on"},
    )
    try:
        with Session(engine) as db:
            identity = tuple(db.execute(text(
                "SELECT current_database(), inet_server_port(), system_identifier "
                "FROM pg_control_system()"
            )).one())
            if identity != EXPECTED_IDENTITY:
                raise RuntimeError(f"database_identity_mismatch:{identity}")
            all_public = list(db.scalars(select(Question).where(
                Question.bank_scope == "public"
            )))
            results = []
            for raw_id, rationale in DECISIONS.items():
                question = db.get(Question, UUID(raw_id))
                if question is None:
                    raise RuntimeError(f"missing_question:{raw_id}")
                node = question.kp
                snapshot = question_snapshot_sha256(question)
                current = current_auto_review(question, node)
                if current is None or current.question_snapshot_sha256 != snapshot:
                    raise RuntimeError(f"current_review_not_snapshot_bound:{raw_id}")
                assessment = assess_auto_qualification(
                    db, question, node, all_questions=all_public
                )
                if assessment.get("status") != "AUTO_VERIFIED":
                    raise RuntimeError(
                        f"current_auto_review_failed:{raw_id}:"
                        f"{json.dumps(assessment, ensure_ascii=False, default=str)}"
                    )
                stages = assessment.get("stages", {})
                if not stages or any(stage.get("status") != "PASS" for stage in stages.values()):
                    raise RuntimeError(f"current_stage_failure:{raw_id}")
                results.append({
                    "question_id": raw_id,
                    "node_code": node.code,
                    "node_name": node.name,
                    "subject": node.subject,
                    "decision": "KEEP_WITH_REASON",
                    "rationale": rationale,
                    "content_snapshot_sha256": snapshot,
                    "current_review_event_id": str(current.id),
                    "current_review_version": current.review_version,
                    "current_qualification_class": current.qualification_class,
                    "fresh_assessment": assessment["status"],
                    "stage_statuses": {name: stage["status"] for name, stage in stages.items()},
                    "grader_method": stages.get("grading", {}).get("method"),
                    "human_verified": False,
                })
            report = {
                "version": "phase45z5-sample-keep-dispositions-v1",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "database_identity": {
                    "database": identity[0], "port": identity[1], "system_identifier": identity[2]
                },
                "decision_count": len(results),
                "questions_changed": False,
                "history_tables_changed": False,
                "results": results,
            }
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"status": "RECORDED_READ_ONLY", "decisions": len(results), "path": str(OUT)}))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
