"""QA requests and Planner proposals: two separate confirmations, no grading writes.

注意：本文件在第十一轮曾因误覆盖被重建；重建依据 API 契约、调用方与
现有业务规则（计划预览、确认、拒绝、提案），未放宽任何准入或冻结保护。
"""
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from uuid import UUID, uuid4

from sqlalchemy import select

from backend.errors import AppError
from backend.models.practice_request import PracticeRequest
from backend.models.learning_task import LearningTask
from backend.models.chat import ChatSession, ChatMessage
from backend.schemas.learning_assistant import StudyContext, PlannerHandoff
from backend.services.assistant_router import CapabilityRoute
from backend.services.study_context_service import validate_study_context


def view(row, now=None, *, task_status=None, db=None):
    now = now or datetime.now(timezone.utc)
    status = row.status
    error_code = row.error_code
    if status in {"cancelled", "canceled"}:
        status = "failed"
        error_code = error_code or "learning_task_cancelled"
    # 以真实 planner_task 状态派生（只读：不写回数据库）。
    if status not in {"accepted", "declined"} and row.status not in {"cancelled", "canceled"}:
        if task_status == "failed":
            status = "failed"
        elif task_status in {"cancelled", "canceled"}:
            status = "failed"
            error_code = error_code or "learning_task_cancelled"
        elif task_status == "running":
            status = "planning"
        elif task_status == "ready" and status in {"pending", "planning"}:
            status = "proposed"
    if status not in {"accepted", "declined"} and row.expires_at <= now:
        status = "expired"
    from backend.services.planning_public_view import public_practice_details
    return {"id": str(row.id), "status": status,
            "source_conversation_id": str(row.source_conversation_id) if row.source_conversation_id else None,
            "source_message_id": str(row.source_message_id) if row.source_message_id else None,
            "user_request": row.user_request, "details": public_practice_details(row, now, db=db),
            "planner_task_id": str(row.planner_task_id) if row.planner_task_id else None,
            "daily_plan_id": str(row.daily_plan_id) if row.daily_plan_id else None,
            "error_code": error_code,
            "created_at": row.created_at.isoformat(), "expires_at": row.expires_at.isoformat(),
            "handled_at": row.handled_at.isoformat() if row.handled_at else None}


def recent_learning_evidence(factory, now):
    """最近 30 天真实作答摘要；辅助作答不计入独立掌握。"""
    from backend.models.learning import KnowledgePoint, QuestionAttempt
    since = now - timedelta(days=30)
    with factory() as db:
        attempts = list(db.scalars(select(QuestionAttempt).where(QuestionAttempt.submitted_at >= since)))
        wrong_kp = {}
        independent_right = independent_wrong = assisted_right = assisted_wrong = unknown = 0
        for attempt in attempts:
            receipt = attempt.grading_evidence or {}
            assisted = (receipt.get("assisted") is True
                        or receipt.get("assistance_level") in {"hint_1", "hint_2", "solution", "process_review"})
            if attempt.objective_result == "right":
                if assisted:
                    assisted_right += 1
                else:
                    independent_right += 1
            elif attempt.objective_result == "wrong":
                if assisted:
                    assisted_wrong += 1
                else:
                    independent_wrong += 1
                wrong_kp[attempt.kp_id] = wrong_kp.get(attempt.kp_id, 0) + 1
            else:
                unknown += 1
        names = {n.id: n.name for n in db.scalars(select(KnowledgePoint).where(
            KnowledgePoint.id.in_(list(wrong_kp) or [UUID(int=0)])))}
    focus = [names[k] for k, _ in sorted(wrong_kp.items(), key=lambda kv: (-kv[1], str(kv[0])))[:4] if k in names]
    summary = (f"最近 30 天客观作答：独立答对 {independent_right} 次、独立答错 {independent_wrong} 次、"
               f"辅助后答对 {assisted_right} 次、辅助后答错 {assisted_wrong} 次、无法判定 {unknown} 次。"
               + (f"主要错题知识点：{'、'.join(focus)}。" if focus else "最近没有可归因的错题知识点。"))
    return {"summary": summary, "focus_names": focus, "attempt_count": len(attempts),
            "independent_right": independent_right, "independent_wrong": independent_wrong,
            "assisted_right": assisted_right, "assisted_wrong": assisted_wrong, "unknown": unknown}


def build_plan_preview(factory, *, handoff, now, constraints=None, prior_plan=None, evidence=None):
    """按预算、真实题库与结构化约束生成可执行的计划预览。"""
    from backend.models.learning import KnowledgePoint
    from backend.services.question_availability import question_availability
    constraints = dict(constraints or {})
    budget = int(getattr(handoff, "available_minutes", None)
                 or constraints.get("target_minutes") or constraints.get("budget_minutes") or 90)
    budget = max(5, min(240, budget))
    if constraints.get("restore_plan") and prior_plan:
        restored = dict(prior_plan)
        restored["message"] = (prior_plan.get("message", "")
                               + "\n\n已按你的要求恢复上一轮时间安排。")
        return restored
    node_ids = [UUID(str(k)) for k in (handoff.target_knowledge_node_ids or [])]
    with factory() as db:
        nodes = list(db.scalars(select(KnowledgePoint).where(
            KnowledgePoint.id.in_(node_ids or [UUID(int=0)]))))
        names = [n.name for n in nodes]
        stock = question_availability(db, now=now, kp_ids=node_ids or None, limit=60)
    eligible = int(stock.get("practice_eligible_count") or 0)
    practice_minutes = max(5, min(max(5, budget - 5), int(budget * 0.6)))
    review_minutes = max(0, min(10, budget - practice_minutes - 1))
    wrap = max(0, budget - practice_minutes - review_minutes)
    if constraints.get("review_shortened"):
        shortened = max(2, wrap // 2)
        practice_minutes += (wrap - shortened)
        wrap = shortened
    prior_count = None
    if prior_plan:
        for activity in prior_plan.get("activities") or []:
            if activity.get("type") in {"practice", "remediation"}:
                prior_count = activity.get("question_count")
    locked = bool(constraints.get("question_count_locked"))
    activities = []
    review_title = (("回顾薄弱知识点：" + "、".join(names[:4])) if names else "回顾近期错题与薄弱知识点")
    if evidence and evidence.get("focus_names"):
        review_title = "优先回顾最近错题：" + "、".join(evidence["focus_names"][:3])
    activities.append({"type": "review", "minutes": review_minutes, "title": review_title})
    if eligible > 0:
        explicit_count = constraints.get("requested_question_count")
        if explicit_count is not None:
            count = min(eligible, max(1, int(explicit_count)))
        elif locked and prior_count is not None:
            count = min(eligible, int(prior_count))
        else:
            count = min(eligible, max(1, practice_minutes // 5))
        activities.append({"type": "practice", "minutes": practice_minutes,
                           "title": f"从真实题库练习（当前范围 {eligible} 道可练）",
                           "question_count": int(count), "question_count_locked": locked or explicit_count is not None})
    else:
        activities.append({"type": "remediation", "minutes": practice_minutes, "question_count": 0,
                           "title": "当前范围没有可练题：改用讲义重读、公式推导与错题重做"})
    activities.append({"type": "wrap_up", "minutes": wrap, "title": "复盘：记录错因并整理下一轮重点"})
    total = sum(a["minutes"] for a in activities)
    message = (f"按 {budget} 分钟安排的今日复习建议（尚未创建正式今日卷）：\n\n"
               + "\n".join(f"{i + 1}. {a['title']}（{a['minutes']} 分钟）" for i, a in enumerate(activities))
               + f"\n\n合计 {total} 分钟。确认后可在今日学习生成正式卷；本次没有修改正式卷。")
    result = {"budget_minutes": budget, "activities": activities, "eligible_count": eligible,
              "message": message, "constraints": constraints}
    if evidence:
        result["evidence"] = evidence
        result["message"] = evidence["summary"] + "\n\n" + message
    return result


def _inherit_scope(factory, ctx, message):
    """NA-02：追加指令缺知识点时，从本会话最近上下文继承范围（相似检索/今日卷）。

    只读取真实记录，不跨会话；找不到时返回空列表，由上层澄清。
    """
    if not re.search(r'(?:再|继续).{0,8}(?:加|来|补|增加|安排)|刚才|上面|上一|这个范围|推荐范围', message):
        return []
    today = datetime.now(timezone.utc).astimezone(__import__("zoneinfo").ZoneInfo("Asia/Shanghai")).date().isoformat()
    with factory() as db:
        recent = list(db.scalars(select(ChatMessage).where(
            ChatMessage.session_id == ctx.conversation_id,
            ChatMessage.role == "assistant").order_by(ChatMessage.seq.desc()).limit(6)))
        for row in recent:
            meta = row.metadata_ or {}
            ref = meta.get("similar_reference_question_id")
            if ref:
                from backend.models.learning import Question
                question = db.get(Question, UUID(str(ref)))
                if question is not None and question.kp_id:
                    return [question.kp_id]
            generated = (meta.get("personal_generation") or {}).get("question_ids") or []
            if generated:
                from backend.models.learning import Question
                question = db.get(Question, UUID(str(generated[0])))
                if question is not None and question.kp_id:
                    return [question.kp_id]
        from backend.models.learning import DailyPlan, PracticeItem
        plan = db.scalar(select(DailyPlan).where(DailyPlan.study_date == today))
        if plan is not None:
            item = db.scalar(select(PracticeItem).where(PracticeItem.plan_id == plan.id).order_by(PracticeItem.ordinal).limit(1))
            if item is not None and item.kp_id:
                return [item.kp_id]
    return []


def draft_request(factory, *, ctx, user_id, assistant_id, message, now, route=None):
    # 今日正式卷已生成并冻结时，不生成追加方案（避免用户确认后才收到 409）。
    from zoneinfo import ZoneInfo
    from backend.models.learning import DailyPlan, PracticeItem
    with factory() as _db:
        _today = now.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()
        _plan = _db.scalar(select(DailyPlan).where(DailyPlan.study_date == _today))
        _frozen = bool(_plan is not None and _db.scalar(
            select(PracticeItem.id).where(PracticeItem.plan_id == _plan.id).limit(1)) is not None)
    # 冻结保护的是“已生成试卷不被重排/替换”，不阻断“把用户明确确认的预览题追加到卷尾”。
    # 追加只新增 PracticeItem，不修改已有点位，也不触碰历史作答/证据。
    append_confirmed_preview = bool(route and route.reason in {"select_preview"})
    if _frozen and not append_confirmed_preview:
        return {"notice": "今日正式卷已生成并冻结，不能再重排或替换；如需追加预览题，请明确确认「加入」后再试。",
                "details": {}, "frozen": True}
    from backend.services.learning_assistant_service import planner_handoff
    effective_route = (route if (route and route.intent in {"plan", "recommend", "modify", "query"})
                       else CapabilityRoute("planner", "plan", 1, "practice_request"))
    try:
        handoff = planner_handoff(factory, ctx=ctx, user_id=user_id, message=message,
                                  route=effective_route, now=now)
    except Exception:
        import logging
        logging.getLogger(__name__).exception("planner_handoff_failed route=%s message=%s", effective_route, message[:80])
        raise
    if route and route.explanation_request:
        handoff = handoff.model_copy(update={"constraints": {**handoff.constraints,
            "explanation_request": route.explanation_request}})
    # NA-02：追加指令未带知识点时，从本会话最近上下文继承（相似检索/今日卷），不跨会话。
    if not handoff.target_knowledge_node_ids and route and route.intent in {"plan", "modify"}:
        inherited = _inherit_scope(factory, ctx, message)
        if inherited:
            handoff = handoff.model_copy(update={"target_knowledge_node_ids": inherited})
    selection = bool(route and route.reason in {"explicit_bank_selection", "select_preview", "replace_preview"})
    reference = None
    if route and route.reason in {"select_preview", "replace_preview"}:
        from backend.services.practice_preview_reference import latest_preview
        reference, error = latest_preview(factory, ctx.conversation_id, message, now)
        if error:
            antecedent = None
            if error.startswith("上一轮展示了多道题"):
                with factory() as db:
                    prior = db.scalar(select(ChatMessage).where(
                        ChatMessage.session_id == ctx.conversation_id,
                        ChatMessage.role == "assistant", ChatMessage.status == "completed",
                    ).order_by(ChatMessage.seq.desc()).limit(1))
                    if prior:
                        antecedent = ((prior.metadata_ or {}).get("preview_antecedent_message_id")
                                      or str(prior.id))
            return {"notice": error, "details": {}, "preview_antecedent_message_id": antecedent}
        changed_scope = bool(handoff.constraints.get("scope_explicit")
                             and set(map(str, handoff.target_knowledge_node_ids)) != {reference["kp_id"]})
        if changed_scope and route.reason == "select_preview":
            return {"notice": "本轮明确知识点与上一预览不同，请先查询新知识点的题目；未撤回旧方案或修改今日卷。",
                    "details": {}}
        if route.reason == "select_preview":
            from backend.services.practice_preview_reference import preview_question_state
            current = preview_question_state(factory, reference, ctx, now)
            if current and current["state"] in {"already_in_today_plan", "stale_preview"}:
                return {"notice": current["message"], "details": {}, "selection_state": current,
                        "preview_antecedent_message_id": reference.get("source_message_id")}
        # 明确替换时保留服务端解析后的新范围；未明确时沿用预览所属知识点。
        scope_ids = list(handoff.target_knowledge_node_ids) if changed_scope else [UUID(reference["kp_id"])]
        resolved_ids = (list(handoff.constraints.get("resolved_scope_node_ids") or [str(k) for k in scope_ids])
                        if changed_scope else [str(k) for k in scope_ids])
        query_state = {**reference["query_state"]}
        if changed_scope:
            query_state.update(scope_node_ids=resolved_ids, subject=handoff.subject)
        constraints = {**handoff.constraints, "scope_explicit": True,
                       "scope_origin": handoff.constraints.get("scope_origin") if changed_scope else "same_session_query_scope",
                       "resolved_scope_node_ids": resolved_ids,
                       "preview_query_state": query_state,
                       "preview_source_message_id": reference["source_message_id"]}
        if route.reason == "select_preview":
            constraints["selected_question_refs"] = [reference]
        else:
            constraints["excluded_preview_question_ids"] = [reference["question_id"]]
            constraints["preview_question_type"] = reference["question_type"]
        handoff = handoff.model_copy(update={"target_knowledge_node_ids": scope_ids,
            "requested_question_count": 1, "constraints": constraints})
    if selection:
        handoff = handoff.model_copy(update={"constraints": {**handoff.constraints, "existing_bank_only": True}})
    if selection:
        # A bank selection is a concrete question preview, not a generic time
        # schedule. Keep the same eligibility/version tools used at confirmation.
        from backend.services.composite_bank_plan import build_explained_plan
        prepared = build_explained_plan(factory, handoff=handoff, now=now)
        if prepared["status"] != "ready" or not prepared.get("draft"):
            return {"notice": prepared["message"], "details": {},
                    "trace": prepared.get("trace", []), "error_code": prepared.get("error_code")}
        payload = handoff.model_dump(mode="json")
        # Pin the exact validated preview, including replacement results, so
        # later confirmation cannot randomly select a different question/version.
        payload["constraints"] = {**payload["constraints"], "selected_question_refs": [
            {"question_id": q["question_id"], "question_version": q["question_version"]}
            for q in prepared["draft"]["questions"]]}
        payload.update({"preview_status": prepared["status"], "preview_draft": prepared["draft"],
                        "preview_message": prepared["selection_message"],
                        "explanation": prepared["explanation"], "preview_trace": prepared["trace"]})
        # Save the replacement and withdraw its owned antecedent atomically.
        # A failed builder must leave the old usable draft intact.
        with factory.begin() as db:
            if reference and route.reason == "replace_preview" and reference.get("request_id"):
                old = db.get(PracticeRequest, UUID(reference["request_id"]), with_for_update=True)
                if old is None or old.source_conversation_id != ctx.conversation_id:
                    raise AppError("forbidden", status_code=403)
                if old.status not in {"draft", "pending", "planning", "proposed"} or old.expires_at <= now:
                    raise AppError("practice_request_conflict", status_code=409)
                old.status = "declined"
                old.handled_at = now
            row = PracticeRequest(id=uuid4(), source_conversation_id=ctx.conversation_id,
                source_message_id=user_id, user_request=message, request=payload,
                status="draft", expires_at=now + timedelta(hours=24), created_at=now)
            db.add(row)
            db.flush()
            return view(row, now, db=db)
    with factory() as db:
        prior = db.scalar(select(PracticeRequest).where(
            PracticeRequest.source_conversation_id == ctx.conversation_id,
            PracticeRequest.status.in_(["draft", "proposed", "planning"]),
        ).order_by(PracticeRequest.created_at.desc()).limit(1))
        prior_plan = (prior.request or {}).get("plan_preview") if prior else None
        prior_constraints = dict((prior.request or {}).get("plan_constraints") or {}) if prior else {}
        previous_ids = (prior.request or {}).get("target_knowledge_node_ids") if prior else None
        previous_budget = (prior.request or {}).get("available_minutes") if prior else None
    names_specific = re.search(r'极限|积分|导数|求导|矩阵|行列式|级数|概率|线代|高数|微分|方程', message)
    if re.search(r'线代|线性代数', message) and not re.search(r'矩阵|行列式|向量|特征值|二次型', message):
        from backend.models.learning import KnowledgePoint as _Kp
        with factory() as _db:
            la_node = _db.scalar(select(_Kp).where(_Kp.name == '线性代数', _Kp.is_active.is_(True)))
        if la_node is not None:
            handoff = handoff.model_copy(update={"target_knowledge_node_ids": [la_node.id]})
    constraints = dict(prior_constraints)
    prior_n = None
    if prior_plan:
        for activity in prior_plan.get("activities") or []:
            if activity.get("type") in {"practice", "remediation"}:
                prior_n = activity.get("question_count")
    count_match = re.search(r'(?:只做|只练|安排|来|做|保持)\s*(\d{1,2})\s*道', message)
    delta_match = re.search(r'(?:再|多)(?:增加|加|来)\s*(\d{1,2})\s*道', message)
    reduce_match = re.search(r'(?:减少|去掉|降到)\s*(\d{1,2})\s*道', message)
    if re.search(r"题量(?:不要|不能|别)增加|不增加题量", message):
        constraints["question_count_locked"] = True
    requested_count = None
    if re.search(r"恢复.{0,6}题量|恢复刚才.{0,6}题量", message) and prior_n:
        requested_count = int(prior_n)
    elif count_match:
        requested_count = int(count_match.group(1))
    elif delta_match and prior_n:
        requested_count = int(prior_n) + int(delta_match.group(1))
    elif reduce_match and prior_n:
        requested_count = max(1, int(prior_n) - int(reduce_match.group(1)))
    elif constraints.get("question_count_locked") and prior_n:
        requested_count = int(prior_n)
    if requested_count is not None:
        constraints["requested_question_count"] = requested_count
        constraints["question_count_locked"] = True
        handoff = handoff.model_copy(update={"requested_question_count": requested_count})
    if re.search(r"复盘.{0,6}(?:缩短|减少)|缩短.{0,6}复盘", message):
        constraints["review_shortened"] = True
    if re.search(r"恢复.{0,6}(?:时间|安排)|按刚才|恢复刚才", message) and prior_plan:
        constraints["restore_plan"] = True
    if not names_specific and previous_ids:
        handoff = handoff.model_copy(update={"target_knowledge_node_ids": [UUID(str(k)) for k in previous_ids][:8]})
    if previous_budget and not re.search(r"\d+\s*(?:分钟|小时)", message):
        handoff = handoff.model_copy(update={"available_minutes": int(previous_budget)})
    evidence = None
    if re.search(r"根据.{0,8}(?:最近|近期|表现)|最近.{0,6}(?:表现|情况)|明天.{0,6}(?:怎么|安排)", message):
        evidence = recent_learning_evidence(factory, now)
    plan_preview = build_plan_preview(factory, handoff=handoff, now=now,
                                      constraints=constraints, prior_plan=prior_plan, evidence=evidence)
    payload = handoff.model_dump(mode="json")
    payload.update({"plan_preview": plan_preview, "plan_constraints": constraints,
                    "preview_message": plan_preview.get("message", "")})
    with factory.begin() as db:
        row = PracticeRequest(id=uuid4(), source_conversation_id=ctx.conversation_id,
                              source_message_id=user_id, user_request=message, request=payload,
                              status="draft", expires_at=now + timedelta(hours=24), created_at=now)
        db.add(row)
        db.flush()
        result = view(row, now, db=db)
    return result


def list_requests(factory, *, source_conversation_id=None, now=None):
    now = now or datetime.now(timezone.utc)
    with factory() as db:
        query = select(PracticeRequest)
        if source_conversation_id:
            query = query.where(PracticeRequest.source_conversation_id == source_conversation_id)
        rows = list(db.scalars(query.order_by(PracticeRequest.created_at.desc()).limit(50)))
        task_ids = [row.planner_task_id for row in rows if row.planner_task_id]
        tasks = {task.id:task for task in db.scalars(
            select(LearningTask).where(LearningTask.id.in_(task_ids)))} if task_ids else {}
        output=[]
        today=now.astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat()
        for row in rows:
            task=tasks.get(row.planner_task_id)
            shown=view(row,now,task_status=task.status if task and row.status!='draft' else None,db=db)
            if row.status not in {'accepted','declined','draft'} and shown['status']!='expired':
                if task and task.status in {'failed','cancelled','canceled'}:
                    shown['status']='failed'
                    shown['error_code']=task.error_code or ('learning_task_cancelled'
                        if task.status in {'cancelled','canceled'} else 'planning_interrupted')
                elif shown['status']=='proposed' and task:
                    date=((task.context or {}).get('current_plan') or {}).get('study_date')
                    if date and date!=today:
                        shown['status']='expired'
                        shown['error_code']='learning_task_stale_draft'
                elif row.status=='planning' and task is None:
                    raw=(row.request or {}).get('planning_started_at')
                    try:
                        started=datetime.fromisoformat(raw.replace('Z','+00:00')) if raw else row.created_at
                        if started.tzinfo is None:started=started.replace(tzinfo=timezone.utc)
                    except (ValueError,TypeError,AttributeError):started=row.created_at
                    if now-started>timedelta(minutes=5):
                        shown['status']='failed';shown['error_code']='planning_interrupted'
            output.append(shown)
        return output


def send_request(factory, request_id, *, source_conversation_id, target_study_session_id=None, now=None):
    now = now or datetime.now(timezone.utc)
    with factory.begin() as db:
        row = db.get(PracticeRequest, request_id, with_for_update=True)
        if not row:
            raise AppError("practice_request_not_found", status_code=404)
        if row.source_conversation_id != source_conversation_id:
            raise AppError("forbidden", status_code=403)
        if target_study_session_id:
            target = db.get(ChatSession, target_study_session_id)
            if (not target or target.purpose != "study" or target.mode != "builtin" or target.archived_at):
                raise AppError("forbidden", status_code=403)
        if view(row, now, db=db)["status"] == "expired":
            raise AppError("practice_request_expired", status_code=409)
        if row.status in {"pending", "planning", "proposed", "accepted"}:
            return view(row, now, db=db)
        if row.status != "draft":
            raise AppError("practice_request_conflict", status_code=409)
        if not row.request.get("target_knowledge_node_ids"):
            raise AppError("practice_scope_required", status_code=422)
        row.status = "pending"
        row.request = {**row.request, "confirmation_a": True,
                       **({"target_study_session_id": str(target_study_session_id)}
                          if target_study_session_id else {})}
        return view(row, now, db=db)


def decline_request(factory, request_id, *, now=None):
    now = now or datetime.now(timezone.utc)
    with factory.begin() as db:
        row = db.get(PracticeRequest, request_id, with_for_update=True)
        if not row:
            raise AppError("practice_request_not_found", status_code=404)
        if row.status in {"accepted", "declined"}:
            return view(row, now, db=db)
        row.status = "declined"
        row.handled_at = now
        return view(row, now, db=db)


def _selection_draft(factory, handoff):
    """按已确认选题构造正式草稿；不调用 LLM，保留题目与版本。"""
    from backend.models.learning import KnowledgePoint, Question, QuestionVersion
    from backend.services.learning_task_tools import _question_source_category
    from backend.services.question_eligibility import question_eligibility
    from backend.services.question_versions import question_version_reference
    refs = handoff.constraints.get("selected_question_refs") or []
    if not refs:
        return None
    questions = []
    with factory() as db:
        for ref in refs:
            try:
                q = db.get(Question, UUID(str(ref["question_id"])))
                v = db.get(QuestionVersion, UUID(str(ref["question_version"])))
            except (KeyError, TypeError, ValueError):
                return None
            if not q or not v or v.question_id != q.id:
                return None
            version_id = question_version_reference(q)
            if not version_id or str(v.id) != str(version_id):
                return None
            node = db.get(KnowledgePoint, q.kp_id)
            assessment = question_eligibility(q, node)
            if not assessment.practice_eligible:
                return None
            questions.append({"question_id": str(q.id), "kp_id": str(q.kp_id),
                "kp_name": node.name if node else "该知识点", "stem": q.stem, "options": q.options,
                "question_type": q.question_type, "difficulty": q.difficulty,
                "question_role": q.question_role, "is_variant": q.is_variant,
                "source_category": _question_source_category(q),
                "question_trust": assessment.public_dict(), "eligibility_snapshot": assessment.public_dict(),
                "minutes": q.estimated_minutes, "question_version": version_id})
    if not questions:
        return None
    total = sum(int(item.get("minutes") or 0) for item in questions)
    budget = int(getattr(handoff, "available_minutes", None) or 90)
    if total > budget:
        return None
    return {"selected_question_ids": [item["question_id"] for item in questions],
            "questions": questions, "review_nodes": [], "review_minutes": 0,
            "total_minutes": total, "budget_minutes": budget,
            "rationale": "按用户已确认的选题生成；保留题目与版本，未重新挑选。",
            "warnings": ["本方案由确定性转换生成，未调用模型。"]}


def _preview_draft(factory, handoff, plan_preview, now):
    """模型不可用时，按已确认预览与真实题库生成草稿；无合适题则明确留空。"""
    from backend.models.learning import KnowledgePoint, Question
    from backend.services.learning_task_tools import _question_source_category
    from backend.services.question_availability import _descendant_ids
    from backend.services.question_eligibility import question_eligibility
    from backend.services.question_versions import question_version_reference
    if not plan_preview:
        return None
    budget = int(plan_preview.get("budget_minutes") or getattr(handoff, "available_minutes", 90) or 90)
    node_ids = [UUID(str(k)) for k in (handoff.target_knowledge_node_ids or [])]
    excluded = {UUID(str(x)) for x in (handoff.constraints.get("excluded_preview_question_ids") or [])}
    question_type = handoff.constraints.get("preview_question_type")
    count = 1
    for activity in plan_preview.get("activities") or []:
        if activity.get("type") in {"practice", "remediation"}:
            count = int(activity.get("question_count") or 1)
    count = max(1, min(count, 10))
    questions, nodes, total = [], [], 0
    with factory() as db:
        scope = _descendant_ids(db, set(node_ids)) if node_ids else set()
        rows = []
        if scope:
            query = select(Question).where(Question.kp_id.in_(scope), Question.is_active.is_(True),
                                           Question.is_hidden.is_(False))
            if question_type:
                query = query.where(Question.question_type == question_type)
            rows = list(db.scalars(query.order_by(Question.estimated_minutes, Question.id).limit(200)))
        for q in rows:
            if q.id in excluded:
                continue
            version = question_version_reference(q)
            node = db.get(KnowledgePoint, q.kp_id)
            assessment = question_eligibility(q, node) if node else None
            if not version or not assessment or not assessment.practice_eligible:
                continue
            minutes = int(q.estimated_minutes or 0)
            if total + minutes > budget:
                continue
            questions.append({"question_id": str(q.id), "kp_id": str(q.kp_id),
                "kp_name": node.name if node else "该知识点", "stem": q.stem, "options": q.options,
                "question_type": q.question_type, "difficulty": q.difficulty,
                "question_role": q.question_role, "is_variant": q.is_variant,
                "source_category": _question_source_category(q),
                "question_trust": assessment.public_dict(),
                "eligibility_snapshot": assessment.public_dict(),
                "minutes": minutes, "question_version": version})
            nodes.append({"kp_id": str(q.kp_id), "name": node.name if node else "该知识点"})
            total += minutes
            if len(questions) >= count:
                break
    if not questions:
        return {"selected_question_ids": [], "questions": [], "review_nodes": [],
                "review_minutes": budget, "total_minutes": budget, "budget_minutes": budget,
                "rationale": "模型不可用；当前范围没有符合准入的题，未编造题目。",
                "warnings": ["当前范围没有可练题：请缩小/调整范围或先补充题库；本方案未加入具体题目。"]}
    return {"selected_question_ids": [item["question_id"] for item in questions],
            "questions": questions, "review_nodes": nodes,
            "review_minutes": max(0, budget - total), "total_minutes": budget, "budget_minutes": budget,
            "rationale": "模型不可用；按已确认范围从真实题库选择准入通过且版本有效的题。",
            "warnings": ["本方案由确定性 fallback 生成，未调用模型；已保留题目与版本。"]}


def plan_request(factory, request_id, *, study_session_id, provider, now=None):
    from backend.services.learning_assistant_service import prepare_planner
    from backend.services.learning_task_service import run_task
    now = now or datetime.now(timezone.utc)
    with factory.begin() as db:
        row = db.get(PracticeRequest, request_id, with_for_update=True)
        if not row:
            raise AppError("practice_request_not_found", status_code=404)
        if row.expires_at<=now and row.status!='accepted':
            raise AppError("practice_request_expired",status_code=409)
        if row.status not in {'pending','planning','proposed','failed','accepted'} or not (row.request or {}).get('confirmation_a'):
            raise AppError("practice_request_conflict", status_code=409)
        target=db.get(ChatSession,study_session_id)
        if not target or target.purpose!='study' or target.mode!='builtin' or target.archived_at:
            raise AppError('forbidden',status_code=403)
        today=now.astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat()
        if target.study_date!=today:
            raise AppError('practice_request_expired',status_code=409)
        bound=(row.request or {}).get('target_study_session_id')
        if bound and bound!=str(study_session_id):
            raise AppError('forbidden',status_code=403)
        row.request={**row.request,'target_study_session_id':str(study_session_id)}
        workflow_keys={'plan_preview','plan_constraints','preview_message','confirmation_a','confirmation_b','target_study_session_id'}
        handoff_payload = {k:v for k,v in row.request.items() if k not in workflow_keys}
        # Requests persisted before the complete handoff envelope was introduced
        # may contain only planning constraints. Recover provenance from the
        # durable PracticeRequest row instead of turning a valid confirmation
        # into a 500 during model validation.
        handoff_payload.setdefault("source_conversation_id",
            str(row.source_conversation_id or study_session_id))
        handoff_payload.setdefault("source_message_id",
            str(row.source_message_id) if row.source_message_id else None)
        handoff_payload.setdefault("user_problem", row.user_request or "")
        handoff_payload.setdefault("request_type", "plan")
        handoff_payload['generated_at']=row.created_at
        handoff=PlannerHandoff.model_validate(handoff_payload)
    ctx = StudyContext(surface="study", origin="practice", conversation_id=study_session_id)
    # 幂等：同一 PracticeRequest 已有任务时直接返回，不重复创建。
    with factory() as db:
        request_row = db.get(PracticeRequest, request_id)
        existing_task_id = request_row.planner_task_id if request_row else None
    if existing_task_id:
        from backend.services.learning_task_service import get_task
        try:
            existing = get_task(factory, existing_task_id)
        except AppError:
            existing = None
        if existing is not None and existing.status not in {"failed", "cancelled"}:
            with factory() as db:
                current_request = db.get(PracticeRequest, request_id)
                return {"request": view(current_request, now, db=db),
                        "task": existing.model_dump(mode="json")}
    task = prepare_planner(factory, ctx=ctx, handoff=handoff, now=now)
    with factory.begin() as db:
        request_row=db.get(PracticeRequest,request_id,with_for_update=True)
        task_row=db.get(LearningTask,task.task_id,with_for_update=True)
        link=(task_row.context or {}).get('practice_request_id') if task_row else None
        if (request_row is None or task_row is None or task_row.session_id!=study_session_id
                or (link and link!=str(request_id))):
            raise AppError('practice_request_conflict',status_code=409)
        task_row.context={**(task_row.context or {}),'practice_request_id':str(request_id)}
        request_row.planner_task_id=task.task_id

    draft = _selection_draft(factory, handoff) if handoff.constraints.get("selected_question_refs") else None
    if draft is not None:
        from backend.services.learning_task_service import get_task
        with factory.begin() as db:
            task_row = db.get(LearningTask, task.task_id, with_for_update=True)
            task_row.draft = draft
            task_row.status = "ready"
            task_row.error_code = None
            task_row.message = (f"已按确认的选题生成正式学习草稿：{len(draft['questions'])} 道，"
                                f"预算 {draft['budget_minutes']} 分钟；尚未加入今日卷。")
            task_row.metrics = {**(task_row.metrics or {}), "deterministic_fallback": True,
                                "model_calls": 0, "memory_lifecycle": "closed"}
            row = db.get(PracticeRequest, request_id, with_for_update=True)
            row.planner_task_id = task.task_id
            row.status = "proposed"
            row.error_code = None
            row.handled_at = now
            request_view = view(row, now, db=db)
        result = get_task(factory, task.task_id)
        return {"request": request_view, "task": result.model_dump(mode="json")}
    if handoff.constraints.get("selected_question_refs") or handoff.constraints.get("explanation_request"):
        from backend.services.composite_bank_plan import prepare_explained_plan
        result = prepare_explained_plan(factory, task.task_id, handoff=handoff, now=now)
    else:
        result = run_task(factory, task.task_id, provider, now=now)
    if result.status != "ready" or not result.draft:
        with factory() as db:
            request_row = db.get(PracticeRequest, request_id)
            plan_preview = (request_row.request or {}).get("plan_preview") if request_row else None
        fallback = _preview_draft(factory, handoff, plan_preview, now)
        if fallback is not None:
            from backend.services.learning_task_service import get_task
            with factory.begin() as db:
                task_row = db.get(LearningTask, task.task_id, with_for_update=True)
                task_row.draft = fallback
                task_row.status = "ready"
                task_row.error_code = None
                task_row.message = (f"已按确认的计划生成草稿（预算 {fallback['budget_minutes']} 分钟，"
                                    f"{len(fallback['questions'])} 道题）；模型本次不可用，已用真实题库完成选题。")
                task_row.metrics = {**(task_row.metrics or {}), "deterministic_fallback": True,
                    "fallback_reason": result.error_code or "llm_unavailable",
                    "model_calls": 0, "memory_lifecycle": "closed"}
                row = db.get(PracticeRequest, request_id, with_for_update=True)
                row.planner_task_id = task.task_id
                row.status = "proposed"
                row.error_code = None
                row.handled_at = now
                request_view = view(row, now, db=db)
            result = get_task(factory, task.task_id)
            return {"request": request_view, "task": result.model_dump(mode="json")}
    with factory.begin() as db:
        row = db.get(PracticeRequest, request_id, with_for_update=True)
        row.planner_task_id = task.task_id
        row.status = "proposed" if result.status == "ready" and result.draft else "failed"
        row.error_code = None if row.status == "proposed" else (result.error_code or "insufficient_practice_inventory")
        row.handled_at = now
        return {"request": view(row, now, db=db), "task": result.model_dump(mode="json")}
