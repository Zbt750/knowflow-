"""测试辅助：把已有学习记录的时间整体前移，用来验证「跨天毕业」规则。

为什么需要它
------------
毕业规则要求「首尾有效确认的上海日期相差至少 2 天」。
如果今天把题一次性做完，跨度恒为 0 天，状态只会停在 consolidating；
要验证毕业，要么真的等两天，要么用这个脚本把历史时间挪到过去。

它改什么、不改什么
------------------
只改时间戳：
  - question_attempts.submitted_at
  - learning_events.occurred_at 及其 payload 内的时间字段
  - kp_states.evidence_window 里每条证据的 occurred_at、manual_confirmed_at
  - kp_states.next_review_at、mastered_at

不改自评结果、不改证据窗口的内容、不动知识点与题库。
**绝不伪造 QuestionAttempt，也不会把任何节点直接改成 mastered** ——
变式题与新的确认必须由你真实作答产生。

参数语义（只有一个，避免歧义）
----------------------------
    --days N   把「第一天」挪到 N 天前（N > 0）。
               所有时间戳统一往前移 N 天，日期之间原有的间隔保持不变。

    --to-shifted-target-days N 与 --days 同义（保留给习惯另一种说法的用法）。

    --show     只打印当前毕业条件，不做任何修改。

典型用法
--------
    # 1) 先看现在差什么
    python scripts/shift_learning_days.py --show

    # 2) 假设「今天」是两天后：把已有记录整体挪到 2 天前
    python scripts/shift_learning_days.py --days 2

    # 3) 然后在 /study 或 /knowledge 真实补做一道「变式题」并自评已掌握 → 毕业
    #    （洛必达法则的变式题在题库里；用「追加练习题」或知识树把它加进今天的卷）

    # 4) 要回到真实时间：用相反的天数挪回来
    python scripts/shift_learning_days.py --days -2
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from backend.config import get_settings  # noqa: E402
from backend.db import create_db_engine, create_session_factory  # noqa: E402
from backend.mastery.enums import EvidenceLevel  # noqa: E402
from backend.mastery.policy import MasteryPolicy  # noqa: E402
from backend.mastery.rules import SHANGHAI, effective_confirmation_count  # noqa: E402
from backend.mastery.storage import snapshot_from_storage  # noqa: E402
from backend.models.learning import (  # noqa: E402
    KnowledgePoint,
    KpMasteryPolicy,
    KpState,
    LearningEvent,
    QuestionAttempt,
)

# payload 里可能出现的时间字段；整体平移时都要跟着改。
PAYLOAD_TIME_KEYS = ("next_review_at", "mastered_at", "occurred_at")


def _shift(value: datetime | None, delta: timedelta) -> datetime | None:
    return value + delta if value is not None else None


def _shift_iso(text: object, delta: timedelta) -> object:
    """把 payload 里的 ISO 时间字符串一起平移；解析失败时原样返回。"""
    if not isinstance(text, str):
        return text
    try:
        return (datetime.fromisoformat(text) + delta).isoformat()
    except ValueError:
        return text


def shift_learning_data(db, *, days: int) -> dict[str, int]:
    """把历史时间整体移 days 天。days 为正表示移到过去，为负表示移回未来。"""
    delta = timedelta(days=-days)
    counts = {"attempts": 0, "events": 0, "kp_states": 0}

    for attempt in db.scalars(select(QuestionAttempt)).all():
        attempt.submitted_at = _shift(attempt.submitted_at, delta)
        attempt.next_review_at = _shift(attempt.next_review_at, delta)
        counts["attempts"] += 1

    for event in db.scalars(select(LearningEvent)).all():
        event.occurred_at = _shift(event.occurred_at, delta)
        payload = dict(event.payload or {})
        for key in PAYLOAD_TIME_KEYS:
            if key in payload:
                payload[key] = _shift_iso(payload[key], delta)
        event.payload = payload
        counts["events"] += 1

    for state in db.scalars(select(KpState)).all():
        state.next_review_at = _shift(state.next_review_at, delta)
        state.mastered_at = _shift(state.mastered_at, delta)
        state.manual_confirmed_at = _shift(state.manual_confirmed_at, delta)
        window = []
        for item in state.evidence_window or []:
            entry = dict(item)
            entry["occurred_at"] = _shift_iso(entry.get("occurred_at"), delta)
            window.append(entry)
        state.evidence_window = window
        counts["kp_states"] += 1

    return counts


def report_graduation_state(db) -> None:
    """打印每个叶子的毕业缺口；判定逻辑与状态机完全一致。

    这里直接复用 `analyze_gaps()`，避免脚本自己算一套「毕业条件」——
    那样一旦规则升级，脚本就会给出与真实判定不同的结论。
    """
    from backend.mastery.rules import SHANGHAI, analyze_gaps
    from backend.mastery.storage import policy_from_storage, snapshot_from_storage

    policies = {
        row.kp_id: policy_from_storage(row)
        for row in db.scalars(select(KpMasteryPolicy)).all()
    }
    rows = db.execute(
        select(KnowledgePoint, KpState)
        .join(KpState, KpState.kp_id == KnowledgePoint.id)
        .where(KnowledgePoint.is_assessable.is_(True))
        .order_by(KnowledgePoint.ordinal, KnowledgePoint.code)
    ).all()

    print("")
    for kp, state in rows:
        snapshot = snapshot_from_storage(state)
        policy = policies.get(kp.id)
        if policy is None:
            from backend.mastery.policy import MasteryPolicy

            policy = MasteryPolicy()
        report = analyze_gaps(
            snapshot.evidence_window,
            manual_credit_count=snapshot.manual_credit_count,
            manual_confirmed_at=snapshot.manual_confirmed_at,
            policy=policy,
        )
        status = "已毕业" if state.state == "mastered" else state.state
        print(f"  {kp.name}（{status}）")
        for item in report.items:
            mark = "OK" if item.satisfied else "缺"
            print(f"      [{mark}] {item.label}: {item.current}/{item.required}")
        if report.can_graduate:
            print("      → 已满足全部毕业条件")
        else:
            print(f"      → 下一步：{report.next_step}")

        window = snapshot.evidence_window
        if window:
            dates = sorted(e.occurred_at.astimezone(SHANGHAI).date() for e in window)
            print(f"      确认日期：{dates[0]} → {dates[-1]}（跨 {(dates[-1]-dates[0]).days} 天）")
        print("")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="把已有学习记录的时间整体前移，用来验证跨天毕业规则",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--days",
        type=int,
        default=None,
        help="把历史时间前移的天数。正数=移到过去（模拟已过去 N 天），负数=移回未来",
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="只打印当前毕业条件，不做任何修改",
    )
    args = parser.parse_args()

    if not args.show and args.days is None:
        parser.print_help()
        print("\n提示：先用 --show 查看现状，再用 --days 2 把历史挪到两天前。")
        return

    settings = get_settings()
    engine = create_db_engine(str(settings.active_database_url))
    session_factory = create_session_factory(engine)
    try:
        with session_factory() as db:
            if args.days is not None:
                print("修改前：")
                report_graduation_state(db)

                counts = shift_learning_data(db, days=args.days)
                db.commit()

                from datetime import datetime, timedelta, timezone

                today = datetime.now(timezone.utc).astimezone(SHANGHAI).date()
                if args.days > 0:
                    print(
                        f"已把 {counts['attempts']} 条练习记录、{counts['events']} 条学习事件、"
                        f"{counts['kp_states']} 条状态投影的时间整体前移 {args.days} 天。"
                    )
                    print(
                        f"『现在』被当作 {today + timedelta(days=args.days)}"
                        f"（真实日期是 {today}）。"
                    )
                    print(
                        "也就是说：所有历史确认都变成了更早的日期，"
                        "与今天的距离就拉开了，跨天毕业条件因此可以被满足。"
                    )
                else:
                    print(
                        f"已把时间整体后移 {abs(args.days)} 天（移回真实时间）。"
                    )
                print(
                    "注意：变式题与新的确认必须由你真实作答产生，脚本不会代做。"
                )

            print("修改后：" if args.days is not None else "当前：")
            report_graduation_state(db)
            if args.days is not None and args.days > 0:
                print("接下来的操作（按这个顺序）：")
                print("  1. 打开或刷新 http://127.0.0.1:5173/study")
                print("     如果今天已经有练习卷，点「追加练习题」把变式题加进来；")
                print("     想重新生成整卷就先执行 scripts\\reset-today.cmd（会清空练习记录）。")
                print("  2. 做那道真实变式题并自评「已掌握」→ 首尾确认跨天，应当毕业。")
                print("  3. 想回到真实时间：再执行一次本脚本并把天数取负。")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()