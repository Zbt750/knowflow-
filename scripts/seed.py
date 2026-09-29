"""把 seed/ 下两个 JSON 灌进数据库；可重复运行，第二次不产生重复题、不覆盖练习历史。

用法（项目根执行）：
    python scripts/seed.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from uuid import UUID

# 允许直接以脚本方式运行：把项目根加入 sys.path。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from backend.config import get_settings  # noqa: E402
from backend.db import create_db_engine, create_session_factory  # noqa: E402
from backend.models.learning import (  # noqa: E402
    KnowledgePoint,
    KpMasteryPolicy,
    KpState,
    Question,
)
from backend.services.question_service import (  # noqa: E402
    DuplicateQuestionStemError,
    assert_not_duplicate_stem,
)
from backend.services.lesson_service import sync_builtin_lessons  # noqa: E402
from backend.services.builtin_material_service import (  # noqa: E402
    sync_builtin_reference_materials,
)
from backend.services.exam_reference_service import sync_exam_reference_index  # noqa: E402

SEED_DIR = Path(__file__).resolve().parents[1] / "seed"


def load_json(name: str) -> dict:
    # 显式 utf-8：Windows 默认编码不是 utf-8，中文题干会被读成乱码。
    return json.loads((SEED_DIR / name).read_text(encoding="utf-8"))


def upsert_knowledge_points(
    db: Session, subject: str, nodes: list[dict], parent_id: UUID | None = None
) -> tuple[int, int]:
    """按 code upsert 整棵树；父节点不写 summary / learning_goal。"""
    created = updated = 0
    for index, node in enumerate(nodes, start=1):
        # code 是稳定业务主键，用它判断新建还是更新，脚本才能重复运行。
        kp = db.scalar(select(KnowledgePoint).where(KnowledgePoint.code == node["code"]))
        if kp is None:
            kp = KnowledgePoint(code=node["code"])
            db.add(kp)
            created += 1
        else:
            updated += 1
        kp.name = node["name"]
        kp.subject = subject
        kp.parent_id = parent_id
        kp.ordinal = node.get("ordinal", index)
        kp.is_assessable = bool(node["is_assessable"])
        # 父节点不写摘要与学习目标，避免页面上出现“父节点也能考核”的暗示。
        kp.summary = node.get("summary")
        kp.learning_goal = node.get("learning_goal")
        kp.is_active = True
        kp.is_reference_only = False
        db.flush()  # 先拿到 kp.id，子节点才能挂上 parent_id。

        child_created, child_updated = upsert_knowledge_points(
            db, subject, node.get("children", []), kp.id
        )
        created += child_created
        updated += child_updated
    return created, updated


def ensure_kp_states(db: Session) -> int:
    # 每个可考核叶子都要有一行投影；缺了它，第一次自评会找不到当前状态。
    leaves = db.scalars(
        select(KnowledgePoint).where(KnowledgePoint.is_assessable.is_(True))
    ).all()
    created = 0
    for leaf in leaves:
        if db.get(KpState, leaf.id) is None:
            # manual_credit_count 显式写 0：列默认值只在 flush 时生效。
            db.add(
                KpState(
                    kp_id=leaf.id,
                    state="unseen",
                    evidence_window=[],
                    review_stage=0,
                    manual_credit_count=0,
                    node_self_grade=None,
                    manual_confirmed_at=None,
                )
            )
            created += 1
    return created


def upsert_questions(db: Session, payload: dict) -> tuple[int, int]:
    created = skipped = 0
    for item in payload["questions"]:
        kp = db.scalar(select(KnowledgePoint).where(KnowledgePoint.code == item["kp_code"]))
        if kp is None:
            raise SystemExit(f"题目引用了不存在的 kp_code：{item['kp_code']}")
        if not kp.is_assessable:
            raise SystemExit(f"题目不能挂到父节点：{item['kp_code']}")
        # 幂等键用“同一 kp 下的完整题干”；近似重复交给 3-gram 纯函数拦截。
        existing = list(db.scalars(select(Question.stem).where(Question.kp_id == kp.id)).all())
        if item["stem"] in existing:
            # 题干相同的题不重复插入，但要把分类元数据刷新到最新：
            # 否则升级前录入的题会缺 question_role / skill_tags，
            # 必考考法就永远无法覆盖，毕业条件形同虚设。
            current = db.scalar(
                select(Question).where(Question.kp_id == kp.id, Question.stem == item["stem"])
            )
            if current is not None:
                current.question_type = item["question_type"]
                current.grading_mode = item["grading_mode"]
                current.difficulty = item["difficulty"]
                current.question_role = item.get("question_role", "basic")
                current.skill_tags = list(item.get("skill_tags") or [])
                current.estimated_minutes = int(item.get("estimated_minutes") or 5)
                current.is_variant = item["is_variant"]
                current.variant_group = item["variant_group"]
                current.options = item["options"]
                current.correct_answer = item["correct_answer"]
                current.explanation = item["explanation"]
            skipped += 1
            continue
        try:
            assert_not_duplicate_stem(item["stem"], existing)
        except DuplicateQuestionStemError as exc:
            # 必须让人看见是哪一题，否则改不动。
            raise SystemExit(
                f"{exc}：{item['stem']}（与 {kp.code} 已有题干相似度 >= 0.85，请改写）"
            ) from exc
        db.add(
            Question(
                kp_id=kp.id,
                question_type=item["question_type"],
                grading_mode=item["grading_mode"],
                difficulty=item["difficulty"],
                # 学习角色、考法标签与预计时长是毕业判定与时间预算的输入，必须一起写入。
                question_role=item.get("question_role", "basic"),
                skill_tags=list(item.get("skill_tags") or []),
                estimated_minutes=int(item.get("estimated_minutes") or 5),
                is_variant=item["is_variant"],
                variant_group=item["variant_group"],
                stem=item["stem"],
                options=item["options"],
                correct_answer=item["correct_answer"],
                explanation=item["explanation"],
                is_active=True,
            )
        )
        created += 1
    return created, skipped


def upsert_policies(db: Session, syllabus: dict) -> tuple[int, int]:
    """按知识点写入毕业策略；没有配置的叶子使用默认策略（这里不建行）。"""
    created = updated = 0

    def walk(nodes: list[dict]) -> None:
        nonlocal created, updated
        for node in nodes:
            strategy = node.get("strategy")
            if node.get("is_assessable") and strategy is not None:
                kp = db.scalar(
                    select(KnowledgePoint).where(KnowledgePoint.code == node["code"])
                )
                if kp is None:
                    raise SystemExit(f"策略引用了不存在的 kp_code：{node['code']}")
                row = db.get(KpMasteryPolicy, kp.id)
                if row is None:
                    row = KpMasteryPolicy(kp_id=kp.id)
                    db.add(row)
                    created += 1
                else:
                    updated += 1
                # 策略是「题目要求」，与用户的学习进度无关，因此可以安全覆盖。
                # 用户的进度在 kp_states 里，这里绝不触碰。
                row.min_confirmations = strategy.get("min_confirmations", 3)
                row.min_real_questions = strategy.get("min_real_questions", 3)
                row.required_question_types = dict(strategy.get("required_question_types") or {})
                row.excluded_question_types = list(strategy.get("excluded_question_types") or [])
                row.required_skill_tags = list(strategy.get("required_skill_tags") or [])
                row.required_variant_count = strategy.get("required_variant_count", 1)
                row.min_day_span = strategy.get("min_day_span", 2)
                row.manual_mastered_credit = strategy.get("manual_mastered_credit", 2)
                row.review_intervals_days = list(strategy.get("review_intervals_days") or [7, 15, 30])
                row.max_evidence_window = strategy.get("max_evidence_window", 20)
                row.note = strategy.get("note")
            walk(node.get("children", []))

    walk(syllabus["nodes"])
    return created, updated


def seed_all(db: Session, *, include_exam_references: bool = False) -> dict[str, int]:
    """供脚本与测试共用的入口：整棵树、策略与题库放在一个事务里。"""
    syllabus = load_json("syllabus.json")
    questions = load_json("questions.json")
    created, updated = upsert_knowledge_points(db, syllabus["subject"], syllabus["nodes"])
    states = ensure_kp_states(db)
    # 策略必须在知识点存在之后写；它只描述题目要求，不触碰用户进度。
    policies_created, policies_updated = upsert_policies(db, syllabus)
    new_questions, skipped = upsert_questions(db, questions)
    result = {
        "kp_created": created,
        "kp_updated": updated,
        "states_created": states,
        "policies_created": policies_created,
        "policies_updated": policies_updated,
        "questions_created": new_questions,
        "questions_skipped": skipped,
    }
    # 大型历年索引由发布/初始化脚本显式导入；普通学习闭环测试仍使用小型演示题库。
    if include_exam_references:
        result.update(sync_exam_reference_index(db))
    return result


def main() -> None:
    settings = get_settings()
    engine = create_db_engine(str(settings.active_database_url))
    session_factory = create_session_factory(engine)
    try:
        with session_factory() as db:
            # 中途失败不留半棵树。
            result = seed_all(db, include_exam_references=True)
            lessons = asyncio.run(
                sync_builtin_lessons(db, materials_root=settings.upload_dir)
            )
            references = asyncio.run(
                sync_builtin_reference_materials(db, materials_root=settings.upload_dir)
            )
            db.commit()
            print(f"知识点：新建 {result['kp_created']}，更新 {result['kp_updated']}；KpState 补齐 {result['states_created']}")
            print(f"毕业策略：新建 {result['policies_created']}，更新 {result['policies_updated']}")
            print(f"题目：新建 {result['questions_created']}，已存在跳过 {result['questions_skipped']}")
            print(
                "历年真题索引："
                f"节点新建 {result['nodes_created']} / 更新 {result['nodes_updated']}，"
                f"题号关联新建 {result['references_created']} / 更新 {result['references_updated']}"
            )
            print(
                f"系统讲解：新建 {lessons['created']}，更新 {lessons['updated']}，"
                f"未变 {lessons['unchanged']}（索引由后台任务完成）"
            )
            print(
                f"系统参考资料：新建 {references['created']}，更新 {references['updated']}，"
                f"未变 {references['unchanged']}（索引由后台任务完成）"
            )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
