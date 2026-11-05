"""Deterministic observation projection, independent of the graduation machine."""
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo
from backend.schemas.capability import LearningProgress

SHANGHAI = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class ProgressAttempt:
    question_id: str | None
    practice_item_id: str
    occurred_at: datetime
    result: str
    number: int = 0
    assisted: bool | None = None
    assistance_level: str | None = None
    category: str | None = None
    sequence_version: str | None = None
    history_unknown: bool | None = None
    reliable_current: bool = False
    strict_current_confirmation: bool = False
    content_identity: str | None = None
    skill_tags: tuple[str, ...] = ()


def no_assistance(a):
    return (a.assisted is False and a.assistance_level == "none"
        and a.sequence_version == "attempt-sequence-v1" and a.history_unknown is False
        and a.category in {"first_independent_correct", "independent_retest_correct", "repeat_correct", "ai_consistent_correct_nonconfirming"})


def project_learning_progress(attempts, *, practice_count, history_truncated=False, required_tags=()):
    rows = sorted(attempts, key=lambda a: (a.occurred_at, a.number, a.practice_item_id))
    latest = {}
    for a in rows:
        if a.question_id:
            latest[a.question_id] = a
    corrected = set()
    for a in latest.values():
        earlier = [p for p in rows if p.practice_item_id == a.practice_item_id and p.question_id == a.question_id
            and p.number < a.number and p.result == "wrong"]
        if a.result == "right" and (earlier or a.category in {"self_corrected", "correct_after_ungraded"}):
            corrected.add(a.question_id)
    retests = {a.question_id for a in latest.values() if a.result == "right" and
        (a.assisted is True or a.question_id in corrected or a.category in {
            "hint_assisted_correct", "solution_assisted_correct", "process_review_assisted_correct", "low_confidence_correct"})}
    latest_reliable = {}
    for a in rows:
        if a.question_id and a.reliable_current and a.result in {"right", "wrong"}:
            latest_reliable[a.question_id] = a
    # An unsupported later input cannot erase a previously reliable error.
    unresolved_wrong = {a.question_id for a in latest_reliable.values() if a.result == "wrong"}
    observed_right = [a for a in latest.values() if a.result == "right" and no_assistance(a) and a.question_id not in corrected]
    confirmed = [a for a in rows if a.result == "right" and a.reliable_current and a.strict_current_confirmation and no_assistance(a)]
    distinct_content = {a.content_identity for a in confirmed if a.content_identity}
    dates = [a.occurred_at.astimezone(SHANGHAI).date() for a in confirmed]
    tags = {t for a in confirmed for t in a.skill_tags}
    # No new automatic quality mechanism exists in this phase. Only current,
    # genuinely strict v4 confirmations can support this conservative label.
    stable = (not history_truncated and not unresolved_wrong and not retests and
        len(distinct_content) >= 3 and dates and (max(dates)-min(dates)).days >= 2
        and len(tags) >= 2 and set(required_tags).issubset(tags))
    limits = []
    if not practice_count:
        limits.append("当前知识点缺少可用练习题，不能据此判断你不会。")
    if any(a.assisted is None or a.assistance_level is None or a.history_unknown is not False for a in rows):
        limits.append("部分历史没有完整辅助或序列记录，不能推断独立作答。")
    if any(a.result not in {"right", "wrong"} for a in rows):
        limits.append("未判定结果不计为错误。")
    if history_truncated:
        limits.append("统计仅含最近100次作答，不能据此确认整体稳定性。")
    reference = [a for a in rows if a.result in {"right", "wrong"} and not a.reliable_current]
    reliability = ("部分结果依据参考答案比对，可用于学习观察，不能当成已核验的客观确认。" if reference else
        "可靠的最终答案观察不代表证明或程序过程正确，也不改变原毕业评价。" if any(a.reliable_current for a in rows) else
        "当前数据不足以确认独立掌握；完成记录和未判定结果仍是学习记录。")
    if reference:
        limits.append("参考答案比对不能独立证明答案正确，必要时应换题或复核答案。")
    count = len(latest)
    if not rows:
        status, label, action = "NOT_STARTED", "尚未练习", "practice" if practice_count else "read_lesson"
        reason = "还没有这个知识点的作答记录。"
        step = "先阅读讲解，再完成基础练习。" if practice_count else "可以先阅读知识点讲解，等待可用题目补齐。"
    elif unresolved_wrong:
        status, label, action = "NEEDS_CONSOLIDATION", "待巩固", "consolidate"
        reason = f"最近有{len(unresolved_wrong)}道题的可靠判题结果为错误，建议针对这些内容巩固。"
        step = "回看对应讲解和方法，再做针对性练习或稍后复测。"
    elif retests:
        status, label, action = "RETEST_RECOMMENDED", "建议复测", "delayed_retest"
        reason = f"已练习{count}道在线题，其中{len(retests)}道仍需独立复验（辅助完成、纠错后完成或信心不足的正确记录）；这些记录不直接等于独立掌握。"
        step = "稍后独立复测，或换一道相关题验证；不用马上反复提交同一答案。"
    elif stable:
        status, label, action = "STABLE_PRACTICE", "基础练习表现稳定", "spaced_review"
        reason = "至少3道不同题的当前有效严格确认跨越2天，并覆盖了相应技能；这是有限范围的练习稳定表现。"
        step = "可以间隔复习或尝试进阶题，证明与程序能力仍需单独验证。"
    elif len(observed_right) >= 2 and any(a.result in {"wrong", "unknown"} and
            a.occurred_at < max(r.occurred_at for r in observed_right) for a in rows):
        status, label, action = "IMPROVING", "有进展", "validate_with_other_questions"
        reason = f"在先前比对不一致或未判定记录之后，已有{len(observed_right)}道不同题出现无已记录辅助的正确比对；建议继续验证。"
        step = "选择不同题目验证方法，参考答案的正确比对暂不等于独立掌握。"
    else:
        status, label, action = "PRACTICING", "正在练习", "validate_with_other_questions" if reference else "practice"
        reason = f"已有{len(rows)}次作答记录，涉及{count}道在线题；目前仍以学习观察为主。"
        if reference and any(a.result == "wrong" for a in reference):
            reason += "部分参考答案比对不一致，尚不能确定是能力问题。"
        step = "换一道相关题验证，必要时先复核参考答案。" if reference else "结合讲解继续练习；未判定的题可先对照解析学习。"
    if not practice_count and rows:
        step = "当前没有可用在线题，可以先阅读讲解；不要因库存不足判断自己不会。"
        action = "read_lesson"
    return LearningProgress(status=status, label=label, reason=reason, reliability_note=reliability,
        next_action=action, next_step=step, limitations=limits, observed_attempt_count=len(rows),
        distinct_question_count=count, assisted_correct_question_count=sum(a.result == "right" and a.assisted is True for a in latest.values()),
        reference_wrong_count=sum(a.result == "wrong" for a in reference),
        reliable_wrong_count=sum(a.result == "wrong" and a.reliable_current for a in rows),
        unknown_count=sum(a.result not in {"right", "wrong"} for a in rows), history_truncated=history_truncated)
