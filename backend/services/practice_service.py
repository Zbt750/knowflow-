from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.mastery.enums import MasteryState, QuestionType, TimeBudget
from backend.mastery.policy import MasteryPolicy
from backend.mastery.rules import pool_capacity_check
from backend.mastery.selection import (
    Priority,
    QuestionCandidate,
    SelectionItem,
    select_questions,
)
from backend.mastery.storage import policy_from_storage, snapshot_from_storage
from backend.mastery.types import MasterySnapshot
from backend.models.learning import (
    DailyPlan,
    ExamQuestionReference,
    KnowledgePoint,
    KpMasteryPolicy,
    KpState,
    PracticeItem,
    Question,
    QuestionAttempt,
)
from backend.services.question_eligibility import question_eligibility

# 单个知识点在一次组卷里最多放几道题：避免一个缺口很大的叶子独占整张卷。
DEFAULT_PER_KP_LIMIT = 5

# 新卷按作答形式由短到长排列；同类题保持选题器给出的优先顺序。
QUESTION_TYPE_ORDER = {
    QuestionType.SINGLE_CHOICE.value: 0,
    QuestionType.FILL_BLANK.value: 1,
    QuestionType.CALCULATION.value: 2,
    QuestionType.PROOF.value: 3,
    QuestionType.SUBJECTIVE.value: 4,
    QuestionType.EXTERNAL_EXAM.value: 5,
}


def _empty_snapshot() -> MasterySnapshot:
    """叶子还没有状态投影时的初始快照（等价于「从未学习」）。"""
    return MasterySnapshot(MasteryState.UNSEEN, (), 0, None, None, None, 0, None)


class PlanAlreadyGeneratedError(ValueError):
    """同一学习日已有活动计划，不能重新洗牌。"""


def _require_assessable_leaf(session: Session, kp_id: UUID) -> KnowledgePoint:
    # 父节点只是汇总器；把父节点交给组卷会让题目归属和毕业条件失去确定性。
    kp = session.get(KnowledgePoint, kp_id)
    if kp is None or not kp.is_active:
        raise ValueError("knowledge_point_not_found")
    if not kp.is_assessable:
        raise ValueError("node_not_assessable")
    return kp


def create_initial_plan(
    session: Session,
    *,
    study_date: date,
    selected_kp_ids: list[UUID],
    now: datetime,
    budget: str = TimeBudget.STANDARD.value,
    per_kp_limit: int = DEFAULT_PER_KP_LIMIT,
) -> DailyPlan:
    """把用户选定的叶子节点转成一份活动练习卷；同一天只允许生成一次。

    选题不再固定「2 基础 + 1 变式」，而是按每个叶子自己的毕业缺口与时间预算决定。
    """
    # 先加锁查当天计划；study_date 有唯一约束，所以必须按“这一天”判重而不是只按 active 判重。
    existing = session.scalar(
        select(DailyPlan).where(DailyPlan.study_date == study_date.isoformat()).with_for_update()
    )
    if existing is not None:
        raise PlanAlreadyGeneratedError("plan_already_generated")
    unique_kp_ids = list(dict.fromkeys(selected_kp_ids))
    if not unique_kp_ids:
        raise ValueError("no_assessable_leaf_selected")
    for kp_id in unique_kp_ids:
        _require_assessable_leaf(session, kp_id)

    # study_date 列是 String(10)，统一存 ISO 日期字符串，和 KpState 的日期口径一致。
    plan = DailyPlan(study_date=study_date.isoformat(), status="active")
    session.add(plan)
    session.flush()  # 取得 plan.id，才能让下面的 PracticeItem 外键指向它。

    picked_items: list[tuple[UUID, SelectionItem, str, UUID | None, UUID | None]] = []
    for kp_id in unique_kp_ids:
        # 这个叶子自己的毕业策略与当前进度：缺口选题的两个输入。
        policy = policy_from_storage(session.get(KpMasteryPolicy, kp_id))
        state = session.get(KpState, kp_id)
        snapshot = (
            snapshot_from_storage(state) if state is not None else _empty_snapshot()
        )
        online_rows = list(session.scalars(select(Question).where(
            Question.kp_id == kp_id, Question.is_active.is_(True)
        ).order_by(Question.question_type, Question.id)).all())
        reference_node = session.get(KnowledgePoint, kp_id).is_reference_only
        rows = [row for row in online_rows if question_eligibility(row, session.get(KnowledgePoint, kp_id)).practice_eligible]
        if not rows:
            # Source pointers are useful for reading, but contain no answerable stem.
            raise ValueError("question_pool_incomplete")
        if reference_node:
            # A reference node may now contain actual online source questions.
            # Selection-only policy: NEVER persist it or weaken graduation rules.
            # Unverified transcripts still yield no objective confirmation.
            policy = MasteryPolicy(min_confirmations=1, min_real_questions=1,
                required_question_types={row.question_type: 1 for row in rows},
                required_variant_count=0, manual_mastered_credit=0,
                note="仅用于选择已有在线题，原节点毕业策略保持不变")
        # 题库必须足以满足这个知识点自己的策略；排除的题型不参与检查。
        pool_by_type: dict[str, int] = {}
        for row in rows:
            pool_by_type[row.question_type] = pool_by_type.get(row.question_type, 0) + 1
        if not pool_capacity_check(policy, pool_by_type):
            # 事务由 route 回滚，DailyPlan 与已暂存的 PracticeItem 不会留下半张卷。
            raise ValueError("question_pool_incomplete")

        # 按缺口选这个叶子的题；每个叶子至少给一道，保证今天的卷确实覆盖到它。
        selection = select_questions(
            policy,
            snapshot.evidence_window,
            _candidates_for(session, kp_id, rows),
            manual_credit_count=snapshot.manual_credit_count,
            manual_confirmed_at=snapshot.manual_confirmed_at,
            budget=budget,
            limit=per_kp_limit,
            # 复测日能否给出题，取决于「今天」相对上次确认隔了多久。
            reference_time=now,
        )
        picked = list(selection.items)
        if not picked:
            # 缺口都补齐时（例如已毕业且未到复测日）仍给一道最需要巩固的题，
            # 否则用户勾了这个知识点却看不到任何题目，会以为系统出错。
            picked = _fallback_picks(rows, policy, limit=1)

        question_types = {str(row.id): row.question_type for row in rows}
        for item in picked:
            picked_items.append((kp_id, item, question_types[item.question_id], UUID(item.question_id), None))

    # 只在初次组卷时排一次序。已有卷和后续追加仍按原 ordinal 保持稳定。
    picked_items.sort(key=lambda entry: QUESTION_TYPE_ORDER.get(entry[2], len(QUESTION_TYPE_ORDER)))
    for ordinal, (kp_id, item, _, question_id, exam_reference_id) in enumerate(picked_items, start=1):
        session.add(
            PracticeItem(
                plan_id=plan.id,
                question_id=question_id,
                exam_reference_id=exam_reference_id,
                kp_id=kp_id,
                ordinal=ordinal,
            )
        )
    return plan


def _candidates_for(
    session: Session, kp_id: UUID, rows: list[Question]
) -> list[QuestionCandidate]:
    """把题库行转成选题所需的候选信息（最近自评、是否已确认）。"""
    # 每道题最近一次练习时间与自评结果，用于识别「上次未掌握」与「最久未复测」。
    history = session.execute(
        select(
            QuestionAttempt.question_id,
            func.max(QuestionAttempt.submitted_at),
        )
        .where(QuestionAttempt.kp_id == kp_id)
        .group_by(QuestionAttempt.question_id)
    ).all()
    last_practiced = {row[0]: row[1] for row in history}

    # practice_items 里同一道题可能被练过多次，取最近一次的自评结果。
    latest_grade: dict[UUID, str | None] = {}
    for item in session.scalars(
        select(PracticeItem)
        .where(PracticeItem.kp_id == kp_id, PracticeItem.latest_self_grade.is_not(None))
        .order_by(PracticeItem.ordinal)
    ).all():
        latest_grade[item.question_id] = item.latest_self_grade

    state = session.get(KpState, kp_id)
    confirmed_ids: set[str] = set()
    if state is not None:
        confirmed_ids = {
            str(entry.get("question_id"))
            for entry in (state.evidence_window or [])
            if entry.get("question_id")
        }

    candidates: list[QuestionCandidate] = []
    for row in rows:
        candidates.append(
            QuestionCandidate(
                question_id=str(row.id),
                question_type=row.question_type,
                skill_tags=tuple(row.skill_tags or ()),
                is_variant=row.is_variant,
                estimated_minutes=row.estimated_minutes,
                last_self_grade=latest_grade.get(row.id),
                last_practiced_at=last_practiced.get(row.id),
                confirmed=str(row.id) in confirmed_ids,
                pending_objective_review=state is not None and str(row.id) in (state.pending_review_question_ids or []),
            )
        )
    return candidates


def _exam_candidates_for(
    session: Session, kp_id: UUID, rows: list[ExamQuestionReference]
) -> list[QuestionCandidate]:
    """把来源索引行作为可自评的外部原卷任务，不生成虚构题干。"""
    ids = [row.id for row in rows]
    history = session.execute(
        select(QuestionAttempt.exam_reference_id, func.max(QuestionAttempt.submitted_at))
        .where(
            QuestionAttempt.kp_id == kp_id,
            QuestionAttempt.exam_reference_id.in_(ids or []),
        )
        .group_by(QuestionAttempt.exam_reference_id)
    ).all()
    last_practiced = {row[0]: row[1] for row in history}
    latest_grade: dict[UUID, str | None] = {}
    for item in session.scalars(
        select(PracticeItem)
        .where(
            PracticeItem.kp_id == kp_id,
            PracticeItem.exam_reference_id.in_(ids or []),
            PracticeItem.latest_self_grade.is_not(None),
        )
        .order_by(PracticeItem.ordinal)
    ).all():
        if item.exam_reference_id is not None:
            latest_grade[item.exam_reference_id] = item.latest_self_grade

    state = session.get(KpState, kp_id)
    confirmed_ids: set[str] = set()
    if state is not None:
        confirmed_ids = {
            str(entry.get("question_id"))
            for entry in (state.evidence_window or [])
            if entry.get("question_id")
        }
    return [
        QuestionCandidate(
            question_id=str(row.id),
            question_type=QuestionType.EXTERNAL_EXAM.value,
            skill_tags=(row.topic_label,),
            is_variant=False,
            estimated_minutes=15,
            last_self_grade=latest_grade.get(row.id),
            last_practiced_at=last_practiced.get(row.id),
            confirmed=str(row.id) in confirmed_ids,
        )
        for row in rows
    ]


def _fallback_picks(
    rows: list[Question], policy: MasteryPolicy, *, limit: int
) -> list[SelectionItem]:
    """缺口已经补齐时的兜底：给最久没有练过的题，保持复习手感。

    这里不再按耗时排序：缺口补齐后用户是在做维护性复习，
    挑「最久没碰过的题」比挑「最短的题」更有价值。
    真正决定复测内容的是 `select_questions`；这里只是它一道题都没给出时的兜底。
    """
    usable = [row for row in rows if row.question_type not in policy.excluded_question_types]
    usable.sort(key=lambda row: str(row.id))
    return [
        SelectionItem(
            question_id=str(row.id),
            question_type=row.question_type,
            is_variant=row.is_variant,
            estimated_minutes=row.estimated_minutes,
            priority=Priority.DUE_REVIEW,
            reason="复习巩固",
            is_review=True,
        )
        for row in usable[:limit]
    ]


def _fallback_exam_picks(
    rows: list[ExamQuestionReference], policy: MasteryPolicy, *, limit: int
) -> list[SelectionItem]:
    usable = [row for row in rows if QuestionType.EXTERNAL_EXAM.value not in policy.excluded_question_types]
    usable.sort(key=lambda row: (row.year, row.question_number))
    return [
        SelectionItem(
            question_id=str(row.id),
            question_type=QuestionType.EXTERNAL_EXAM.value,
            is_variant=False,
            estimated_minutes=15,
            priority=Priority.DUE_REVIEW,
            reason="复习历年真题",
            is_review=True,
        )
        for row in usable[:limit]
    ]


def append_questions_to_plan(
    session: Session, *, plan_id: UUID, question_ids: list[UUID]
) -> int:
    """只从已有题库追加到卷尾；不重洗、不重新生成、不追加重复题。

    允许对 `completed` 的卷继续追加：产品规则要求「追加到 max(ordinal)+1 的卷尾」，
    而 completed 只表示「刚才所有题都做完了」，不代表「今天不许再练」。
    追加成功后把卷改回 `active`，避免同一张卷同时呈现“已完成”和“有待做题”两种矛盾状态。
    真正不允许追加的只有还没生成的草稿卷。
    """
    session.flush()  # Don't discard caller changes when refreshing lock snapshots.
    plan = session.scalar(select(DailyPlan).where(DailyPlan.id == plan_id).with_for_update()
                          .execution_options(populate_existing=True))
    if plan is None:
        raise ValueError("plan_not_found")
    if plan.status not in {"active", "completed"}:
        # draft 表示这张卷还没生成好，不能往里塞题。
        raise ValueError("plan_not_active")
    next_ordinal = (
        session.scalar(select(func.max(PracticeItem.ordinal)).where(PracticeItem.plan_id == plan.id))
        or 0
    ) + 1
    existing_ids = set(
        session.scalars(select(PracticeItem.question_id).where(PracticeItem.plan_id == plan.id)).all()
    )
    if len(set(question_ids)) != len(question_ids):
        raise ValueError("duplicate_question")
    unique_ids = list(question_ids)
    # Keep current node/question eligibility stable until the append commits.
    # Node-first ordering matches content maintenance and Agent confirmation.
    expected_nodes = dict(session.execute(select(Question.id, Question.kp_id).where(Question.id.in_(unique_ids))).all())
    nodes = {node.id: node for node in session.scalars(select(KnowledgePoint)
        .where(KnowledgePoint.id.in_(set(expected_nodes.values())))
        .order_by(KnowledgePoint.code).with_for_update().execution_options(populate_existing=True))}
    questions = {q.id: q for q in session.scalars(select(Question).where(Question.id.in_(unique_ids))
        .order_by(Question.id).with_for_update().execution_options(populate_existing=True))}
    # Validate the complete preview before writing any row. Partial success is
    # never reported when an item was already selected or has lost eligibility.
    for question_id in unique_ids:
        question = questions.get(question_id)
        if question is None or not question.is_active:
            raise ValueError("question_not_found")
        if question.kp_id != expected_nodes.get(question_id):
            raise ValueError("question_not_found")
        node = nodes.get(question.kp_id)
        if node is None or not node.is_active:
            raise ValueError("knowledge_point_not_found")
        _require_assessable_leaf(session, question.kp_id)
        if not question_eligibility(question, node).practice_eligible:
            raise ValueError("question_not_practice_eligible")
        if question_id in existing_ids:
            raise ValueError("question_already_in_plan")
    added = 0
    for question_id in unique_ids:
        question = questions.get(question_id)
        session.add(
            PracticeItem(
                plan_id=plan.id,
                question_id=question.id,
                kp_id=question.kp_id,
                ordinal=next_ordinal,
            )
        )
        existing_ids.add(question_id)
        next_ordinal += 1
        added += 1
    if added > 0 and plan.status == "completed":
        # 卷里又出现了未完成的题，计划自然重新回到进行中。
        plan.status = "active"
    return added


def online_question_for_reference(session: Session, ref: ExamQuestionReference) -> Question | None:
    aliases = {"数学二", "math2"} if ref.subject in {"数学二", "math2"} else {ref.subject}
    source = Question.grading_config["provenance"]["source"]
    matches = list(session.scalars(select(Question).join(KnowledgePoint)
        .where(Question.is_active.is_(True), KnowledgePoint.is_active.is_(True),
            KnowledgePoint.is_assessable.is_(True), source["source_type"].as_string() == "exam",
            source["subject"].as_string().in_(aliases), source["year"].as_integer() == ref.year,
            source["question_number"].as_integer() == ref.question_number)))
    matches = [q for q in matches if question_eligibility(q, session.get(KnowledgePoint, q.kp_id)).practice_eligible]
    return matches[0] if len(matches) == 1 else None


def append_exam_references_to_today(
    session: Session,
    *,
    study_date: date,
    reference_ids: list[UUID],
) -> DailyPlan:
    """Resolve source pointers to actual online questions before creating any plan."""
    if not reference_ids:
        raise ValueError("no_assessable_leaf_selected")
    refs = list(
        session.scalars(
            select(ExamQuestionReference).where(
                ExamQuestionReference.id.in_(list(dict.fromkeys(reference_ids)))
            )
        ).all()
    )
    if len(refs) != len(set(reference_ids)):
        raise ValueError("exam_reference_not_found")
    question_ids = []
    for ref in refs:
        question = online_question_for_reference(session, ref)
        if question is None:
            raise ValueError("question_pool_incomplete")
        question_ids.append(question.id)
    date_key = study_date.isoformat()
    plan = session.scalar(select(DailyPlan).where(DailyPlan.study_date == date_key).with_for_update())
    if plan is None:
        plan = DailyPlan(study_date=date_key, status="active")
        session.add(plan)
        session.flush()
    append_questions_to_plan(session, plan_id=plan.id, question_ids=question_ids)
    return plan
