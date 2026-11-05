"""Explicit local-user generation; shared provider/verifier/Question/Attempt path.

No human stamps. Reservation commits before network; replay never regenerates.
Saved questions and append are separate commits so append failure is recoverable.
"""
from datetime import datetime, timezone
import logging
import re
from uuid import UUID
from zoneinfo import ZoneInfo
from sqlalchemy import select, func, text
from backend.errors import AppError
from backend.models.learning import KnowledgePoint, Question, QuestionVersion, DailyPlan, PracticeItem
from backend.models.personal_generation import PersonalGenerationBatch
from backend.services.golden_learning_slice import digest
from backend.services.question_generation import (
    Budget, generate, assess_output, assess_problem_spec_output, current_generation_binding,
    generation_hash, PERSONAL_PROMPT_VERSION, PERSONAL_C6_PROMPT_VERSION, PERSONAL_C6_OUTPUT_LIMIT,
    PERSONAL_C7_PROMPT_VERSION, PERSONAL_C7_OUTPUT_LIMIT, GENERATION_OUTPUT_LIMIT,
)
from backend.services.personal_question_families import (
    resolve_family, contract_for, build_problem_spec, candidate_profile,
    learning_focus_from_progress, render_problem_spec, teaching_module, supports_difficulty,
)
from backend.services.practice_service import (
    DAILY_PLAN_MATERIALIZATION_LOCK_KEY,
    append_questions_to_plan,
)
from backend.services.question_versions import question_for_practice_item
from backend.services.generation_diagnostics import with_diagnostics, provider_failure_details
from backend.services.generation_outcomes import with_outcomes
from backend.services.generation_difficulty import normalize_requirement,assess_difficulty,only_numeric_size_changed,legacy_difficulty

DAILY_CALL_LIMIT = 30
PROMPT_VERSION = PERSONAL_C7_PROMPT_VERSION
from backend.services.practice_display_order import TYPE_RANK
logger = logging.getLogger(__name__)


def generation_storage_permissions(db, *, write=True):
    """Read ACLs before spending tokens; immutable versions only need INSERT.

    Use regclass resolution through the active schema/search_path. Tests and
    desktop installations do not necessarily store these tables in public.
    This function reports permissions; it never grants or changes them.
    """
    required = {"personal_generation_batches": ("SELECT",)}
    if write:
        required.update({"personal_generation_batches": ("SELECT", "INSERT", "UPDATE"),
                         "questions": ("SELECT", "INSERT", "UPDATE"),
                         "question_versions": ("SELECT", "INSERT")})
    missing = []
    for relation, privileges in required.items():
        for privilege in privileges:
            allowed = db.scalar(text("SELECT CASE WHEN to_regclass(:relation) IS NULL THEN FALSE "
                "ELSE has_table_privilege(current_user, to_regclass(:relation), :privilege) END"),
                {"relation": relation, "privilege": privilege})
            if not allowed:
                missing.append({"table": relation, "privilege": privilege})
    return missing


def _require_generation_storage(db, *, request_key, write=True):
    missing = generation_storage_permissions(db, write=write)
    if missing:
        logger.error("personal_generation_storage_denied request_key=%s missing=%s model_called=false",
                     request_key, missing)
        raise AppError("personal_generation_storage_forbidden", retryable=True)


def duplicate_key(q):
    # Across both banks, hidden/inactive rows too. Never dedup just by answer.
    from backend.services.personal_question_families import strip_registered_wording
    canonical_stem, _ = strip_registered_wording(q.stem)
    options = q.options if isinstance(q.options, dict) else None
    canonical_options = sorted(
        re.sub(r"\s+", "", str(value)).replace("$", "") for value in options.values()
    ) if options else None
    return digest({"stem": re.sub(r"\s+", "", canonical_stem).replace("$", ""),
                   # Multiple-choice label permutations are not new questions.
                   "options": canonical_options, "type": q.question_type})


def verified_problem_identity(q):
    """Dedup the same independently parsed problem across choice/fill formats."""
    from backend.services.question_identity import verified_identity
    return verified_identity(q)


def family_for(node, question_type=None):
    """Resolve only an explicitly registered canonical node and supported type."""
    spec = resolve_family(getattr(node, "code", None), question_type)
    return spec.family_id if spec else None


def bank_rows(db, *, scope="personal", kp_id=None, search="", include_hidden=False, limit=50, offset=0):
    if scope not in {"public", "personal"}: raise AppError("invalid_request", status_code=422)
    stmt = select(Question).where(Question.bank_scope == scope, Question.is_active.is_(True))
    if not include_hidden: stmt = stmt.where(Question.is_hidden.is_(False))
    if kp_id: stmt = stmt.where(Question.kp_id == kp_id)
    if search: stmt = stmt.where(Question.stem.contains(search, autoescape=True))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = list(db.scalars(stmt.order_by(Question.created_at.desc(), Question.id).limit(limit).offset(offset)))
    from backend.services.question_eligibility import question_eligibility
    def verification_state(q):
        config = q.grading_config or {}
        state = (config.get("math_verification") or {}).get("status")
        if state:
            return state
        version = db.get(QuestionVersion, q.current_version_id) if q.current_version_id else None
        snapshot = (version.snapshot_json or {}) if version else {}
        return (snapshot.get("math_verification") or {}).get("status") or "unverified"
    return {"total": total, "scope": scope, "items": [{"id": str(q.id), "kp_id": str(q.kp_id),
        "bank_scope": q.bank_scope, "hidden": q.is_hidden, "question_type": q.question_type,
        "difficulty": q.difficulty, "stem": q.stem, "options": q.options,
        "verification": verification_state(q),
        "difficulty_summary": ((q.grading_config or {}).get('generation') or {}).get('difficulty_summary'),
        "generation_batch_id": str(q.generation_batch_id) if q.generation_batch_id else None,
        "practice_eligible": question_eligibility(q, db.get(KnowledgePoint, q.kp_id)).practice_eligible}
        for q in rows]}


def node_activity(db, kp_id):
    count = db.scalar(select(func.count()).select_from(Question).where(Question.kp_id == kp_id,
        Question.bank_scope == "personal", Question.is_active.is_(True), Question.is_hidden.is_(False)))
    batch = db.scalar(select(PersonalGenerationBatch).join(Question,
        Question.generation_batch_id == PersonalGenerationBatch.id).where(Question.kp_id == kp_id,
        Question.bank_scope == "personal").order_by(PersonalGenerationBatch.created_at.desc()).limit(1))
    activity = None
    if batch:
        result = batch.result or {}
        ids = list(db.scalars(select(Question.id).where(Question.generation_batch_id == batch.id, Question.kp_id == kp_id)))
        appended = set(result.get("appended_question_ids", []))
        current_day = datetime.now(timezone.utc).astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()
        joined_label = "已加入今日学习。" if batch.study_date == current_day else "曾加入学习卷。"
        activity = {"batch_id": str(batch.id), "count": len(ids), "created_at": batch.created_at.isoformat(),
            "message": f"奶蛙新增{len(ids)}道个人练习题，" +
                       (joined_label if ids and all(str(q) in appended for q in ids) else "可进入练习。")}
    return {"count": count, "latest": activity}


def append_personal(factory, *, question_ids, plan_id=None, now=None):
    result=_append_personal_transaction(factory,question_ids=question_ids,plan_id=plan_id,now=now)
    receipt=result.pop('_receipt',None)
    if receipt:
        from backend.services.today_append_result import read_append_result
        with factory() as db:
            result['append_result']=read_append_result(db,**receipt)
    return result


def _append_personal_transaction(factory, *, question_ids, plan_id=None, now=None):
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()
    with factory.begin() as db:
        # Serialize creation/append of today's one shared paper.
        db.execute(text("SELECT pg_advisory_xact_lock(:lock_key)"),
                   {"lock_key": DAILY_PLAN_MATERIALIZATION_LOCK_KEY})
        plan = db.get(DailyPlan, plan_id) if plan_id else db.scalar(select(DailyPlan).where(DailyPlan.study_date == today))
        if plan and plan.study_date != today: raise ValueError("plan_not_today")
        rows = list(db.scalars(select(Question).where(Question.id.in_(question_ids))))
        if len(rows) != len(set(question_ids)) or any(q.bank_scope != "personal" or q.is_hidden for q in rows):
            raise ValueError("personal_question_not_available")
        if plan is None:
            if plan_id: raise ValueError("plan_not_found")
            plan = DailyPlan(study_date=today, status="active")
            db.add(plan); db.flush()
        existing = set(db.scalars(select(PracticeItem.question_id).where(PracticeItem.plan_id == plan.id)))
        add = [q for q in dict.fromkeys(question_ids) if q not in existing]
        if add: append_questions_to_plan(db, plan_id=plan.id, question_ids=add,
                                         allow_personal_practice=True)
        db.flush()
        items = list(db.scalars(select(PracticeItem).where(PracticeItem.plan_id == plan.id).order_by(PracticeItem.ordinal)))
        bound_questions = {i.id: question_for_practice_item(db, i) for i in items}
        from backend.services.practice_display_order import display_key
        ordered = sorted(items, key=lambda i: display_key(bound_questions[i.id].question_type if bound_questions[i.id] else 'external_exam',i.ordinal))
        numbers = [{"question_id": str(i.question_id), "item_id": str(i.id), "number": n,
                    "question_type": bound_questions[i.id].question_type} for n,i in enumerate(ordered, 1) if i.question_id in question_ids]
        # Saved batch activity is updated on retry too, without calling provider.
        from uuid import uuid5,NAMESPACE_URL
        operation_id=str(uuid5(NAMESPACE_URL,'personal-append:'+str(plan.id)+':'+','.join(sorted(map(str,set(question_ids))))))
        receipt=None
        for bid in {q.generation_batch_id for q in rows if q.generation_batch_id}:
            batch = db.get(PersonalGenerationBatch, bid, with_for_update=True)
            prior = dict(batch.result or {})
            operations=dict(prior.get('append_operations',{}))
            if operation_id in operations:
                receipt=operations[operation_id]
            elif add:
                receipt={'operation_id':operation_id,'plan_id':str(plan.id),
                    'item_ids':[str(i.id) for i in items if i.question_id in add],'added_count':len(add)}
                operations[operation_id]=receipt
            prior['append_operations']=operations
            prior["appended_question_ids"] = sorted(set(prior.get("appended_question_ids", [])) | {str(q.id) for q in rows if q.generation_batch_id == bid})
            prior.update(plan_id=str(plan.id), numbers=numbers, append_error=None)
            batch.result = prior
        return {"plan_id": str(plan.id), "numbers": numbers, "added": len(add),'_receipt':receipt}


def result_message(result):
    result=with_outcomes(result)
    summary=result['outcome_summary']
    saved,requested=summary['saved_count'],summary['requested_count']
    details=''.join(f"\n{'另外' if saved else ''}{item['count']}道{item['message']}。" for item in summary['failure_details'])
    if summary['not_attempted_count']:
        details+=f"\n另外{summary['not_attempted_count']}道尚未执行，批次已停止，没有补位调用。"
    if summary['unresolved_count']:
        details+=f"\n另有{summary['unresolved_count']}道缺少完整执行结果，不能认定为质量检查失败。请读取批次状态。"
    if result.get('status')=='running':return f"正在处理请求的{requested}道题，请读取状态；不会重复调用模型。"
    if not saved:
        diagnostics = with_diagnostics(result).get('diagnostics') or []
        if diagnostics:
            return f"你请求了{requested}道题，本次保存0道。"+details+'\n'+diagnostics[0]['message']+' 今日卷和已有学习记录未改变。'
        error = result.get("provider_error")
        if result.get("generation_mode") == "deterministic_fast":
            return "本次快速练习没有题目通过独立检查，未保存或修改今日卷。可以换一个支持的基础题型再试。"
        detail = ("返回的题目格式或内容未通过检查。" if error in {"JSONDecodeError", "ValidationError", "ValueError"}
                  else "模型响应超时，本次没有自动重试。" if error in {"TimeoutError", "ReadTimeout", "ConnectTimeout"}
                  else "当前模型请求未完成，请检查设置。" if error else "缺少完整执行记录，请读取批次状态后再决定是否重新请求。")
        return f"你请求了{requested}道题，本次未确认保存题目。" + details + detail + " 未修改今日卷；没有完整失败记录时不能认定为质量检查失败。"
    mode = result.get("generation_mode")
    identity = "快速练习题" if mode == "deterministic_fast" else "奶蛙AI生成练习题" if mode == "ai_generated" else "奶蛙AI辅助练习题"
    text = f"你请求了{requested}道{identity}，{saved}道通过检查并保存到对应知识点的题目列表。"
    if result.get("reference_only_question_ids"):
        text += "\n其中通用AI出题已完成格式、选项和可执行计算检查；尚无完整独立正确性证明，答案和解析仅供参考，不计入正式毕业证据。"
    text += details
    if result.get("numbers") or result.get("appended_question_ids"):
        for kind,label in (("single_choice","选择题"),("fill_blank","填空题")):
            nums = [str(n["number"]) for n in result.get("numbers", []) if n["question_type"] == kind]
            if nums: text += f"\n{label}：第{'、'.join(nums)}题。"
        text += "\n已加入今日学习，可直接作答；个人题不计入严格毕业确认。"
    elif result.get("append_error"):
        text += "加入今日学习未完成；题目仍已保存，可以重试加入，不会重新生成。"
    else:
        text += "题目已保存在对应知识节点的题目列表中。"
        if result.get("reference_only_question_ids"):
            text += ("这批题尚未完成完整独立正确性验证（needs_review），可用于个人练习与学习记录，"
                     "但不计入正式毕业证据；如需正式卷请使用正式题库题目。")
        else:
            text += "尚未加入今日学习。你可以先查看题目，再选择加入或暂不加入。"
    return text


_PROVEN_MATH_CONFLICTS = {
    "answer_final_value_conflict",
    "selected_option_conflicts_with_nonfinite_final_value",
    "statement_answer_conflict",
    "product_integral_limit_answer_conflict",
    "explanation_step_conflict",
}


def _proven_math_conflict(exc):
    """Return only an explicit bounded-verifier contradiction, never an uncertainty."""
    issues = set(getattr(exc, "issues", []) or [])
    if not issues:
        # GeneralOutput raises these stable validator identifiers directly.
        message = str(exc)
        issues = {code for code in _PROVEN_MATH_CONFLICTS if message == code}
    return next((code for code in sorted(issues) if code in _PROVEN_MATH_CONFLICTS), None)


def _generation_failure_status(exc):
    """Map provider/decoder failures to the audit vocabulary without leaking details."""
    # A structured response can be syntactically valid while a bounded check
    # proves its answer/statement/explanation inconsistent. Preserve that as a
    # mathematical rejection, not a transport or generic format failure.
    if _proven_math_conflict(exc):
        return "CONFIRMED_WRONG"
    if getattr(exc, "code", None) == "answer_truncated":
        return "OUTPUT_TRUNCATED"
    if type(exc).__name__ in {"JSONDecodeError", "ValidationError", "GeneratedFormatError"}:
        return "FORMAT_ERROR"
    if isinstance(exc,ValueError) and str(exc)=='empty_or_oversize_generation':return 'FORMAT_ERROR'
    details = provider_failure_details(exc)
    reason = details['failure_reason']
    if type(exc).__name__ in {'TimeoutError', 'ReadTimeout', 'ConnectTimeout'} or 'Timeout' in reason or reason == 'total_timeout':
        return 'PROVIDER_TIMEOUT'
    if reason.startswith('network_') or details.get('network_cause'): return 'PROVIDER_NETWORK'
    if isinstance(exc, ValueError) and str(exc) in {'generation_budget_exhausted', 'observed_model_usage_budget_exceeded'}:
        return 'BUDGET_STOPPED'
    if isinstance(exc, AppError): return 'PROVIDER_FAILED'
    return "PROCESSING_FAILED"


def run_generation(factory, body, provider=None, *, now=None):
    """Generate and check explicit personal-practice requests.

    `ai_enhanced` spends at most one call per requested item and allows the
    model to select a candidate/pedagogical focus. `deterministic_fast` makes
    zero provider calls and selects a local candidate from the progress signal.
    `ai_generated` uses independent C7 audits when a compatible solver exists;
    all other valid nodes/types use content-bound reference-only generation.
    """
    now = now or datetime.now(timezone.utc)
    from backend.services.generation_difficulty import gradient_requested, requirement_for_target
    if body.difficulty_requirement is not None and not gradient_requested(body.user_requirement):
        # Treat raw learner wording as authoritative when available. A stale
        # client-normalized “basic” must not override “比原题难很多”. Work on a
        # copy so a caller/retry cannot observe a mutated request object.
        body = body.model_copy(deep=True)
        raw = body.difficulty_requirement.raw_text or body.user_requirement or ''
        if raw:
            body.difficulty_requirement = normalize_requirement(raw,body.targets[0].difficulty)
        if body.difficulty_requirement.absolute_explicit or body.difficulty_requirement.relative_change not in {'unspecified','similar'}:
            for target in body.targets:
                target.difficulty = legacy_difficulty(body.difficulty_requirement)
    payload = body.model_dump(mode="json")
    if body.difficulty_requirement is None:
        # Preserve the hash of pre-extension requests when callers omit this
        # optional field. Existing completed batches remain replayable.
        payload.pop('difficulty_requirement',None)
    fingerprint = digest(payload)
    day = now.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()
    total = sum(t.count for t in body.targets)
    mode = body.generation_mode
    if mode not in {"ai_enhanced", "ai_generated", "deterministic_fast"}:
        raise AppError("validation_failed", status_code=422)
    if mode in {"ai_enhanced", "ai_generated"} and provider is None:
        raise AppError("llm_not_configured", status_code=503)

    with factory.begin() as db:
        db.execute(text("SELECT pg_advisory_xact_lock(4520261010)"))
        _require_generation_storage(db, request_key=body.request_key, write=False)
        old = db.scalar(select(PersonalGenerationBatch).where(PersonalGenerationBatch.request_key == str(body.request_key)))
        if old:
            if old.input_sha256 != fingerprint:
                raise AppError("idempotency_key_conflict", status_code=409)
            return {**with_outcomes(with_diagnostics(old.result)), "batch_id": str(old.id), "status": old.status, "replayed": True,
                    "message": result_message(old.result) if old.status != "running" else "出题处理中，请读取状态；不会重复调用模型。"}

        _require_generation_storage(db, request_key=body.request_key)

        reserved = db.scalar(select(func.coalesce(func.sum(PersonalGenerationBatch.reserved_calls), 0))
            .where(PersonalGenerationBatch.study_date == day))
        nodes, family_specs, learning_focus = {}, {}, {}
        for target in body.targets:
            node = db.get(KnowledgePoint, target.kp_id)
            family = resolve_family(node.code, target.question_type) if node else None
            if not node or not node.is_active or not node.is_assessable or db.scalar(select(
                    KnowledgePoint.id).where(KnowledgePoint.parent_id == node.id,
                    KnowledgePoint.is_active.is_(True)).limit(1)) is not None:
                raise AppError("personal_generation_unsupported", status_code=422)
            if family and not supports_difficulty(family, target.difficulty):
                if mode == "ai_generated": family = None
                else: raise AppError("personal_generation_unsupported_difficulty", status_code=422)
            if not family and mode != "ai_generated":
                raise AppError("personal_generation_unsupported", status_code=422)
            nodes[node.id] = node
            family_specs[(node.id, target.question_type)] = family
            if node.id not in learning_focus:
                from backend.services.capability_service import read_capability_profile
                profile = read_capability_profile(db, node)
                learning_focus[node.id] = learning_focus_from_progress(
                    profile.learning_progress if profile else None)

        parent = db.get(Question, body.reference_question_id) if body.reference_question_id else None
        if body.reference_question_id and (not parent or parent.kp_id not in nodes):
            raise AppError("personal_generation_scope_mismatch", status_code=422)
        if parent is not None:
            try:
                from backend.services.question_admission import formal_use_allowed
                allowed = formal_use_allowed(parent)
            except Exception:
                allowed = False
            if not allowed:
                raise AppError("personal_question_reference_not_admitted", status_code=422)
        if parent and mode == "deterministic_fast":
            raise AppError("personal_generation_reference_unsupported_in_fast_mode", status_code=422)

        # Existing explicit parent adaptations retain their bounded C4 route.
        # Fresh ai_generated requests use C7: the model authors the complete
        # question and answer, then the independent registered verifier decides
        # whether the candidate may enter the personal bank. C6 remains a
        # backward-compatible selection-only mode, not the default UI route.
        prompt_version = "question-generation-c4-v1" if parent else (
            PERSONAL_C7_PROMPT_VERSION if mode == "ai_generated" else
            PERSONAL_C6_PROMPT_VERSION if mode == "ai_enhanced" else "deterministic-problem-spec-v1")
        output_limit = PERSONAL_C7_OUTPUT_LIMIT if mode == "ai_generated" else GENERATION_OUTPUT_LIMIT if parent else PERSONAL_C6_OUTPUT_LIMIT
        specs_by_index = {}
        if not parent and mode != "ai_generated":
            item_index = 0
            try:
                for target in body.targets:
                    node = nodes[target.kp_id]
                    family = family_specs[(node.id, target.question_type)]
                    for _ in range(target.count):
                        variants = {}
                        for candidate_number in range(1, 4):
                            seed = digest({"request_key": str(body.request_key), "item_index": item_index,
                                "candidate": candidate_number, "node_code": node.code,
                                "question_type": target.question_type, "difficulty": target.difficulty,
                                "prompt_version": PERSONAL_C6_PROMPT_VERSION})
                            variants[f"candidate_{candidate_number}"] = build_problem_spec(
                                node_code=node.code, question_type=target.question_type,
                                difficulty=target.difficulty, seed=seed)
                        specs_by_index[item_index] = variants
                        item_index += 1
            except ValueError as exc:
                reason = str(exc)
                code = "personal_generation_unsupported_difficulty" if "difficulty_unsupported" in reason else "personal_generation_unsupported"
                raise AppError(code, status_code=422) from exc

        reserved_calls = total if mode in {"ai_enhanced", "ai_generated"} else 0
        if reserved + reserved_calls > DAILY_CALL_LIMIT:
            raise AppError("personal_generation_daily_limit", status_code=429)
        batch = PersonalGenerationBatch(request_key=str(body.request_key), input_sha256=fingerprint,
            study_date=day, reserved_calls=reserved_calls, request=payload,
            result={"requested": total, "generation_mode": mode})
        db.add(batch); db.flush(); batch_id = batch.id
        for node in nodes.values(): db.expunge(node)
        if parent: db.expunge(parent)

    logger.info("personal_generation_reserved request_key=%s batch_id=%s requested=%s model_calls=0",
                body.request_key, batch_id, total)

    budget = Budget(max_calls=total, max_reserved_tokens=total * (8000 + 512 + output_limit),
        max_output_tokens=output_limit) if mode in {"ai_enhanced", "ai_generated"} else None
    result = {"batch_id": str(batch_id), "requested": total, "generation_mode": mode,
        "attempted_indices": [], "saved_items": [],
        "difficulty_summaries": {},
        "reference_only_question_ids": [],
        "learning_focus": list({v["focus"] for v in learning_focus.values()}),
        "model_calls": 0, "question_ids": [], "failures": [], "calls": []}
    idx = 0
    variant_index = 0
    phase = "prepare_candidate"
    try:
        for target in body.targets:
            node = nodes[target.kp_id]
            focus = learning_focus[node.id]
            family = family_specs[(node.id, target.question_type)]
            for _ in range(target.count):
                idx += 1
                result['attempted_indices'].append(idx)
                phase='prepare_candidate'
                general = family is None and mode == "ai_generated"
                if general:
                    from backend.services.personal_question_general import PROMPT_VERSION as GENERAL_PROMPT
                    request = {"question_type": target.question_type, "difficulty": target.difficulty,
                        "node": {"name": node.name, "code": node.code, "subject": node.subject,
                            "summary": (node.summary or "")[:700], "learning_goal": (node.learning_goal or "")[:700]},
                        "sample": idx, "goal": "条件充分、有推理价值的个人AI练习；不冒充正式毕业题。"}
                    if parent: request["parent"] = {"stem": parent.stem[:2200], "options": parent.options,
                        "question_type": parent.question_type}
                    variants = None
                elif parent:
                    request = {"family": family.family_id, "question_type": target.question_type,
                        "difficulty": target.difficulty, "node": {"name": node.name, "code": node.code},
                        "sample": idx, "goal": "在边界内创作条件充分的教学变式。",
                        "family_contract": contract_for(family, node_code=node.code,
                            question_type=target.question_type, difficulty=target.difficulty),
                        "parent": {"stem": parent.stem, "options": parent.options, "question_type": parent.question_type}}
                    variants = None
                else:
                    variants = specs_by_index.get(variant_index)
                    if mode != "ai_generated":
                        variant_index += 1
                    request = {"family": family.family_id, "question_type": target.question_type,
                        "difficulty": target.difficulty, "node": {"name": node.name, "code": node.code},
                        "family_contract": contract_for(family, node_code=node.code,
                            question_type=target.question_type, difficulty=target.difficulty)}
                    if mode == "ai_generated":
                        # Do not send attempts, answer history, or learner notes
                        # to the provider; the user-selected node/type/difficulty
                        # and the public family contract are sufficient.
                        request["goal"] = "生成一道条件完整、答案明确、附关键推导的个人练习题。"
                    else:
                        request["learning_focus"] = focus
                        request["candidates"] = [{"candidate_id": candidate_id,
                            "profile": candidate_profile(spec), "statement": spec.canonical_problem}
                            for candidate_id, spec in variants.items()]
                requirement = requirement_for_target(body,target)
                request['difficulty_requirement'] = requirement.model_dump()
                if body.user_requirement: request['user_requirement'] = body.user_requirement

                if mode == "deterministic_fast":
                    priorities = {"foundation": "candidate_1", "consolidate": "candidate_2",
                        "delayed_retest": "candidate_3", "transfer": "candidate_2",
                        "spaced_review": "candidate_3", "practice": "candidate_1"}
                    selected_id = priorities.get(focus["focus"], "candidate_1")
                    wording_id = "direct"
                    teaching_focus_id = {"consolidate": "common_pitfall", "delayed_retest": "self_check",
                        "transfer": "self_check", "spaced_review": "self_check"}.get(focus["focus"], "method")
                    from backend.services.question_generation import C6Output
                    out = C6Output(candidate_id=selected_id, wording_id=wording_id,
                        teaching_focus_id=teaching_focus_id)
                    trace = {"prompt_version": "deterministic-problem-spec-v1", "model": "none",
                        "mode": "deterministic", "model_calls": 0, "usage": None}
                    chosen_spec = variants[selected_id]
                else:
                    try:
                        phase = "provider_call"
                        if body.reference_text:
                            request["reference"] = {"statement": body.reference_text,
                                "source": body.reference_source or {"kind": "user_provided"}}
                            request["user_requirement"] = body.user_requirement or "基于原题生成有实质变化的练习题。"
                        prompt_version = GENERAL_PROMPT if general else "question-generation-c4-v1" if parent else (
                            PERSONAL_C7_PROMPT_VERSION if mode == "ai_generated" else PERSONAL_C6_PROMPT_VERSION)
                        out, trace = generate(provider, request, budget, max_retries=0,
                            prompt_version=prompt_version)
                        result["model_calls"] += 1
                        trace["model_calls"] = 1
                    except Exception as exc:
                        result["model_calls"] = len(budget.records)
                        failure_status = _generation_failure_status(exc)
                        result["failures"].append({"index": idx, "reason": failure_status,
                            "review_status": failure_status, "error_type": type(exc).__name__,
                            "issues": getattr(exc, 'issues', []), **provider_failure_details(exc)})
                        if failure_status in {"FORMAT_ERROR", "OUTPUT_TRUNCATED"}:
                            continue
                        result["provider_error"] = type(exc).__name__
                        if isinstance(exc, AppError): result["provider_error_code"] = exc.code
                        raise
                    chosen_spec = variants.get(out.candidate_id) if variants and mode != "ai_generated" else None
                    wording_id = out.wording_id if not parent and mode == "ai_enhanced" else "direct"
                    teaching_focus_id = out.teaching_focus_id if not parent and mode == "ai_enhanced" else "method"
                    if not parent and mode != "ai_generated" and chosen_spec is None:
                        result["failures"].append({"index": idx, "reason": "FORMAT_ERROR",
                            "review_status": "FORMAT_ERROR", "issues": ["candidate_selection_invalid"]})
                        continue

                phase = "assess_candidate"
                if mode == 'ai_generated' and out.question_type != target.question_type:
                    result['failures'].append({'index':idx,'reason':'requested_type_not_followed',
                        'review_status':'INSUFFICIENT_EVIDENCE','issues':['requested_type_not_followed']})
                    continue
                if general:
                    from backend.services.personal_question_general import assess_general_output
                    try:
                        candidate = assess_general_output(out, node, request_id=f"personal:{batch_id}:{idx}",
                            trace=trace, parent=parent,
                            difficulty={"basic": "basic", "improved": "medium", "comprehensive": "advanced"}[target.difficulty])
                    except (ValueError, TypeError) as exc:
                        diagnostic = _proven_math_conflict(exc)
                        result["failures"].append({"index": idx,
                            "reason": "CONFIRMED_WRONG" if diagnostic else "FORMAT_ERROR",
                            "review_status": "CONFIRMED_WRONG" if diagnostic else "FORMAT_ERROR",
                            "issues": [diagnostic] if diagnostic else [],
                            "error_type": type(exc).__name__})
                        continue
                elif parent:
                    candidate = assess_output(out, node, request_id=f"personal:{batch_id}:{idx}",
                        mode="adapted", family=family.family_id, parent=parent, trace=trace,
                        difficulty={"basic": "basic", "improved": "medium", "comprehensive": "advanced"}[target.difficulty],
                        family_spec=family)
                elif mode == "ai_generated" and not parent:
                    candidate = assess_output(out, node, request_id=f"personal:{batch_id}:{idx}",
                        mode="original", family=family.family_id, trace=trace,
                        difficulty={"basic": "basic", "improved": "medium", "comprehensive": "advanced"}[target.difficulty],
                        family_spec=family)
                else:
                    candidate = assess_problem_spec_output(out, node, request_id=f"personal:{batch_id}:{idx}",
                        trace=trace, problem_spec=chosen_spec, family_spec=family,
                        difficulty={"basic": "basic", "improved": "medium", "comprehensive": "advanced"}[target.difficulty],
                        generation_mode=mode, wording_id=wording_id, teaching_focus_id=teaching_focus_id)
                if candidate["status"] not in {"AUTO_PASS", "REFERENCE_SAVED"}:
                    result["failures"].append({"index": idx, "reason": candidate["review_status"],
                        "review_status": candidate["review_status"], "legacy_status": candidate["status"],
                        "issues": candidate["errors"], "uncertainties": candidate.get("uncertainties", []),
                        "quality": {key: (candidate.get("quality") or {}).get(key) for key in
                            ("primary_use", "teaching_practice_eligible", "objective_grading_eligible",
                             "comparison_method", "blocking_reasons")}})
                    continue
                q = candidate["question"]
                reference = body.reference_text or (parent.stem if parent else None)
                difficulty_summary, difficulty_issues = assess_difficulty(requirement,
                    trace.get('model_difficulty_assessment'),stem=q.stem,reference=reference)
                if difficulty_issues:
                    result['failures'].append({'index':idx,'reason':'DIFFICULTY_MISMATCH',
                        'review_status':'INSUFFICIENT_EVIDENCE','issues':difficulty_issues,
                        'difficulty_summary':difficulty_summary})
                    continue
                record = q.grading_config['generation']
                record['difficulty_summary'] = difficulty_summary
                record['verified_content_hash'] = generation_hash(q)
                if not parent and mode != "ai_generated":
                    generation = q.grading_config["generation"]
                    generation["selected_candidate_id"] = out.candidate_id
                    generation["candidate_selection_authority"] = "model_menu_selection" if mode == "ai_enhanced" else "local_progress_rule"
                    generation["learning_focus"] = focus
                    generation["verified_content_hash"] = generation_hash(q)
                if parent and only_numeric_size_changed(q.stem,parent.stem):
                    result["failures"].append({"index": idx, "reason": "CONFIRMED_WRONG",
                        "review_status": "CONFIRMED_WRONG", "issues": ["adaptation_only_numeric_change"]})
                    continue
                phase = "save_question_version"
                with factory.begin() as db:
                    db.execute(text("SELECT pg_advisory_xact_lock(4520261011)"))
                    live = db.get(KnowledgePoint, node.id)
                    q.bank_scope = "personal"; q.generation_batch_id = batch_id; q.is_hidden = False
                    if not current_generation_binding(q, live):
                        result["failures"].append({"index": idx, "reason": "node_or_verifier_drift"})
                        continue
                    if parent:
                        from backend.services.question_generation import source_input_hash
                        live_parent = db.get(Question, parent.id)
                        if not live_parent or source_input_hash(live_parent) != source_input_hash(parent):
                            result["failures"].append({"index": idx, "reason": "parent_content_drift"})
                            continue
                    # 通用题可能超出独立求解器范围；不让可选的语义去重器
                    # 阻断整个领域，精确题干/选项去重仍始终执行。
                    identity=None if general else verified_problem_identity(q)
                    if any(duplicate_key(old_question) == duplicate_key(q) or
                            identity is not None and verified_problem_identity(old_question)==identity
                            for old_question in db.scalars(select(Question).where(Question.bank_scope=='personal'))):
                        result["failures"].append({"index": idx, "reason": "duplicate"})
                        continue
                    q.bank_scope = "personal"; q.generation_batch_id = batch_id; q.is_hidden = False
                    db.add(q); db.flush()
                    saved_id = str(q.id)
                    saved_ids = [*result["question_ids"], saved_id]
                    saved_items=[*result['saved_items'],{'index':idx,'question_id':saved_id}]
                    saved_summaries = {**result['difficulty_summaries'], saved_id:difficulty_summary}
                    reference_ids = [*result["reference_only_question_ids"], saved_id] if general else result["reference_only_question_ids"]
                    ledger = db.get(PersonalGenerationBatch, batch_id, with_for_update=True)
                    ledger.result = {**result, "question_ids": saved_ids,
                        'saved_items':saved_items,
                        'difficulty_summaries':saved_summaries,
                        "reference_only_question_ids": reference_ids,
                        "calls": list(budget.records) if budget else []}
                # Expose an ID only after its transaction commits. A failed
                # QuestionVersion/ledger write must not look like a saved题.
                result["question_ids"] = saved_ids
                result['saved_items']=saved_items
                result['difficulty_summaries'] = saved_summaries
                result["reference_only_question_ids"] = reference_ids
    except Exception as exc:
        result["failure_stage"] = phase
        result["failure_type"] = type(exc).__name__
        sqlstate = getattr(getattr(exc, "orig", None), "sqlstate", None)
        if idx and not any(f.get('index')==idx for f in result['failures']) and not any(q['index']==idx for q in result['saved_items']):
            result['failures'].append({'index':idx,'reason':'STORAGE_FORBIDDEN' if sqlstate=='42501' else 'PROCESSING_FAILED',
                'stage':phase,'error_type':type(exc).__name__})
        if phase == "provider_call":
            result.setdefault("provider_error", type(exc).__name__)
        else:
            result["processing_error"] = "storage_permission_denied" if sqlstate == "42501" else "generation_stopped"
        logger.error("personal_generation_failed request_key=%s batch_id=%s stage=%s exception_type=%s sqlstate=%s saved_count=%s model_calls=%s",
                     body.request_key, batch_id, phase, type(exc).__name__, sqlstate,
                     len(result["question_ids"]), result["model_calls"])

    result["calls"] = budget.records if budget else []
    result["reserved_tokens"] = budget.reserved_tokens if budget else 0
    result["status"] = "partial" if result["question_ids"] and len(result["question_ids"]) < total else "completed" if result["question_ids"] else "failed"
    result = with_outcomes(with_diagnostics(result))
    for item in result['diagnostics']:
        logger.warning('personal_generation_rejected batch_id=%s index=%s code=%s stage=%s',
                       batch_id, item['index'], item['code'], item['stage'])
    with factory.begin() as db:
        row = db.get(PersonalGenerationBatch, batch_id, with_for_update=True)
        row.status = result["status"]; row.result = result
    logger.info("personal_generation_finished request_key=%s batch_id=%s status=%s saved_count=%s model_calls=%s",
                body.request_key, batch_id, result["status"], len(result["question_ids"]), result["model_calls"])
    # Saving a generated Question is not consent to create a PracticeItem.
    # All surfaces use the explicit /personal-questions/append action after the
    # user reviews the saved question and chooses to add it to today's plan.
    return {**result, "message": result_message(result), "replayed": False}
