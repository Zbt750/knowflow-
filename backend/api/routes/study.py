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

from fastapi import APIRouter, Depends, Request, Response, UploadFile, File, Form, Query
from sqlalchemy import func, select, tuple_
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.exc import IntegrityError

from backend.api.deps import get_db, get_time_provider
from backend.errors import AppError
from backend.schemas.question_source import public_question_source
from backend.schemas.question_trust import QuestionTrustView, QuestionAvailabilityView
from backend.mastery.enums import EvidenceLevel, MasteryState, SelfGrade
from backend.mastery.policy import MasteryPolicy
from backend.mastery.rules import (
    SHANGHAI,
    GapReport,
    analyze_gaps,
    confirmation_dates,
    effective_confirmation_count,
)
from backend.mastery.storage import policy_for_node, snapshot_from_storage
from backend.services.policy_evidence_service import current_policy_snapshot
from backend.models.learning import (
    DailyPlan,
    ExamQuestionReference,
    KnowledgePoint,
    KpMasteryPolicy,
    KpState,
    LearningEvent,
    PracticeItem,
    Question,
    QuestionAutoReviewEvent,
    QuestionAnswerVerificationEvent,
    QuestionAttempt,
    QuestionVersion,
)
from backend.services.question_versions import question_for_practice_item
from backend.services.knowledge_tree_cache import (
    cache_generation,
    cache_knowledge_tree,
    get_cached_knowledge_tree,
    get_cached_knowledge_tree_http,
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
from backend.services.question_eligibility import question_eligibility
from backend.services.question_availability import question_availability
from backend.services.personal_question_service import node_activity
from backend.services.evidence_pool import assess_evidence_pool
from backend.services.capability_service import read_capability_profile
from backend.services.node_assessment_service import assess_knowledge_node
from backend.services.planning_service import GoalCandidate, select_daily_goals
from backend.services.practice_service import (
    append_exam_references_to_today,
    append_questions_to_plan,
    create_initial_plan,
)
from backend.services.lesson_service import read_lesson
from backend.services.study_read_context import policies_for_nodes, question_read_options

router = APIRouter(tags=["study"])

from backend.schemas.practice import PracticeActivityRequest


@router.post('/practice-items/{item_id}/activity')
def record_practice_activity(item_id: UUID, body: PracticeActivityRequest,
    db: Session=Depends(get_db), time_provider=Depends(get_time_provider)):
    from backend.services.practice_activity_service import record_activity
    try:
        event=record_activity(db,item_id=item_id,kind=body.kind,
            idempotency_key=body.idempotency_key,now=time_provider())
        db.commit()
        return {'event_id':str(event.id),'kind':event.payload['kind'],'occurred_at':event.occurred_at.isoformat()}
    except ValueError as exc:
        db.rollback()
        raise _http_error(exc) from exc


@router.get('/practice-items/{item_id}/activity')
def read_practice_activity(item_id: UUID, db: Session=Depends(get_db)):
    if db.get(PracticeItem,item_id) is None:
        raise AppError('practice_item_not_found')
    rows=db.scalars(select(LearningEvent).where(LearningEvent.source_id==item_id,
        LearningEvent.event_type=='scheduler_activity').order_by(LearningEvent.occurred_at,LearningEvent.id)).all()
    return {'events':[{'event_id':str(r.id),'kind':r.payload['kind'],
        'occurred_at':r.occurred_at.isoformat()} for r in rows]}


def _question_trust_view(question: Question, node: KnowledgePoint | None = None) -> QuestionTrustView:
    return QuestionTrustView(**question_eligibility(question, node).public_dict())


@router.get("/question-availability", response_model=QuestionAvailabilityView)
def read_question_availability(
    subject: str | None = None,
    kp_ids: list[UUID] = Query(default=[]),
    exclude_kp_ids: list[UUID] = Query(default=[]),
    exclude_question_ids: list[UUID] = Query(default=[]),
    question_type: str | None = None,
    plan_id: UUID | None = None,
    limit: int = Query(default=100, ge=1, le=200),
    db: Session = Depends(get_db),
    time_provider: Callable[[], datetime] = Depends(get_time_provider),
) -> QuestionAvailabilityView:
    return QuestionAvailabilityView(**question_availability(db, now=time_provider(), subject=subject,
        kp_ids=kp_ids or None, exclude_kp_ids=exclude_kp_ids or None,
        exclude_question_ids=exclude_question_ids or None,
        question_type=question_type, plan_id=plan_id, limit=limit))

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
            question = question_for_practice_item(db, item)
            if question is None or question.question_type not in {"calculation", "proof", "subjective"}:
                raise AppError("process_review_not_supported")
        data = await file.read(MAX_IMAGE_BYTES + 1)
        return await recognize_work(request.app.state.settings, data)
    finally:
        await file.close()


@router.post("/qa/image-transcribe", response_model=RecognitionResponse)
async def transcribe_question_image(request: Request, file: UploadFile = File(...),
                                    consent: bool = Form(False)):
    """普通问答页的通用图片题转写：不绑定练习项、不写盘、不写掌握度。

    只做临时转写；识别文本必须由用户核对确认后才会作为问题发送。
    """
    try:
        if not consent:
            raise AppError("vision_consent_required")
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
    "question_not_practice_eligible": 409,
    "question_not_formally_admitted": 422,
    "question_already_in_plan": 409,
    "duplicate_question": 422,
    "exam_reference_not_found": 404,
    "idempotency_key_conflict": 409,
    "external_exam_has_no_embedded_answer": 409,
    "process_review_not_supported": 409,
    "practice_retry_not_available": 409,
    "process_review_kind_mismatch": 422,
    "process_review_text_too_short": 422,
    "answer_attempt_conflict": 409,
    "answer_grading_unsupported": 422,
    "answer_retry_not_allowed": 409,
    "answer_question_changed": 409,
    "answer_attempt_limit": 409,
    "selected_option_required": 422,
    "selected_option_invalid": 422,
    "graduation_set_transition_confirmation_required": 409,
    "graduation_set_transition_requires_mutating_confirmation": 409,
    "graduation_set_transition_state_missing": 409,
    "graduation_set_transition_legacy_mastery_requires_review": 409,
    "graduation_set_transition_confirmation_scope_invalid": 422,
    "graduation_set_binding_missing_for_started_learner": 409,
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


def _recommendations(db: Session, now: datetime, *, subject: str | None = None,
                     limit: int = 6) -> list[RecommendationItem]:
    """准备页的候选：只推荐可考核叶子，理由来自真实的毕业缺口。"""
    eligible_kp_ids = set()
    # A warm process already has immutable, version-bound public eligibility
    # decisions. Read only their key columns on those requests; cold starts and
    # cache misses still load the full question and run the original validator.
    from sqlalchemy.orm import joinedload, load_only, undefer
    from backend.services.question_eligibility import (
        cached_question_eligibility, public_eligibility_cache_ready,
    )
    warm_eligibility_cache = public_eligibility_cache_ready(db.get_bind())
    eligibility_columns = (
        Question.id, Question.current_version_id, Question.updated_at, Question.kp_id,
        Question.question_type, Question.question_provenance, Question.content_trust,
        Question.source_status, Question.answer_provenance, Question.answer_reliability,
        Question.content_reviewed_by, Question.content_reviewed_at,
        Question.answer_reviewed_by, Question.answer_reviewed_at,
        Question.source_attestation_key, Question.source_attestation_sha256,
        Question.answer_attestation_key, Question.answer_attestation_sha256,
        Question.answer_verification_event_id, Question.auto_review_event_id,
        Question.is_active, Question.is_hidden, Question.bank_scope,
        Question.generation_batch_id,
    )
    query_options = [
        joinedload(Question.current_auto_review).load_only(
            QuestionAutoReviewEvent.id, QuestionAutoReviewEvent.question_id,
            QuestionAutoReviewEvent.event_type, QuestionAutoReviewEvent.review_version,
            QuestionAutoReviewEvent.qualification_class,
            QuestionAutoReviewEvent.question_snapshot_sha256,
            QuestionAutoReviewEvent.answer_sha256, QuestionAutoReviewEvent.audit_sha256,
        ).defer(QuestionAutoReviewEvent.audit_snapshot),
        selectinload(KnowledgePoint.children),
    ]
    if warm_eligibility_cache:
        query_options.insert(0, load_only(*eligibility_columns))
        query_options.append(joinedload(Question.current_answer_verification).load_only(
            QuestionAnswerVerificationEvent.id, QuestionAnswerVerificationEvent.question_id,
            QuestionAnswerVerificationEvent.event_type,
            QuestionAnswerVerificationEvent.verification_type,
            QuestionAnswerVerificationEvent.answer_sha256,
            QuestionAnswerVerificationEvent.verifier,
            QuestionAnswerVerificationEvent.created_at,
        ))
    else:
        # The full validator reads reference metadata and hashes on a cold
        # decision. Keep that receipt eager so cold inventory evaluation cannot
        # regress into per-question deferred JSON queries.
        query_options.append(joinedload(Question.current_answer_verification))
    eligible_rows = db.execute(select(Question, KnowledgePoint).options(*query_options).join(
        KnowledgePoint, KnowledgePoint.id == Question.kp_id).where(
            Question.is_active.is_(True), KnowledgePoint.is_active.is_(True),
            KnowledgePoint.is_assessable.is_(True))).all()
    if subject == '408':
        eligible_rows=[(question,node) for question,node in eligible_rows
            if node.subject in {'408','cs408','计算机学科专业基础'} or node.code.startswith('cs408')]
    elif subject:
        eligible_rows=[(question,node) for question,node in eligible_rows if node.subject==subject]
    # R25：请求级映射（已用真实库验证与原版 eligibility 判定完全等价：
    # 1931 行、eligible_plain=eligible_map=1822）。复用已预载关系，零额外查询。
    review_events = {str(q.auto_review_event_id): q.current_auto_review
                     for q, _ in eligible_rows
                     if q.auto_review_event_id and q.current_auto_review is not None}
    cached_eligibility = {}
    full_load_rows = []
    if warm_eligibility_cache:
        for question, node in eligible_rows:
            decision = cached_question_eligibility(
                question, node, auto_review_events=review_events)
            if decision is None:
                full_load_rows.append((question, node))
            else:
                cached_eligibility[question.id] = decision
        if full_load_rows:
            from sqlalchemy.orm import undefer
            missed_ids = {question.id for question, _ in full_load_rows}
            db.execute(select(Question).where(Question.id.in_(missed_ids)).options(
                undefer("*"),
                joinedload(Question.current_auto_review).undefer("*").defer(
                    QuestionAutoReviewEvent.audit_snapshot),
                joinedload(Question.current_answer_verification).undefer("*"),
            ).execution_options(populate_existing=True)).scalars().all()
            review_events = {str(question.auto_review_event_id): question.current_auto_review
                for question, _ in full_load_rows
                if question.auto_review_event_id and question.current_auto_review is not None}
            from backend.services.auto_question_review import preload_uncached_auto_review_snapshots
            preload_uncached_auto_review_snapshots(db, full_load_rows, review_events)
    else:
        from backend.services.auto_question_review import preload_uncached_auto_review_snapshots
        preload_uncached_auto_review_snapshots(db, eligible_rows, review_events)
    eligible_versions = {}
    for question, node in eligible_rows:
        decision = cached_eligibility.get(question.id)
        if decision is None:
            decision = question_eligibility(question, node, auto_review_events=review_events)
        if decision.practice_eligible:
            eligible_kp_ids.add(node.id)
            if question.current_version_id:
                eligible_versions[(str(question.id), str(question.current_version_id))] = str(node.id)
    rows = db.execute(
        select(
            KnowledgePoint,
            KpState,
            func.max(QuestionAttempt.submitted_at),
            func.max(PracticeItem.latest_self_grade),
        )
        .outerjoin(KpState, KpState.kp_id == KnowledgePoint.id)
        .outerjoin(QuestionAttempt, QuestionAttempt.kp_id == KnowledgePoint.id)
        .outerjoin(PracticeItem, PracticeItem.kp_id == KnowledgePoint.id)
        .where(
            KnowledgePoint.is_assessable.is_(True),
            KnowledgePoint.is_active.is_(True),
            KnowledgePoint.id.in_(eligible_kp_ids or {UUID(int=0)}),
        )
        .options(selectinload(KnowledgePoint.children))
        .group_by(KnowledgePoint.id, KpState.kp_id)
    ).all()

    # 策略按知识点批量取一次，避免每个候选各查一遍。
    policies, read_context = policies_for_nodes(db, [kp.id for kp, _, _, _ in rows])

    candidates: list[GoalCandidate] = []
    from backend.services.adaptive_schedule_projection import read_projection
    adaptive = read_projection(db, now, [kp.id for kp, _, _, _ in rows])
    due_nodes = set()
    for key, card in adaptive.cards.items():
        if card.due <= now and key in eligible_versions:
            due_nodes.add(eligible_versions[key])
    gaps: dict[str, GapReport] = {}
    names: dict[str, str] = {}
    states: dict[str, str] = {}
    for kp, state, last_practiced_at, last_grade in rows:
        key = str(kp.id)
        names[key] = kp.name
        states[key] = state.state if state else MasteryState.UNSEEN.value
        policy = policies.get(kp.id) or MasteryPolicy()
        # Reading recommendations must not bootstrap or bind learner state.
        from backend.mastery.types import MasterySnapshot
        snapshot = (current_policy_snapshot(db, state, policy, _read_context=read_context) if state else
            MasterySnapshot(MasteryState.UNSEEN, (), 0, None, None, None, 0, None))
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
                state=snapshot.state,
                next_review_at=snapshot.next_review_at,
                last_practiced_at=last_practiced_at,
                # 最近一次自评：识别「未掌握」与「部分掌握」这两个层级。
                last_self_grade=last_grade,
                has_evidence=bool(
                    snapshot.evidence_window or snapshot.manual_credit_count
                ),
                has_pending_objective_review=bool(snapshot.pending_review_question_ids),
                adaptive_due=key in due_nodes,
                adaptive_cooldown=bool(adaptive.skills.get(key) and adaptive.skills[key].last_at
                    and (now-adaptive.skills[key].last_at).total_seconds() < 172800),
                adaptive_mastery=(adaptive.skills[key].probability if key in adaptive.skills
                    and adaptive.skills[key].right + adaptive.skills[key].wrong else None),
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
            requires_graduation_set_confirmation=bool(
                policies.get(UUID(goal.kp_id)) and policies[UUID(goal.kp_id)].graduation_binding_pending
            ),
        )
        for goal in select_daily_goals(candidates, now, policies=policies, gaps=gaps, limit=limit)
    ]


def _last_reason_codes(db: Session) -> dict[UUID, str]:
    """每个叶子最近一次事件的 reason_code；未掌握给出更高优先级时会用到。"""
    events = db.scalars(
        select(LearningEvent).order_by(LearningEvent.kp_id, LearningEvent.occurred_at.desc())
    ).all()
    latest: dict[UUID, str] = {}
    for event in events:
        if event.event_type in {"ai_process_reviewed", "scheduler_activity"}:
            continue  # AI 辅助审阅不更新状态，也不能遮住最近一次真实状态原因。
        if event.kp_id in latest:
            continue
        reason = event.payload.get("reason_code") if isinstance(event.payload, dict) else None
        latest[event.kp_id] = str(reason) if reason else event.event_type
    return latest


def _build_today_active(db: Session, plan: DailyPlan, *, selected_rows=None) -> TodayActive:
    rows = selected_rows if selected_rows is not None else db.scalars(
        select(PracticeItem).where(PracticeItem.plan_id == plan.id).order_by(PracticeItem.ordinal)
    ).all()
    rows = [row for row in rows if row.removed_at is None]
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
        question = question_for_practice_item(db, item)
        reference = item.exam_reference
        items.append(
            PlanItemView(
                id=item.id,
                retry_source_id=item.retry_source_id,
                answer_revealed_at=_iso(item.answer_revealed_at),
                ordinal=item.ordinal,
                kp_id=item.kp_id,
                kp_name=kp_names.get(item.kp_id, ""),
                question_id=item.question_id,
                question_version_id=item.question_version_id,
                question_type=question.question_type if question is not None else "external_exam",
                question_role=question.question_role if question is not None else None,
                difficulty=question.difficulty if question is not None else None,
                stem=question.stem if question is not None else None,
                question_source=public_question_source(question.grading_config) if question is not None else None,
                question_trust=_question_trust_view(question, db.get(KnowledgePoint, question.kp_id)) if question is not None else None,
                options=_options_of(question) if question is not None else None,
                skill_tags=list(question.skill_tags or []) if question is not None else [],
                is_variant=question.is_variant if question is not None else False,
                estimated_minutes=question.estimated_minutes if question is not None else 15,
                completed=item.completed_at is not None,
                completed_at=_iso(item.completed_at),
                latest_self_grade=item.latest_self_grade,
                answer_submission=submission_response(submissions[item.id]) if item.id in submissions else None,
                answer_grading_method=question_eligibility(question, db.get(KnowledgePoint, question.kp_id)).answer_comparison_method
                    if question is not None else None,
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

    from backend.services.practice_display_order import display_key
    for number,item in enumerate(sorted(items,key=lambda item:display_key(item.question_type,item.ordinal)),1):
        item.display_number=number
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

    retry_wrong_items: list[PlanItemView] = []
    if selected_rows is None and rows:
        root_order = {item.id: index for index, item in enumerate(rows)}
        retry_rows = list(db.scalars(select(PracticeItem).where(
            PracticeItem.retry_source_id.in_(root_order)).order_by(PracticeItem.created_at, PracticeItem.id)))
        retry_rows.sort(key=lambda item: (root_order.get(item.retry_source_id, len(root_order)),
            item.created_at, str(item.id)))
        if retry_rows:
            retry_view = _build_today_active(db, plan, selected_rows=retry_rows)
            retry_wrong_items = [item for item in retry_view.items
                if item.completed and not item.is_external_reference
                and item.answer_submission is not None and item.answer_submission.result == "wrong"]

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
        retry_wrong_items=retry_wrong_items,
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


@router.get("/plans/today/recommendations", response_model=TodaySetup)
def read_today_recommendations(db: Session = Depends(get_db),
    time_provider: Callable[[], datetime] = Depends(get_time_provider)):
    """Read-only selection view, also available when today's paper has items."""
    now = time_provider()
    return TodaySetup(study_date=_today(now).isoformat(), recommendations=_recommendations(db, now))


from backend.schemas.home_recommendation import HomeRecommendationRequest, HomeRecommendationConfirm, HomeDifficultyRequest
from backend.services import home_recommendation_service as home_recommendation
from backend.services import home_difficulty_service as home_difficulty


@router.get("/plans/today/home-recommendation")
def read_home_system_recommendation(response: Response, db: Session = Depends(get_db),
    time_provider: Callable[[], datetime] = Depends(get_time_provider)):
    now = time_provider()
    import time as _time
    from backend.db import reset_sql_profile, sql_profile_snapshot
    reset_sql_profile()
    service_started = _time.perf_counter()
    # public_system deliberately strips learner evidence. Avoid constructing
    # those private per-topic diagnostics only to discard them on this GET.
    # Internal draft planning keeps the default evidence-rich representation.
    from backend.services.study_read_context import shared_policy_read_context
    with shared_policy_read_context(db):
        result = home_recommendation.read_system(db, _recommendations(db, now), now, include_evidence=False)
    service_seconds = _time.perf_counter() - service_started
    snap = sql_profile_snapshot()
    response.headers["X-SQL-Count"] = str(snap["count"])
    response.headers["X-SQL-Seconds"] = "%.4f" % snap["seconds"]
    response.headers["X-Service-Seconds"] = "%.4f" % service_seconds
    response.headers["X-Service-Non-SQL-Seconds"] = "%.4f" % max(0.0,service_seconds-snap["seconds"])
    response.headers["X-SQL-Top"] = " | ".join("%d x %s" % (c, q[:48]) for q, c in snap.get("top", []))
    import json as _json
    response.headers["X-SQL-Stack"] = _json.dumps(snap.get("top_stacks", []), ensure_ascii=True)[:3500]
    from backend.services.home_public_view import public_system
    return public_system(result)


@router.get("/plans/today/home-preview")
def read_home_preview(session_id: UUID, db: Session = Depends(get_db)):
    from backend.services.home_public_view import public_preview
    return public_preview(home_recommendation.recover(db, session_id))


@router.post("/plans/today/home-preview")
def adjust_home_preview(body: HomeRecommendationRequest, request: Request, db: Session = Depends(get_db),
    time_provider: Callable[[], datetime] = Depends(get_time_provider)):
    now=time_provider()
    recommendations=[] if body.action in {'accept_workload','dismiss_workload'} else _recommendations(db,now)
    from backend.chat.service import provider_from_settings
    result = home_recommendation.adjust(db, body, recommendations, now,
        intent_provider_factory=lambda:provider_from_settings(request.app.state.settings))
    db.commit()
    from backend.services.home_public_view import public_preview
    return public_preview(result)


@router.post("/plans/today/home-preview/{task_id}/difficulty")
def adjust_home_difficulty(task_id: UUID, body: HomeDifficultyRequest, db: Session = Depends(get_db),
    time_provider: Callable[[], datetime] = Depends(get_time_provider)):
    """整卷难度调整：只替换真实候选题，题量/知识点/预算保持不变。"""
    result = home_difficulty.adjust_paper_difficulty(
        db, task_id=task_id, session_id=body.session_id, direction=body.direction,
        request_key=body.request_key, now=time_provider(),
    )
    db.commit()
    from backend.services.home_public_view import public_preview
    return public_preview(result)


@router.post("/plans/today/home-preview/{task_id}/confirm")
def confirm_home_preview(task_id: UUID, body: HomeRecommendationConfirm, db: Session = Depends(get_db),
    time_provider: Callable[[], datetime] = Depends(get_time_provider)):
    try:
        result = home_recommendation.confirm(db, task_id, body, time_provider())
        db.commit()
        from backend.services.home_public_view import public_preview
        return public_preview(result)
    except ValueError as exc:
        db.rollback()
        raise _http_error(exc) from exc


@router.post("/plans/today/generate", status_code=201, response_model=TodayActive)
def generate_today_plan(
    body: GeneratePlanRequest,
    db: Session = Depends(get_db),
    time_provider: Callable[[], datetime] = Depends(get_time_provider),
) -> TodayActive:
    """首次组卷或显式扩充；已有卷不会被替换，所选范围仍需用户确认。"""
    now = time_provider()
    try:
        create_initial_plan(
            db,
            study_date=_today(now),
            selected_kp_ids=list(body.selected_kp_ids),
            now=now,
            budget=body.budget,
            confirm_legacy_set_transition_ids=list(body.confirm_legacy_set_transition_ids),
            extend_existing=body.extend_existing,
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
    plan_id: UUID, body: AppendQuestionsRequest, db: Session = Depends(get_db),
    time_provider: Callable[[], datetime] = Depends(get_time_provider),
) -> TodayActive:
    """追加只从已有题库取题，永远是卷尾；不重洗、不生成、不显示来源。"""
    now=time_provider()
    try:
        target = db.get(DailyPlan, plan_id)
        if target is not None and target.study_date != _today(now).isoformat():
            raise AppError("plan_not_today", status_code=409)
        append_questions_to_plan(db, plan_id=plan_id, question_ids=list(body.question_ids),now=now)
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
    """把已对应完整在线题目的原卷引用加入今天；缺题面时拒绝追加。"""
    now=time_provider()
    try:
        plan = append_exam_references_to_today(
            db,
            study_date=_today(now),
            reference_ids=list(body.reference_ids),
            now=now,
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
    question = question_for_practice_item(db, item)
    if question is None:
        raise AppError("external_exam_has_no_embedded_answer")
    answer_verification_current = question_eligibility(
        question, db.get(KnowledgePoint, question.kp_id)).answer_verification_current
    return PracticeItemAnswer(
        practice_item_id=item.id,
        question_id=question.id,
        question_version_id=item.question_version_id,
        stem=question.stem,
        options=_options_of(question),
        correct_answer=question.correct_answer,
        explanation=question.explanation,
        question_type=question.question_type,
        grading_mode=question.grading_mode,
        question_trust=_question_trust_view(question, db.get(KnowledgePoint, question.kp_id)),
        answer_notice=("来源身份与题面结构已机器校验；AI答案经两次独立求解、第三次独立核验一致，仍非人工或官方核验；解析内容未单独核验"
            if question.content_trust == "source_attested" and question.answer_provenance == "ai_generated"
                and question.answer_reliability == "ai_generated_consistent" else
            "AI答案存在独立求解分歧 · 已停用自动判题，仅供复习参考"
            if question.answer_provenance == "ai_generated" and question.answer_reliability == "ai_disagreement" else
            "AI生成参考答案 · 暂无已核验参考答案，练习对照不等于权威判定"
            if question.answer_provenance == "ai_generated" else
            "参考答案已按登记的权威来源核验" if answer_verification_current and question.answer_provenance == "verified_reference" else
            "答案已由人工核验（不表示官方来源）" if answer_verification_current and question.answer_provenance == "human_verified" else
            "答案来源尚未核验，内容仅供自行对照"),
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
                               error_kind=body.error_kind,
                               expected_previous_attempt_id=body.expected_previous_attempt_id)
        db.commit()
        return result
    except ValueError as exc:
        db.rollback()
        raise _http_error(exc) from exc
    except IntegrityError as exc:
        db.rollback()
        raise AppError("idempotency_key_conflict", status_code=409) from exc


def _retry_view(db, item):
    root = item
    while root.plan_id is None:
        root = db.get(PracticeItem, root.retry_source_id)
        if root is None: raise AppError('practice_item_not_found', status_code=404)
    return _build_today_active(db, root.plan, selected_rows=[item]).items[0]


@router.post('/practice-items/{item_id}/retries', response_model=PlanItemView)
def create_practice_retry(item_id: UUID, body: SubmitAnswerRequest, db: Session = Depends(get_db),
                          time_provider=Depends(get_time_provider)):
    from backend.services.practice_retry_service import create_retry
    try:
        item = create_retry(db, source_id=item_id, key=body.idempotency_key, now=time_provider())
        result = _retry_view(db, item)
        db.commit()
        return result
    except ValueError as exc:
        db.rollback()
        raise AppError(str(exc), status_code=409) from exc
    except IntegrityError as exc:
        db.rollback()
        raise AppError('idempotency_key_conflict', status_code=409) from exc


@router.get('/practice-items/{item_id}/retries', response_model=list[PlanItemView])
def read_practice_retries(item_id: UUID, db: Session = Depends(get_db)):
    if db.get(PracticeItem, item_id) is None: raise AppError('practice_item_not_found', status_code=404)
    rows = db.scalars(select(PracticeItem).where(PracticeItem.retry_source_id == item_id)
        .order_by(PracticeItem.created_at, PracticeItem.id)).all()
    return [_retry_view(db, row) for row in rows]


@router.get('/practice-items/{item_id}/retry', response_model=PlanItemView)
def read_practice_retry(item_id: UUID, db: Session = Depends(get_db)):
    item = db.get(PracticeItem, item_id)
    if item is None or item.retry_source_id is None: raise AppError('practice_item_not_found', status_code=404)
    return _retry_view(db, item)


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
def read_knowledge_tree_http(
    request: Request,
    db: Session = Depends(get_db),
    time_provider=Depends(get_time_provider),
):
    from fastapi.responses import Response
    now = time_provider()
    bind = db.get_bind()
    day = now.astimezone(SHANGHAI).date()
    cached = get_cached_knowledge_tree_http(bind=bind, day_bucket=day)
    if cached is None:
        result = read_knowledge_tree(db, lambda: now)
        cached = get_cached_knowledge_tree_http(bind=bind, day_bucket=day)
        if cached is None:
            # A concurrent relevant commit invalidated the entry while building.
            # Send this request's validated snapshot without publishing it anew.
            return Response(result.model_dump_json(), media_type='application/json',
                            headers={'Cache-Control': 'private, no-cache'})
    body, etag = cached
    headers = {'Cache-Control': 'private, no-cache', 'ETag': etag}
    validators = [value.strip() for value in request.headers.get('if-none-match', '').split(',')]
    if etag in validators or 'W/' + etag in validators or '*' in validators:
        return Response(status_code=304, headers=headers)
    # The cached bytes come from KnowledgeTreeResponse.model_dump_json(); this
    # preserves the complete public schema without copying all nodes per read.
    return Response(body, media_type='application/json', headers=headers)


def read_knowledge_tree(
    db: Session = Depends(get_db),
    time_provider=Depends(get_time_provider),
) -> KnowledgeTreeResponse:
    now = time_provider()
    bind = db.get_bind()
    day_bucket = now.astimezone(SHANGHAI).date()
    cached = get_cached_knowledge_tree(bind=bind, day_bucket=day_bucket)
    if cached is not None:
        return cached

    generation = cache_generation()
    response = _build_knowledge_tree(db, now)
    cache_knowledge_tree(
        bind=bind,
        day_bucket=day_bucket,
        generation=generation,
        value=response,
    )
    return response


def warm_knowledge_tree_cache(db: Session, now: datetime) -> None:
    """启动阶段预热首屏；失败不影响服务启动，后续请求仍可正常计算。"""
    bind = db.get_bind()
    generation = cache_generation()
    response = _build_knowledge_tree(db, now)
    cache_knowledge_tree(
        bind=bind,
        day_bucket=now.astimezone(SHANGHAI).date(),
        generation=generation,
        value=response,
    )


def _build_knowledge_tree(db: Session, now: datetime) -> KnowledgeTreeResponse:
    nodes = db.scalars(
        select(KnowledgePoint)
        .options(selectinload(KnowledgePoint.children))
        .where(KnowledgePoint.is_active.is_(True))
        .order_by(KnowledgePoint.ordinal, KnowledgePoint.code)
    ).all()
    states = {
        state.kp_id: state
        for state in db.scalars(select(KpState)).all()
    }
    # 策略按知识点存储：缺口与门槛都取该叶子自己那一行，没有配置则用默认策略。
    policies, read_context = policies_for_nodes(db, [node.id for node in nodes])
    views = {
        node.id: _node_view(node, states.get(node.id), policies.get(node.id), db=db,
                            now=now, read_context=read_context)
        for node in nodes
    }
    online_counts = dict(db.execute(select(Question.kp_id, func.count(Question.id))
        .where(Question.is_active.is_(True), Question.is_hidden.is_(False)).group_by(Question.kp_id)).all())
    eligible_counts: dict[UUID, int] = {}
    node_by_id = {node.id: node for node in nodes}
    questions_by_node: dict[UUID, list[Question]] = {}
    eligibility_by_node: dict[UUID, dict[UUID, object]] = {}
    all_questions = list(db.scalars(select(Question).options(*question_read_options()).where(
        Question.is_active.is_(True), Question.is_hidden.is_(False))))
    active_version_ids=set(db.scalars(select(QuestionVersion.id).where(QuestionVersion.is_active.is_(True),
        QuestionVersion.id.in_([q.current_version_id for q in all_questions if q.current_version_id]))))
    home_counts: dict[UUID,int]={}
    for question in all_questions:
        node = node_by_id.get(question.kp_id)
        if node is None:
            continue
        questions_by_node.setdefault(node.id, []).append(question)
        assessment = question_eligibility(question, node)
        eligibility_by_node.setdefault(node.id, {})[question.id] = assessment
        if assessment.practice_eligible:
            eligible_counts[node.id] = eligible_counts.get(node.id, 0) + 1
            if question.current_version_id in active_version_ids:
                home_counts[node.id]=home_counts.get(node.id,0)+1
    question_ids = [question.id for question in all_questions]
    attempted_ids = set(db.scalars(select(QuestionAttempt.question_id).where(
        QuestionAttempt.question_id.in_(question_ids or [UUID(int=0)]),
        QuestionAttempt.question_id.is_not(None),
    ).distinct()))
    for kp_id, view in views.items():
        view.online_question_count = online_counts.get(kp_id, 0)
        view.practice_eligible_question_count = eligible_counts.get(kp_id, 0)
        view.home_allocatable_question_count=home_counts.get(kp_id,0)
        view.blocked_active_question_count = view.online_question_count - view.practice_eligible_question_count
        node = node_by_id[kp_id]
        pool = assess_evidence_pool(questions=questions_by_node.get(kp_id, []),
            eligibility_by_id=eligibility_by_node.get(kp_id, {}),
            attempted_question_ids=attempted_ids, known=node.is_active and node.is_assessable,
            policy=policies.get(kp_id))
        view.evidence_pool_status = pool.status
        view.evidence_pool_reasons = list(pool.reasons)
        view.verified_objective_question_count = pool.verified_objective_question_count
        view.distinct_objective_question_count = pool.distinct_objective_question_count
        view.unattempted_objective_question_count = pool.unattempted_objective_question_count
        view.variation_objective_question_count = pool.variation_objective_question_count
    roots: list[KnowledgeNodeView] = []
    for node in nodes:
        view = views[node.id]
        if node.parent_id is None:
            roots.append(view)
        else:
            parent = views.get(node.parent_id)
            if parent is not None:
                parent.children.append(view)
    def review_count(view):
        own=int(bool(view.post_graduation and view.post_graduation.applicable and view.post_graduation.status in {'CONSOLIDATE','REVIEW'}))
        view.post_graduation_review_count=own+sum(review_count(c) for c in view.children)
        return view.post_graduation_review_count
    for root in roots:review_count(root)
    return KnowledgeTreeResponse(nodes=roots)


@router.get('/learning-review-needs')
def read_learning_review_needs(subject: str | None=None, limit: int=Query(default=10,ge=1,le=30),
                              db: Session=Depends(get_db), time_provider=Depends(get_time_provider)):
    from backend.services.post_graduation_service import list_review_needs
    return list_review_needs(db,now=time_provider(),subject=subject,limit=limit)


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
    eligible_count = 0
    if node.is_assessable:
        for question in db.scalars(select(Question).where(Question.kp_id == node.id, Question.is_active.is_(True))):
            if question_eligibility(question, node).practice_eligible:
                eligible_count += 1
    return KnowledgeLessonResponse(
        id=node.id,
        code=node.code,
        name=node.name,
        subject=node.subject,
        is_assessable=node.is_assessable,
        breadcrumbs=path,
        markdown=markdown,
        question_count=question_count,
        practice_eligible_question_count=eligible_count,
    )


@router.get("/knowledge/{kp_id}", response_model=KnowledgeNodeDetail)
def read_knowledge_node(kp_id: UUID, db: Session = Depends(get_db), time_provider=Depends(get_time_provider)) -> KnowledgeNodeDetail:
    node = db.get(KnowledgePoint, kp_id)
    if node is None:
        raise AppError("knowledge_point_not_found")
    state = db.get(KpState, kp_id)
    policy = policy_for_node(db, kp_id)
    view = _node_view(node, state, policy, db=db, now=time_provider())
    if not node.is_assessable:
        from backend.services.question_availability import _descendant_ids
        from backend.services.post_graduation_service import list_review_needs
        view.post_graduation_review_count=list_review_needs(db,now=time_provider(),scope_ids=_descendant_ids(db,{kp_id}))['risk_count']

    questions = db.scalars(
        select(Question)
        .where(Question.kp_id == kp_id, Question.is_active.is_(True), Question.is_hidden.is_(False))
        # Question 没有 ordinal 列；按创建顺序稳定排序，保证页面与测试可预期。
        .order_by(Question.created_at, Question.id)
    ).all()
    view.online_question_count = len(questions)
    view.practice_eligible_question_count = sum(question_eligibility(q, node).practice_eligible for q in questions)
    view.blocked_active_question_count = view.online_question_count - view.practice_eligible_question_count
    detail_attempts = set(db.scalars(select(QuestionAttempt.question_id).where(
        QuestionAttempt.question_id.in_([q.id for q in questions] or [UUID(int=0)]),
        QuestionAttempt.question_id.is_not(None),
    ).distinct()))
    detail_eligibility = {q.id: question_eligibility(q, node) for q in questions}
    pool = assess_evidence_pool(questions=questions, eligibility_by_id=detail_eligibility,
        attempted_question_ids=detail_attempts, known=node.is_active and node.is_assessable, policy=policy)
    view.evidence_pool_status = pool.status
    view.evidence_pool_reasons = list(pool.reasons)
    view.verified_objective_question_count = pool.verified_objective_question_count
    view.distinct_objective_question_count = pool.distinct_objective_question_count
    view.unattempted_objective_question_count = pool.unattempted_objective_question_count
    view.variation_objective_question_count = pool.variation_objective_question_count
    # Family nodes display existing questions through their explicit source
    # pointers, without cloning questions or borrowing child mastery evidence.
    display_questions = questions
    if ".family." in node.code:
        identities = db.execute(select(
            ExamQuestionReference.subject, ExamQuestionReference.year,
            ExamQuestionReference.question_number,
        ).where(ExamQuestionReference.knowledge_point_id == kp_id)).all()
        if identities:
            source = Question.grading_config["provenance"]["source"]
            related = db.scalars(select(Question).where(
                Question.is_active.is_(True), source["source_type"].as_string() == "exam",
                tuple_(source["subject"].as_string(), source["year"].as_integer(),
                       source["question_number"].as_integer()).in_([tuple(row) for row in identities]),
            ).order_by(Question.created_at, Question.id)).all()
            display_questions = list({q.id: q for q in [*questions, *related]}.values())
    q_views = [
        NodeQuestionView(
            id=question.id,
            question_type=question.question_type,
            difficulty=question.difficulty,
            is_variant=question.is_variant,
            stem=question.stem,
            bank_scope=question.bank_scope,
            options=question.options,
            question_source=public_question_source(question.grading_config),
            trust=_question_trust_view(question, db.get(KnowledgePoint, question.kp_id)),
            kp_id=question.kp_id,
        )
        for question in display_questions
    ]

    attempts = db.execute(
        select(
            QuestionAttempt,
            QuestionVersion.stem,
            ExamQuestionReference.id,
            ExamQuestionReference.subject,
            ExamQuestionReference.year,
            ExamQuestionReference.question_number,
            ExamQuestionReference.topic_label,
        )
        .outerjoin(QuestionVersion, QuestionVersion.id == QuestionAttempt.question_version_id)
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
            question_version_id=attempt.question_version_id,
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
        capability_profile=read_capability_profile(db, node, questions=questions, now=time_provider()),
        personal_questions=node_activity(db, kp_id),
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
    node: KnowledgePoint, state: KpState | None, policy: MasteryPolicy | None = None, *, db: Session | None = None, now=None,
    read_context=None,
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
    snapshot = current_policy_snapshot(db, state, active_policy, _read_context=read_context) if db is not None else snapshot_from_storage(state)
    from backend.services.post_graduation_service import read_post_practice
    post=read_post_practice(db,node,now=now,snapshot=snapshot,policy=active_policy) if db is not None else None
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
        post_graduation=post,
        required_question_types=dict(active_policy.required_question_types),
        policy_version=active_policy.policy_version,
        graduation_set_binding_status=(state.graduation_set_binding_status if state else "unstarted"),
        # Deprecated compatibility field: provenance is displayed per question,
        # but it no longer blocks graduation or plan selection.
        required_question_origins={},
        excluded_question_types=sorted(active_policy.excluded_question_types),
        required_skill_tags=sorted(active_policy.required_skill_tags),
    )


# 时区常量在此导出，便于测试断言学习日口径。
__all__ = ["router", "SHANGHAI", "timezone"]
