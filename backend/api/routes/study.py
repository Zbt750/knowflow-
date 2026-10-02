"""今日学习、知识树与自评的 HTTP 层。

设计约束（不要随意改动）：
- 父节点只做汇总：`state` 返回 None，页面数 children 得到结果。
- 练习卷响应里**绝不包含答案与解析**；答案只能走专门的答案接口，且该接口纯读取。
- 服务层抛 ValueError(业务码)，这里统一翻译成 HTTP 错误与统一错误体。
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Request, UploadFile, File, Form
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from backend.api.deps import get_db, get_time_provider
from backend.errors import AppError
from backend.mastery.enums import EvidenceLevel, MasteryState, SelfGrade
from backend.mastery.policy import MasteryPolicy
from backend.mastery.rules import (
    SHANGHAI,
    GapReport,
    analyze_gaps,
    confirmation_dates,
    effective_confirmation_count,
)
from backend.mastery.storage import policy_from_storage, snapshot_from_storage
from backend.models.learning import (
    DailyPlan,
    ExamQuestionReference,
    KnowledgePoint,
    KpMasteryPolicy,
    KpState,
    LearningEvent,
    PracticeItem,
    Question,
    QuestionAttempt,
)
from backend.schemas.knowledge import (
    ExamQuestionReferenceView,
    GapItemView,
    KnowledgeLessonResponse,
    KnowledgeNodeDetail,
    KnowledgeNodeView,
    KnowledgeTreeResponse,
    LessonBreadcrumb,
    NodeAttemptView,
    NodeQuestionView,
    NodeSelfAssessmentRequest,
    NodeSelfAssessmentResponse,
)
from backend.schemas.practice import (
    AppendExamReferencesRequest,
    AppendQuestionsRequest,
    AnswerSubmissionResponse,
    AnswerSubmissionHistory,
    ProcessReviewRequest,
    ProcessReviewResponse,
    SubmitAnswerRequest,
    AssessmentResponse,
    GeneratePlanRequest,
    PlanItemView,
    PracticeItemAnswer,
    RecommendationItem,
    SubmitSelfAssessmentRequest,
    TodayActive,
    TodaySetup,
    TodaySummaryKp,
)
from backend.services.attempt_service import assess_practice_item
from backend.services.answer_submission_service import (submit_answer, record_answer_reveal,
    submission_response, read_answer_history, attempt_sort_key)
from backend.services.process_review_service import latest_text_process_review, review_text_process
from backend.chat.service import provider_from_settings
from backend.services.answer_grading import available_grading_method
from backend.services.capability_service import read_capability_profile
from backend.services.node_assessment_service import assess_knowledge_node
from backend.services.planning_service import GoalCandidate, select_daily_goals
from backend.services.practice_service import (
    append_exam_references_to_today,
    append_questions_to_plan,
    create_initial_plan,
)
from backend.services.lesson_service import read_lesson

router = APIRouter(tags=["study"])

from backend.services.vision_recognition_service import MAX_IMAGE_BYTES, RecognitionResponse, recognize_work


@router.post("/practice-items/{item_id}/recognize-work", response_model=RecognitionResponse)
async def recognize_practice_work(request: Request, item_id: UUID, file: UploadFile = File(...),
                                  consent: bool = Form(False)):
    """Explicit upload consent; transcription is not an assistance/mastery event."""
    try:
        if not consent:
            raise AppError("vision_consent_required")
        with request.app.state.session_factory() as db:
            item = db.get(PracticeItem, item_id)
            if item is None:
                raise AppError("practice_item_not_found")
            if item.question is None or item.question.question_type not in {"calculation", "proof", "subjective"}:
                raise AppError("process_review_not_supported")
        data = await file.read(MAX_IMAGE_BYTES + 1)
        return await recognize_work(request.app.state.settings, data)
    finally:
        await file.close()

# 业务码 → HTTP 状态码。服务层不认识 FastAPI，翻译只发生在这里。
_ERROR_STATUS: dict[str, int] = {
    "knowledge_point_not_found": 404,
    "plan_not_found": 404,
    "practice_item_not_found": 404,
    "plan_already_generated": 409,
    "plan_not_active": 409,
    "node_not_assessable": 409,
    "kp_state_not_found": 409,
    "practice_item_already_assessed": 409,
    "question_pool_incomplete": 409,
    "no_assessable_leaf_selected": 422,
    "question_not_found": 404,
    "exam_reference_not_found": 404,
    "idempotency_key_conflict": 409,
    "external_exam_has_no_embedded_answer": 409,
    "process_review_not_supported": 409,
    "process_review_kind_mismatch": 422,
    "process_review_text_too_short": 422,
    "answer_attempt_conflict": 409,
    "answer_retry_not_allowed": 409,
    "answer_question_changed": 409,
    "answer_attempt_limit": 409,
}


def _http_error(exc: ValueError) -> AppError:
    code = str(exc.args[0]) if exc.args else "invalid_request"
    if code not in _ERROR_STATUS:
        return AppError("invalid_request", detail=str(exc))
    return AppError(code, status_code=_ERROR_STATUS[code], detail=str(exc))


def _today(now: datetime) -> date:
    # 学习日一律按上海日期计算，和状态机的跨天口径保持一致。
    return now.astimezone(SHANGHAI).date()


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


# --------------------------------------------------------------------------- #
# 今日学习
# --------------------------------------------------------------------------- #


def _recommendations(db: Session, now: datetime) -> list[RecommendationItem]:
    """准备页的候选：只推荐可考核叶子，理由来自真实的毕业缺口。"""
    rows = db.execute(
        select(
            KnowledgePoint,
            KpState,
            func.max(QuestionAttempt.submitted_at),
            func.max(PracticeItem.latest_self_grade),
        )
        .join(KpState, KpState.kp_id == KnowledgePoint.id)
        .outerjoin(QuestionAttempt, QuestionAttempt.kp_id == KnowledgePoint.id)
        .outerjoin(PracticeItem, PracticeItem.kp_id == KnowledgePoint.id)
        .where(
            KnowledgePoint.is_assessable.is_(True),
            KnowledgePoint.is_active.is_(True),
            KnowledgePoint.is_reference_only.is_(False),
        )
        .group_by(KnowledgePoint.id, KpState.kp_id)
    ).all()

    # 策略按知识点批量取一次，避免每个候选各查一遍。
    policies = {
        row.kp_id: policy_from_storage(row)
        for row in db.scalars(select(KpMasteryPolicy)).all()
    }

    candidates: list[GoalCandidate] = []
    gaps: dict[str, GapReport] = {}
    names: dict[str, str] = {}
    states: dict[str, str] = {}
    for kp, state, last_practiced_at, last_grade in rows:
        key = str(kp.id)
        names[key] = kp.name
        states[key] = state.state
        snapshot = snapshot_from_storage(state)
        policy = policies.get(kp.id) or MasteryPolicy()
        # 缺口与毕业判定共用同一个实现：推荐理由必须与毕业条件一致。
        gaps[key] = analyze_gaps(
            snapshot.evidence_window,
            manual_credit_count=snapshot.manual_credit_count,
            manual_confirmed_at=snapshot.manual_confirmed_at,
            policy=policy,
        )
        candidates.append(
            GoalCandidate(
                kp_id=key,
                state=MasteryState(state.state),
                next_review_at=state.next_review_at,
                last_practiced_at=last_practiced_at,
                # 最近一次自评：识别「未掌握」与「部分掌握」这两个层级。
                last_self_grade=last_grade,
                has_evidence=bool(
                    snapshot.evidence_window or snapshot.manual_credit_count
                ),
                has_pending_objective_review=bool(snapshot.pending_review_question_ids),
            )
        )

    return [
        RecommendationItem(
            kp_id=UUID(goal.kp_id),
            name=names[goal.kp_id],
            state=states[goal.kp_id],
            reason=goal.reason,
            next_step=goal.next_step,
            missing_types=list(goal.missing_types),
        )
        for goal in select_daily_goals(candidates, now, policies=policies, gaps=gaps)
    ]


def _last_reason_codes(db: Session) -> dict[UUID, str]:
    """每个叶子最近一次事件的 reason_code；未掌握给出更高优先级时会用到。"""
    events = db.scalars(
        select(LearningEvent).order_by(LearningEvent.kp_id, LearningEvent.occurred_at.desc())
    ).all()
    latest: dict[UUID, str] = {}
    for event in events:
        if event.event_type == "ai_process_reviewed":
            continue  # AI 辅助审阅不更新状态，也不能遮住最近一次真实状态原因。
        if event.kp_id in latest:
            continue
        reason = event.payload.get("reason_code") if isinstance(event.payload, dict) else None
        latest[event.kp_id] = str(reason) if reason else event.event_type
    return latest


def _build_today_active(db: Session, plan: DailyPlan) -> TodayActive:
    rows = db.scalars(
        select(PracticeItem).where(PracticeItem.plan_id == plan.id).order_by(PracticeItem.ordinal)
    ).all()
    kp_names = dict(
        db.execute(select(KnowledgePoint.id, KnowledgePoint.name)).all()
    )
    # 之前练过的题目集合：用于标记「复测题」。
    # 一次查完，不在循环里逐题查（否则是 N+1）。
    normal_question_ids = [row.question_id for row in rows if row.question_id is not None]
    attempted_ids = set(
        db.scalars(
            select(QuestionAttempt.question_id).where(
                QuestionAttempt.question_id.in_(normal_question_ids or [])
            )
        ).all()
    )
    reference_ids = [row.exam_reference_id for row in rows if row.exam_reference_id is not None]
    attempted_reference_ids = set(
        db.scalars(
            select(QuestionAttempt.exam_reference_id).where(
                QuestionAttempt.exam_reference_id.in_(reference_ids or [])
            )
        ).all()
    )
    items: list[PlanItemView] = []
    submissions = {
        attempt.practice_item_id: attempt
        for attempt in sorted(db.scalars(select(QuestionAttempt).where(
            QuestionAttempt.practice_item_id.in_([row.id for row in rows]),
            QuestionAttempt.grading_evidence.is_not(None),
        )).all(), key=attempt_sort_key)
    }
    for item in rows:
        question = item.question
        reference = item.exam_reference
        items.append(
            PlanItemView(
                id=item.id,
                ordinal=item.ordinal,
                kp_id=item.kp_id,
                kp_name=kp_names.get(item.kp_id, ""),
                question_id=item.question_id,
                question_type=question.question_type if question is not None else "external_exam",
                question_role=question.question_role if question is not None else None,
                difficulty=question.difficulty if question is not None else None,
                stem=question.stem if question is not None else None,
                options=_options_of(question) if question is not None else None,
                skill_tags=list(question.skill_tags or []) if question is not None else [],
                is_variant=question.is_variant if question is not None else False,
                estimated_minutes=question.estimated_minutes if question is not None else 15,
                completed=item.completed_at is not None,
                completed_at=_iso(item.completed_at),
                latest_self_grade=item.latest_self_grade,
                answer_submission=submission_response(submissions[item.id]) if item.id in submissions else None,
                answer_grading_method=available_grading_method(
                    question_type=question.question_type, config=question.grading_config,
                    expected=question.correct_answer, options=question.options,
                ) if question is not None else None,
                is_review=(
                    item.question_id in attempted_ids
                    if item.question_id is not None
                    else item.exam_reference_id in attempted_reference_ids
                ),
                is_external_reference=reference is not None,
                exam_reference=(
                    ExamQuestionReferenceView(
                        id=reference.id,
                        subject=reference.subject,
                        year=reference.year,
                        question_number=reference.question_number,
                        topic_label=reference.topic_label,
                        source_topic_label=reference.source_topic_label,
                        question_source_url=reference.question_source_url,
                        topic_source_url=reference.topic_source_url,
                        local_folder=reference.local_folder,
                        source_note=reference.source_note,
                    )
                    if reference is not None
                    else None
                ),
            )
        )

    completed = [item for item in items if item.completed]
    focus = next((item.id for item in items if not item.completed), None)
    # 卷子构成与预计时长：页面据此显示「选择题 2 道、填空 2 道…… 预计 45 分钟」。
    type_summary: dict[str, int] = {}
    for item in items:
        type_summary[item.question_type] = type_summary.get(item.question_type, 0) + 1
    total_minutes = sum(item.estimated_minutes for item in items)
    remaining_minutes = sum(item.estimated_minutes for item in items if not item.completed)

    # 今日知识点摘要：只统计今天这张卷实际涉及的叶子与完成数量。
    summary: dict[UUID, TodaySummaryKp] = {}
    for item in items:
        entry = summary.get(item.kp_id)
        if entry is None:
            entry = TodaySummaryKp(
                kp_id=item.kp_id, name=item.kp_name, completed_count=0, total_count=0
            )
            summary[item.kp_id] = entry
        entry.total_count += 1
        if item.completed:
            entry.completed_count += 1

    # 直接返回数据库里的真实状态，不再由题目完成情况重新推导：
    # 否则数据库写着 completed、接口却可能说 active，追加接口与页面会得出不同结论。
    # 状态在真正发生变化的两个事务里维护：全部做完时改 completed、追加新题时改回 active。
    return TodayActive(
        status=plan.status,
        plan_id=plan.id,
        study_date=plan.study_date,
        completed_count=len(completed),
        total_count=len(items),
        items=items,
        focus_item_id=focus,
        summary_kps=list(summary.values()),
        type_summary=type_summary,
        estimated_minutes=total_minutes,
        remaining_minutes=remaining_minutes,
    )


def _options_of(question: Question) -> dict[str, str] | None:
    options = question.options
    if not isinstance(options, dict):
        return None
    return {str(key): str(value) for key, value in options.items()}


@router.get("/plans/today", response_model=TodaySetup | TodayActive)
def read_today_plan(
    db: Session = Depends(get_db),
    time_provider: Callable[[], datetime] = Depends(get_time_provider),
):
    """没有今天的计划就返回 setup；页面据此渲染准备页，而不是直接塞题。"""
    now = time_provider()
    study_date = _today(now).isoformat()
    plan = db.scalar(select(DailyPlan).where(DailyPlan.study_date == study_date))
    if plan is None:
        return TodaySetup(study_date=study_date, recommendations=_recommendations(db, now))
    return _build_today_active(db, plan)


@router.post("/plans/today/generate", status_code=201, response_model=TodayActive)
def generate_today_plan(
    body: GeneratePlanRequest,
    db: Session = Depends(get_db),
    time_provider: Callable[[], datetime] = Depends(get_time_provider),
) -> TodayActive:
    """生成动作只允许成功一次；“今天学什么”由用户在准备页确认后交给服务冻结。"""
    now = time_provider()
    try:
        create_initial_plan(
            db,
            study_date=_today(now),
            selected_kp_ids=list(body.selected_kp_ids),
            now=now,
            budget=body.budget,
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise _http_error(exc) from exc
    plan = db.scalar(select(DailyPlan).where(DailyPlan.study_date == _today(now).isoformat()))
    if plan is None:  # pragma: no cover - 生成成功后必然存在
        raise AppError("plan_not_found")
    return _build_today_active(db, plan)


@router.get("/plans/{plan_id}/items", response_model=TodayActive)
def read_plan_items(plan_id: UUID, db: Session = Depends(get_db)) -> TodayActive:
    plan = db.get(DailyPlan, plan_id)
    if plan is None:
        raise AppError("plan_not_found")
    return _build_today_active(db, plan)


@router.post("/plans/{plan_id}/questions", response_model=TodayActive)
def append_plan_questions(
    plan_id: UUID, body: AppendQuestionsRequest, db: Session = Depends(get_db)
) -> TodayActive:
    """追加只从已有题库取题，永远是卷尾；不重洗、不生成、不显示来源。"""
    try:
        append_questions_to_plan(db, plan_id=plan_id, question_ids=list(body.question_ids))
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise _http_error(exc) from exc
    plan = db.get(DailyPlan, plan_id)
    if plan is None:  # pragma: no cover - 追加成功后必然存在
        raise AppError("plan_not_found")
    return _build_today_active(db, plan)


@router.post("/plans/today/exam-references", response_model=TodayActive)
def append_today_exam_references(
    body: AppendExamReferencesRequest,
    db: Session = Depends(get_db),
    time_provider: Callable[[], datetime] = Depends(get_time_provider),
) -> TodayActive:
    """把知识树选中的原卷题号加入今天，并允许自评计入该节点毕业进度。"""
    try:
        plan = append_exam_references_to_today(
            db,
            study_date=_today(time_provider()),
            reference_ids=list(body.reference_ids),
        )
        plan_id = plan.id
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise _http_error(exc) from exc
    plan = db.get(DailyPlan, plan_id)
    if plan is None:  # pragma: no cover - 服务刚才已创建或读到这张卷
        raise AppError("plan_not_found")
    return _build_today_active(db, plan)


# --------------------------------------------------------------------------- #
# 答案（纯读取）
# --------------------------------------------------------------------------- #


@router.get("/practice-items/{item_id}/answer", response_model=PracticeItemAnswer)
def read_practice_item_answer(
    item_id: UUID, db: Session = Depends(get_db)
) -> PracticeItemAnswer:
    """返回答案与解析。

    这里**只读**：不写 revealed_at、不改掌握度、不影响毕业与复习计划、
    也不影响用户自评。做题前、中、后都可以调用。
    """
    item = db.get(PracticeItem, item_id)
    if item is None:
        raise AppError("practice_item_not_found")
    question = item.question
    if question is None:
        raise AppError("external_exam_has_no_embedded_answer")
    return PracticeItemAnswer(
        practice_item_id=item.id,
        question_id=question.id,
        stem=question.stem,
        options=_options_of(question),
        correct_answer=question.correct_answer,
        explanation=question.explanation,
        question_type=question.question_type,
        grading_mode=question.grading_mode,
    )


# --------------------------------------------------------------------------- #
# 自评
# --------------------------------------------------------------------------- #


@router.post("/practice-items/{item_id}/answer-submissions", response_model=AnswerSubmissionResponse)
def submit_practice_answer(
    item_id: UUID, body: SubmitAnswerRequest, db: Session = Depends(get_db),
    time_provider: Callable[[], datetime] = Depends(get_time_provider),
) -> AnswerSubmissionResponse:
    try:
        result = submit_answer(db, item_id=item_id, raw_answer=body.raw_answer,
                               selected_option=body.selected_option,
                               idempotency_key=body.idempotency_key, now=time_provider(), confidence=body.confidence,
                               expected_previous_attempt_id=body.expected_previous_attempt_id)
        db.commit()
        return result
    except ValueError as exc:
        db.rollback()
        raise _http_error(exc) from exc
    except IntegrityError as exc:
        db.rollback()
        raise AppError("idempotency_key_conflict", status_code=409) from exc


@router.get("/practice-items/{item_id}/answer-submissions", response_model=AnswerSubmissionHistory)
def read_practice_answer_history(item_id: UUID, db: Session = Depends(get_db)) -> AnswerSubmissionHistory:
    """Read immutable observed submissions; never grades/replays or updates state."""
    try:
        return read_answer_history(db, item_id=item_id)
    except ValueError as exc:
        raise _http_error(exc) from exc


@router.post("/practice-items/{item_id}/process-reviews", response_model=ProcessReviewResponse)
def review_practice_process(
    request: Request, item_id: UUID, body: ProcessReviewRequest,
    time_provider: Callable[[], datetime] = Depends(get_time_provider),
) -> ProcessReviewResponse:
    """按需审阅文字过程；不判分、不完成题目、不改变掌握度。"""
    try:
        return review_text_process(
            request.app.state.session_factory, item_id=item_id,
            work_text=body.work_text, subjective_kind=body.subjective_kind,
            idempotency_key=body.idempotency_key, now=time_provider(),
            provider=provider_from_settings(request.app.state.settings),
        )
    except ValueError as exc:
        raise _http_error(exc) from exc
    except IntegrityError as exc:
        raise AppError("idempotency_key_conflict", status_code=409) from exc


@router.get("/practice-items/{item_id}/process-reviews/latest", response_model=ProcessReviewResponse | None)
def read_latest_process_review(request: Request, item_id: UUID) -> ProcessReviewResponse | None:
    try:
        return latest_text_process_review(request.app.state.session_factory, item_id=item_id)
    except ValueError as exc:
        raise _http_error(exc) from exc


@router.post("/practice-items/{item_id}/answer-reveal", response_model=PracticeItemAnswer)
def reveal_practice_answer(
    item_id: UUID, db: Session = Depends(get_db),
    time_provider: Callable[[], datetime] = Depends(get_time_provider),
) -> PracticeItemAnswer:
    try:
        record_answer_reveal(db, item_id=item_id, now=time_provider())
        result = read_practice_item_answer(item_id, db)
        db.commit()
        return result
    except ValueError as exc:
        db.rollback()
        raise _http_error(exc) from exc


@router.post("/practice-items/{item_id}/self-assessments", response_model=AssessmentResponse)
def submit_self_assessment(
    item_id: UUID,
    body: SubmitSelfAssessmentRequest,
    db: Session = Depends(get_db),
    time_provider: Callable[[], datetime] = Depends(get_time_provider),
) -> AssessmentResponse:
    """一次自评的完整事务：attempt + 状态投影 + 审计事件一起提交。"""
    try:
        result = assess_practice_item(
            db,
            item_id=item_id,
            raw_answer=body.raw_answer,
            self_grade=_self_grade(body.self_grade),
            idempotency_key=body.idempotency_key,
            now=time_provider(),
            selected_option=body.selected_option,
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise _http_error(exc) from exc

    item = db.get(PracticeItem, item_id)
    if item is None:  # pragma: no cover
        raise AppError("practice_item_not_found")
    state = db.get(KpState, item.kp_id)
    manual_credit = state.manual_credit_count if state else 0
    return AssessmentResponse(
        practice_item_id=item_id,
        kp_id=item.kp_id,
        state=result.state.value,
        reason_code=result.reason_code,
        effective_confirmation_count=result.effective_count,
        manual_credit_count=manual_credit,
        next_review_at=_iso(result.next_review_at),
    )


def _self_grade(value: str) -> SelfGrade:
    """把已验证的请求字符串转成领域枚举；非法值由 Pydantic 提前拦下。"""
    return SelfGrade(value)


# --------------------------------------------------------------------------- #
# 知识树
# --------------------------------------------------------------------------- #


@router.get("/knowledge/tree", response_model=KnowledgeTreeResponse)
def read_knowledge_tree(db: Session = Depends(get_db)) -> KnowledgeTreeResponse:
    nodes = db.scalars(
        select(KnowledgePoint)
        .where(KnowledgePoint.is_active.is_(True))
        .order_by(KnowledgePoint.ordinal, KnowledgePoint.code)
    ).all()
    states = {
        state.kp_id: state
        for state in db.scalars(select(KpState)).all()
    }
    # 策略按知识点存储：缺口与门槛都取该叶子自己那一行，没有配置则用默认策略。
    policies = {
        row.kp_id: policy_from_storage(row)
        for row in db.scalars(select(KpMasteryPolicy)).all()
    }
    views = {
        node.id: _node_view(node, states.get(node.id), policies.get(node.id))
        for node in nodes
    }
    roots: list[KnowledgeNodeView] = []
    for node in nodes:
        view = views[node.id]
        if node.parent_id is None:
            roots.append(view)
        else:
            parent = views.get(node.parent_id)
            if parent is not None:
                parent.children.append(view)
    return KnowledgeTreeResponse(nodes=roots)


@router.get("/knowledge/lessons/{code}", response_model=KnowledgeLessonResponse)
def read_knowledge_lesson(code: str, db: Session = Depends(get_db)) -> KnowledgeLessonResponse:
    node = db.scalar(
        select(KnowledgePoint).where(
            KnowledgePoint.code == code,
            KnowledgePoint.is_active.is_(True),
        )
    )
    if node is None:
        raise AppError("knowledge_point_not_found")
    markdown = read_lesson(node.code)
    if markdown is None:
        raise AppError("knowledge_lesson_not_found")

    path: list[LessonBreadcrumb] = []
    current: KnowledgePoint | None = node
    seen: set[UUID] = set()
    while current is not None and current.id not in seen:
        seen.add(current.id)
        path.append(LessonBreadcrumb(code=current.code, name=current.name))
        current = db.get(KnowledgePoint, current.parent_id) if current.parent_id else None
    path.reverse()
    question_count = (
        db.scalar(
            select(func.count(Question.id)).where(
                Question.kp_id == node.id,
                Question.is_active.is_(True),
            )
        ) or 0
    ) if node.is_assessable else 0
    return KnowledgeLessonResponse(
        id=node.id,
        code=node.code,
        name=node.name,
        subject=node.subject,
        is_assessable=node.is_assessable,
        breadcrumbs=path,
        markdown=markdown,
        question_count=question_count,
    )


@router.get("/knowledge/{kp_id}", response_model=KnowledgeNodeDetail)
def read_knowledge_node(kp_id: UUID, db: Session = Depends(get_db)) -> KnowledgeNodeDetail:
    node = db.get(KnowledgePoint, kp_id)
    if node is None:
        raise AppError("knowledge_point_not_found")
    state = db.get(KpState, kp_id)
    policy = policy_from_storage(db.get(KpMasteryPolicy, kp_id))
    view = _node_view(node, state, policy)

    questions = db.scalars(
        select(Question)
        .where(Question.kp_id == kp_id, Question.is_active.is_(True))
        # Question 没有 ordinal 列；按创建顺序稳定排序，保证页面与测试可预期。
        .order_by(Question.created_at, Question.id)
    ).all()
    q_views = [
        NodeQuestionView(
            id=question.id,
            question_type=question.question_type,
            difficulty=question.difficulty,
            is_variant=question.is_variant,
            stem=question.stem,
            kp_id=question.kp_id,
        )
        for question in questions
    ]

    attempts = db.execute(
        select(
            QuestionAttempt,
            Question.stem,
            ExamQuestionReference.id,
            ExamQuestionReference.subject,
            ExamQuestionReference.year,
            ExamQuestionReference.question_number,
            ExamQuestionReference.topic_label,
        )
        .outerjoin(Question, Question.id == QuestionAttempt.question_id)
        .outerjoin(
            ExamQuestionReference,
            ExamQuestionReference.id == QuestionAttempt.exam_reference_id,
        )
        .where(QuestionAttempt.kp_id == kp_id)
        .order_by(QuestionAttempt.submitted_at.desc())
        .limit(50)
    ).all()
    a_views = [
        NodeAttemptView(
            id=attempt.id,
            question_id=attempt.question_id,
            exam_reference_id=reference_id,
            question_stem=(
                stem
                if stem is not None
                else f"{year} 年 {subject} 第 {question_number} 题 · {topic_label}"
            ),
            self_grade=attempt.self_grade,
            objective_result=attempt.objective_result,
            result_state=attempt.result_state,
            reason_code=attempt.reason_code,
            submitted_at=attempt.submitted_at.isoformat(),
            raw_answer=attempt.raw_answer,
            grading_evidence=attempt.grading_evidence,
        )
        for attempt, stem, reference_id, subject, year, question_number, topic_label in attempts
    ]

    exam_references = db.scalars(
        select(ExamQuestionReference)
        .where(ExamQuestionReference.knowledge_point_id == kp_id)
        .order_by(ExamQuestionReference.year.desc(), ExamQuestionReference.question_number)
    ).all()
    exam_reference_views = [
        ExamQuestionReferenceView(
            id=row.id,
            subject=row.subject,
            year=row.year,
            question_number=row.question_number,
            topic_label=row.topic_label,
            source_topic_label=row.source_topic_label,
            question_source_url=row.question_source_url,
            topic_source_url=row.topic_source_url,
            local_folder=row.local_folder,
            source_note=row.source_note,
        )
        for row in exam_references
    ]

    return KnowledgeNodeDetail(
        node=view,
        questions=q_views,
        attempts=a_views,
        exam_references=exam_reference_views,
        lesson_available=read_lesson(node.code) is not None,
        materials_ready=False,
        capability_profile=read_capability_profile(db, node, questions=questions),
    )


@router.post(
    "/knowledge/{kp_id}/self-assessment", response_model=NodeSelfAssessmentResponse
)
def submit_node_self_assessment(
    kp_id: UUID,
    body: NodeSelfAssessmentRequest,
    db: Session = Depends(get_db),
    time_provider: Callable[[], datetime] = Depends(get_time_provider),
) -> NodeSelfAssessmentResponse:
    """叶子整体自评：mastered 只写 2 个透明基础确认，绝不伪造两条作答。"""
    try:
        result = assess_knowledge_node(
            db,
            kp_id=kp_id,
            self_grade=_self_grade(body.self_grade),
            idempotency_key=body.idempotency_key,
            now=time_provider(),
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise _http_error(exc) from exc

    state = db.get(KpState, kp_id)
    if state is None:  # pragma: no cover
        raise AppError("kp_state_not_found")
    return NodeSelfAssessmentResponse(
        kp_id=kp_id,
        state=result.state.value,
        reason_code=result.reason_code,
        effective_confirmation_count=result.effective_count,
        manual_credit_count=state.manual_credit_count,
        next_review_at=_iso(result.next_review_at),
    )


def _node_view(
    node: KnowledgePoint, state: KpState | None, policy: MasteryPolicy | None = None
) -> KnowledgeNodeView:
    if state is None or not node.is_assessable:
        # 父节点没有状态投影：汇总由页面数 children 得到，不存第二份统计真相。
        return KnowledgeNodeView(
            id=node.id,
            code=node.code,
            name=node.name,
            subject=node.subject,
            ordinal=node.ordinal,
            is_assessable=node.is_assessable,
            is_reference_only=node.is_reference_only,
            summary=node.summary if node.is_assessable else None,
            learning_goal=node.learning_goal if node.is_assessable else None,
        )

    active_policy = policy or MasteryPolicy()
    snapshot = snapshot_from_storage(state)
    # 与状态机共用同一个日期函数：页面看到的跨度必须等于毕业判定使用的跨度。
    dates = confirmation_dates(
        snapshot.evidence_window,
        manual_credit_count=snapshot.manual_credit_count,
        manual_confirmed_at=snapshot.manual_confirmed_at,
    )
    # 缺口报告同样与状态机共用：页面显示的每一项进度就是毕业判定的那一项。
    report = analyze_gaps(
        snapshot.evidence_window,
        manual_credit_count=snapshot.manual_credit_count,
        manual_confirmed_at=snapshot.manual_confirmed_at,
        policy=active_policy,
    )
    return KnowledgeNodeView(
        id=node.id,
        code=node.code,
        name=node.name,
        subject=node.subject,
        ordinal=node.ordinal,
        is_assessable=True,
        is_reference_only=node.is_reference_only,
        summary=node.summary,
        learning_goal=node.learning_goal,
        state=snapshot.state.value,
        assessment_basis=snapshot.assessment_basis,
        pending_review_count=len(snapshot.pending_review_question_ids),
        next_review_at=_iso(snapshot.next_review_at),
        mastered_at=_iso(snapshot.mastered_at),
        node_self_grade=snapshot.node_self_grade.value if snapshot.node_self_grade else None,
        manual_credit_count=snapshot.manual_credit_count,
        effective_confirmation_count=effective_confirmation_count(
            snapshot.evidence_window, manual_credit_count=snapshot.manual_credit_count
        ),
        has_real_variant=any(
            item.is_variant and item.level is EvidenceLevel.CONFIRMED
            for item in snapshot.evidence_window
        ),
        first_confirmed_on=dates[0].isoformat() if dates else None,
        last_confirmed_on=dates[-1].isoformat() if dates else None,
        day_span=(dates[-1] - dates[0]).days if dates else None,
        gap_items=([
            GapItemView(
                key=item.key,
                label=item.label,
                current=item.current,
                required=item.required,
                satisfied=item.satisfied,
            )
            for item in report.items
        ] + ([GapItemView(key="objective_review", label="最近错题复测", current=0,
                          required=len(snapshot.pending_review_question_ids), satisfied=False)]
              if snapshot.pending_review_question_ids else [])),
        next_step=f"复测 {len(snapshot.pending_review_question_ids)} 道最近答错的题" if snapshot.pending_review_question_ids else report.next_step,
        required_question_types=dict(active_policy.required_question_types),
        excluded_question_types=sorted(active_policy.excluded_question_types),
        required_skill_tags=sorted(active_policy.required_skill_tags),
    )


# 时区常量在此导出，便于测试断言学习日口径。
__all__ = ["router", "SHANGHAI", "timezone"]
