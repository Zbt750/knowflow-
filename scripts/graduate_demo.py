"""毕业演示脚本：把学习状态准备成「今天就能毕业」。

为什么需要它
------------
毕业规则要求「首尾有效确认的上海日期相差至少 2 天」。
如果今天一次性做完所有题，跨度恒为 0，状态只能停在 consolidating，
要验证毕业就必须等真实的两天过去。

这个脚本把「第一天」的真实学习记录移到两天前，
于是**今天打开页面做一道针对性的题就能毕业**——不需要改系统时间，
也不需要等。

它做什么
--------
`first`（第一天）：
  1. 清空今日计划与练习历史（知识点、题库、策略都保留）；
  2. 生成今天的练习卷，并真实地按缺口把题目做完（默认全选「已掌握」）；
  3. 把这次学习的时间整体移到两天前。
     此时唯一的缺口就是「跨天确认」。

`retest`（复测日）：
  1. 检查跨天是否已经成立；
  2. 在页面准备复测题：
     - 如果题库还有没做过的、能补缺口的题，今天重新生成一份卷；
     - 否则把卷内那道「最久没确认」的题恢复为未完成，供你重做（复测）。
  3. 打印还缺什么、接下来做哪道题。

它不做什么
----------
不会替你毕业：最后那一步必须由你在页面上真实作答并自评。
不会伪造 QuestionAttempt，也不会把任何节点直接改成 mastered。

推荐用法（CMD，项目根目录）
---------------------------
    scripts\\graduate-demo.cmd first     准备第一天（做完题并把时间移到两天前）
    scripts\\graduate-demo.cmd retest    准备复测日（拿一道复测题）
    scripts\\graduate-demo.cmd show      只看当前毕业缺口

也可以在页面里自己做：`first` 之后打开 /study，用「追加练习题」把变式题
加进今天的卷，做完并自评「已掌握」就会毕业。
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from backend.config import get_settings  # noqa: E402
from backend.db import create_db_engine, create_session_factory  # noqa: E402
from backend.mastery.enums import MasteryState, SelfGrade  # noqa: E402
from backend.mastery.policy import MasteryPolicy  # noqa: E402
from backend.mastery.rules import SHANGHAI, analyze_gaps  # noqa: E402
from backend.mastery.selection import QuestionCandidate, select_questions  # noqa: E402
from backend.mastery.storage import policy_from_storage, snapshot_from_storage  # noqa: E402
from backend.models.learning import (  # noqa: E402
    DailyPlan,
    KnowledgePoint,
    KpMasteryPolicy,
    KpState,
    PracticeItem,
    Question,
    QuestionAttempt,
)
from backend.services.attempt_service import assess_practice_item  # noqa: E402
from backend.services.practice_service import (  # noqa: E402
    PlanAlreadyGeneratedError,
    create_initial_plan,
)
from backend.services.practice_service import _candidates_for  # noqa: E402

SPAN_DAYS = 2


def _today() -> datetime:
    """当前时刻（UTC，带时区）；学习日按上海日期换算。"""
    return datetime.now(timezone.utc)


def _study_date(now: datetime):
    return now.astimezone(SHANGHAI).date()


def _clear_today(db) -> None:
    """清空今日计划与练习历史；知识点、题库与毕业策略都保留。"""
    from sqlalchemy import text

    for table in ("question_attempts", "learning_events", "practice_items", "daily_plans"):
        db.execute(text(f"DELETE FROM {table}"))
    for state in db.scalars(select(KpState)).all():
        state.state = MasteryState.UNSEEN.value
        state.evidence_window = []
        state.review_stage = 0
        state.next_review_at = None
        state.mastered_at = None
        state.node_self_grade = None
        state.manual_credit_count = 0
        state.manual_confirmed_at = None


def _shift_all(db, *, days: int) -> dict[str, int]:
    """把三张表里的时间整体前移 days 天（复用 shift_learning_days 的逻辑）。"""
    from scripts.shift_learning_days import shift_learning_data

    return shift_learning_data(db, days=days)


def _leaf_by_keyword(db, keyword: str) -> KnowledgePoint:
    rows = db.scalars(
        select(KnowledgePoint).where(KnowledgePoint.is_assessable.is_(True))
    ).all()
    for row in rows:
        if keyword in row.name:
            return row
    raise SystemExit(f"找不到包含「{keyword}」的可考核知识点")


def _finish_first_day(db, *, kp: KnowledgePoint, now: datetime) -> dict[str, object]:
    """生成今天的卷并真实做完，然后统计缺口。"""
    plan = create_initial_plan(
        db,
        study_date=_study_date(now),
        selected_kp_ids=[kp.id],
        now=now,
    )
    db.flush()

    items = db.scalars(
        select(PracticeItem).where(PracticeItem.plan_id == plan.id).order_by(PracticeItem.ordinal)
    ).all()
    done = 0
    for index, item in enumerate(items, start=1):
        # 用真实的自评事务写完三张表；这里只是替用户点「已掌握」。
        assess_practice_item(
            db,
            item_id=item.id,
            raw_answer=None,
            self_grade=SelfGrade.MASTERED,
            idempotency_key=f"graduate-demo-{now.timestamp()}-{index}",
            now=now,
        )
        done += 1
    return {"plan_id": plan.id, "items": done}


def _report(db, *, kp: KnowledgePoint) -> None:
    state = db.get(KpState, kp.id)
    if state is None:
        print(f"  {kp.name}：还没有状态行，请先执行 first")
        return
    policy = policy_from_storage(db.get(KpMasteryPolicy, kp.id))
    snapshot = snapshot_from_storage(state)
    report = analyze_gaps(
        snapshot.evidence_window,
        manual_credit_count=snapshot.manual_credit_count,
        manual_confirmed_at=snapshot.manual_confirmed_at,
        policy=policy,
    )
    print(f"  {kp.name}：当前状态 {state.state}")
    for item in report.items:
        mark = "OK" if item.satisfied else "缺"
        print(f"      [{mark}] {item.label}: {item.current}/{item.required}")
    if report.can_graduate:
        print("      → 已满足全部毕业条件")
    else:
        print(f"      → 下一步：{report.next_step}")
    dates = sorted(e.occurred_at.astimezone(SHANGHAI).date() for e in snapshot.evidence_window)
    if dates:
        print(f"      确认日期：{dates[0]} → {dates[-1]}（跨 {(dates[-1] - dates[0]).days} 天）")


def cmd_first(db, args) -> int:
    now = _today()
    kp = _leaf_by_keyword(db, args.kp)
    print(f"=== 准备第一天：{kp.name} ===")
    _clear_today(db)
    db.flush()

    info = _finish_first_day(db, kp=kp, now=now)
    print(f"  已生成并做完 {info['items']} 道题（全部自评「已掌握」）")

    counts = _shift_all(db, days=SPAN_DAYS)
    db.commit()
    print(
        f"  已把这些学习记录的时间整体前移 {SPAN_DAYS} 天"
        f"（{counts['attempts']} 条作答、{counts['events']} 条事件、{counts['kp_states']} 条状态）"
    )
    print()
    print("现在这一步做完之后的缺口：")
    _report(db, kp=kp)
    print()
    print("接下来（任选一种）：")
    print("  A. 页面操作：打开 http://127.0.0.1:5173/study")
    print("     → 点「追加练习题」把该知识点的变式题加进今天的卷 → 做完并自评「已掌握」→ 应当毕业")
    print("  B. 命令行：执行 scripts\\graduate-demo.cmd retest")
    print("     → 脚本会把一道「最久没确认」的题放到今天的卷里，你去页面做它即可")
    return 0


def cmd_retest(db, args) -> int:
    now = _today()
    kp = _leaf_by_keyword(db, args.kp)
    print(f"=== 准备复测日：{kp.name} ===")
    _report(db, kp=kp)

    state = db.get(KpState, kp.id)
    if state is None:
        print("  还没有学习记录，请先执行 graduate-demo.cmd first")
        return 1
    if state.state == MasteryState.MASTERED.value:
        print("  该知识点已经毕业；要重新演示请先执行 first")
        return 0

    policy = policy_from_storage(db.get(KpMasteryPolicy, kp.id))
    snapshot = snapshot_from_storage(state)
    rows = list(
        db.scalars(
            select(Question).where(Question.kp_id == kp.id, Question.is_active.is_(True))
        ).all()
    )
    candidates = _candidates_for(db, kp.id, rows)
    selection = select_questions(
        policy,
        snapshot.evidence_window,
        candidates,
        manual_credit_count=snapshot.manual_credit_count,
        manual_confirmed_at=snapshot.manual_confirmed_at,
        reference_time=now,
    )

    today = _study_date(now)
    existing = db.scalar(select(DailyPlan).where(DailyPlan.study_date == today.isoformat()))

    if selection.items:
        picked = {UUID(item.question_id) for item in selection.items}
        print()
        print(f"  今天的复测题（{len(selection.items)} 道）：")
        for item in selection.items:
            tag = "复测" if item.is_review else "新题"
            print(f"      [{tag}] {item.question_type} {item.estimated_minutes} 分钟 —— {item.reason}")
    else:
        picked = set()
        print()
        print("  选题算法没有给出新题；下面用「最久没确认」的题兜底。")

    if existing is None:
        # 今天还没有卷：直接用选中的题生成。
        if not picked:
            # 缺口已补齐时给最久没确认的一道题。
            window_ids = {
                str(entry.get("question_id")) for entry in (state.evidence_window or [])
            }
            oldest = next(
                (
                    row
                    for row in rows
                    if str(row.id) in window_ids
                ),
                rows[0] if rows else None,
            )
            if oldest is None:
                print("  该知识点题库为空，无法复测")
                return 1
            picked = {oldest.id}
        plan = DailyPlan(study_date=today.isoformat(), status="active")
        db.add(plan)
        db.flush()
        for ordinal, question_id in enumerate(sorted(picked, key=str), start=1):
            db.add(
                PracticeItem(
                    plan_id=plan.id,
                    question_id=question_id,
                    kp_id=kp.id,
                    ordinal=ordinal,
                )
            )
        print(f"  已为今天生成复测卷（{len(picked)} 道题）")
    else:
        # 今天已有卷：把选中的题恢复为未完成，追加到卷尾。
        existing_ids = {
            item.question_id
            for item in db.scalars(
                select(PracticeItem).where(PracticeItem.plan_id == existing.id)
            ).all()
        }
        if not picked:
            window_ids = {
                str(entry.get("question_id")) for entry in (state.evidence_window or [])
            }
            oldest = next((row for row in rows if str(row.id) in window_ids), None)
            if oldest is None:
                print("  没有可复测的题")
                return 1
            picked = {oldest.id}

        next_ordinal = (
            db.scalar(
                select(PracticeItem.ordinal)
                .where(PracticeItem.plan_id == existing.id)
                .order_by(PracticeItem.ordinal.desc())
            )
            or 0
        )
        added = 0
        for question_id in sorted(picked, key=str):
            # 逐题直接查：卷里已有这道题时，把它恢复为未完成，用户才能重做一次。
            # 不做集合比对，避免 UUID 与字符串比较导致的漏判。
            item = db.scalar(
                select(PracticeItem).where(
                    PracticeItem.plan_id == existing.id,
                    PracticeItem.question_id == question_id,
                )
            )
            if item is not None:
                if item.completed_at is not None:
                    item.completed_at = None
                    item.latest_self_grade = None
                    added += 1
                continue
            next_ordinal += 1
            db.add(
                PracticeItem(
                    plan_id=existing.id,
                    question_id=question_id,
                    kp_id=kp.id,
                    ordinal=next_ordinal,
                )
            )
            added += 1
        existing.status = "active"
        db.flush()
        total_items = len(
            db.scalars(
                select(PracticeItem).where(PracticeItem.plan_id == existing.id)
            ).all()
        )
        pending_items = len(
            db.scalars(
                select(PracticeItem).where(
                    PracticeItem.plan_id == existing.id,
                    PracticeItem.completed_at.is_(None),
                )
            ).all()
        )
        if added:
            print(f"  已把 {added} 道复测题准备成「待做」")
        else:
            print("  复测题已经在今天的卷里且待做，直接去页面做它即可")
        print(
            f"  今天的卷共 {total_items} 道，其中待做 {pending_items} 道"
            f"（已完成的题在专注模式会自动隐藏，打开页面看到的就是待做题）"
        )

    db.commit()
    print()
    print("接下来：打开 http://127.0.0.1:5173/study，做完那道复测题并自评「已掌握」。")
    print("如果这是首尾确认跨 2 天的最后一次确认，状态会变成「已毕业」。")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="把学习状态准备成「今天就能毕业」，用于验证跨天毕业规则",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "action",
        choices=("first", "retest", "show"),
        help="first=准备第一天；retest=准备复测日；show=只看当前缺口",
    )
    parser.add_argument("--kp", default="洛必达", help="知识点名称关键词（默认：洛必达）")
    args = parser.parse_args()

    engine = create_db_engine(str(get_settings().active_database_url))
    session_factory = create_session_factory(engine)
    try:
        with session_factory() as db:
            if args.action == "show":
                _report(db, kp=_leaf_by_keyword(db, args.kp))
                return
            if args.action == "first":
                cmd_first(db, args)
                return
            cmd_retest(db, args)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()