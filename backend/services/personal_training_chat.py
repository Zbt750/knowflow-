"""Narrow, deterministic ChatPage commands for the independent training service.

Only explicit training commands are intercepted. Ambiguous wording stays in the
normal QA path; this module never creates a daily-plan item or formal paper.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import logging
import re
from uuid import UUID, uuid5, NAMESPACE_URL

from sqlalchemy import select

from backend.errors import AppError
from backend.models.learning import KnowledgePoint
from backend.models.personal_training import PersonalTraining, PersonalTrainingAttempt, PersonalTrainingItem
from backend.schemas.personal_questions import GenerationTarget, PersonalGenerationRequest
from backend.services.personal_training_service import (
    PersonalTrainingError, append_personal_questions_to_training,
    append_training_questions, create_training, create_training_from_personal_questions,
    list_trainings, read_training, training_report, transition_training, _recent_mistakes,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TrainingCommand:
    action: str
    count: int | None = None
    minutes: int | None = None
    recent_mistakes: bool = False
    ai: bool = False


_NUMBERS = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
            "六": 6, "七": 7, "八": 8, "九": 9}


def _number(raw: str) -> int:
    if raw.isdigit():
        return int(raw)
    if "十" in raw:
        left, right = raw.split("十", 1)
        return (_NUMBERS.get(left, 1) if left else 1) * 10 + _NUMBERS.get(right, 0)
    return _NUMBERS[raw]


def _count(text: str) -> int | None:
    values = re.findall(r"(\d{1,2}|[一二两三四五六七八九十]{1,3})\s*(?:道|题)", text)
    return _number(values[-1]) if values else None


def _minutes(text: str) -> int | None:
    values = re.findall(r"(\d{1,3}|[一二两三四五六七八九十]{1,3})\s*分钟", text)
    if values:
        return _number(values[-1])
    hours = re.findall(r"(半|\d|[一二两三四])\s*(?:个)?小时", text)
    if hours:
        return 30 if hours[-1] == "半" else _number(hours[-1]) * 60
    return None


def parse_training_command(text: str) -> TrainingCommand | None:
    # 临时停用专项练习（2026-11-02）：只关闭聊天入口，不删除实现，便于恢复。
    return None
    value = text.strip()
    if not value:
        return None
    # “把生成的题加入今日学习/今日卷”是今日学习追加，不属于专项训练。
    if (re.search(r'加入|添加|放进|加到|放到', value)
            and re.search(r'今日|今天|卷', value)
            and not re.search(r'专项|训练', value)):
        return None
    # “把这道/刚才第 N 道题加入专项”是显式追加，不是泛化问答。
    if (re.search(r'这道|这道题|刚才|第\s*[一二两三四五六七八九十\d]+\s*道|错题', value)
            and re.search(r'(?:加入|加到|放进|放到).{0,10}(?:专项|训练)', value)):
        return TrainingCommand("append", count=1)
    # 明确“基于刚才/第 N 道题出变式”是个人题变式，不是专项创建。
    if (re.search(r'变式|新编', value)
            and re.search(r'刚才|上面|上一|第\s*[一二两三四五六七八九十\d]+\s*道|这道|那道', value)
            and not re.search(r'专项|训练', value)):
        return None
    # “安排一组/创建一次专项练习”是真正的专项创建。
    if re.search(r'(?:安排|创建|开始|来|做).{0,8}(?:一组|一次|一个)?.{0,10}(?:专项练习|专项训练|专项)', value) \
            and not re.search(r'加入|追加|加到|放进|暂停|继续|结束|进度|状态|错题', value):
        return TrainingCommand("create")
    if re.search(r"(?:我现在|目前|查看|列出|显示).{0,8}(?:有哪些|所有|我的)?专项", value):
        return TrainingCommand("list")
    if re.search(r"(?:专项中|专项里|训练中).{0,12}(?:做错|错题)|(?:做错了哪些题|专项错题|哪些题.*错了)", value):
        return TrainingCommand("mistakes")
    if re.search(r"(?:上次|最近|当前|这个|本次)?专项.{0,8}(?:完成了吗|做完了吗|进度|状态)", value):
        return TrainingCommand("status")
    if re.search(r"(?:暂停|先停).{0,8}(?:当前|这个|本次)?专项|暂停一下", value):
        return TrainingCommand("pause")
    if re.search(r"(?:继续|恢复).{0,14}(?:上次|最近|当前|这个|暂停的)(?:的|还没做完的|没做完的)?专项|(?:继续|恢复)专项", value):
        return TrainingCommand("resume")
    if re.search(r"(?:结束|完成).{0,8}(?:当前|这个|本次)?专项", value):
        return TrainingCommand("finish")
    if re.search(r"(?:当前|这个|本次)专项.{0,10}(?:难度|题目).{0,8}(?:提高|提升|调高|难一点|更难)|"
                 r"(?:把|将)(?:当前|这个|本次)?专项(?:的)?难度(?:提高|提升|调高)|"
                 r"(?:提高|提升)(?:当前|这个|本次)?专项难度", value):
        return TrainingCommand("increase_difficulty")
    # 有当前学习题目时，“生成一道类似的题”是变式生成，不是新建专项。
    if (re.search(r'(?:类似|相似|变式).{0,6}(?:的)?题|生成.{0,4}(?:类似|相似)', value)
            and not re.search(r'专项|训练', value)):
        return None
    count = _count(value)
    if re.search(r'再来\s*(?:几|一|\d{1,2})?\s*道|再加几道|再来几题', value) \
            and not re.search(r'找|查|题库|多少|库存', value):
        return TrainingCommand("append", count=count or 3)
    if count is not None and re.search(r"(?:追加|再加|加到|增加|补充).{0,14}(?:当前|这个|本次|专项|训练)|(?:当前|这个|本次)专项.{0,10}(?:追加|再加|增加)", value):
        return TrainingCommand("ai_append" if re.search(r"AI|变式|新编|生成", value) else "append",
                               count=count, ai=bool(re.search(r"AI|变式|新编|生成", value)))
    recent = bool(re.search(
        r"(?:根据|按照|结合).{0,18}(?:(?:最近|刚才|今天|历史).{0,8})?(?:做错的题|错误作答|错题)|"
        r"我.{0,10}(?:最近|总是).{0,20}(?:做错|答错)", value))
    explicit_ai = bool(re.search(r"(?:AI|人工智能|变式|新编|生成|出题)", value)
                       and re.search(r"(?:给我|帮我|为我|请|安排|生成|出|再来|追加|补充)", value)
                       and re.search(r"(?:题|练习|专项|训练)", value))
    if recent and (re.search(r"(?:创建|安排|开|做).{0,8}(?:专项|训练|练习)", value)
                   or re.search(r"(?:专项练习一下|做一组专项|安排一组训练)", value)):
        return TrainingCommand("create", minutes=_minutes(value) or 30, recent_mistakes=True)
    if explicit_ai:
        return TrainingCommand("ai_append" if re.search(r"(?:当前|这个|本次)专项|专项(?:中|里)", value) else "ai_create",
                               count=count or 1, minutes=_minutes(value) or 30,
                               recent_mistakes=recent, ai=True)
    if re.search(r"(?:给我|帮我|为我|安排|创建|开始|来一组).{0,28}(?:专项|专项练习|专项训练)", value) and (count or _minutes(value) or recent):
        return TrainingCommand("create", count=count, minutes=_minutes(value) or 30,
                               recent_mistakes=recent)
    return None


def _named_nodes(db, text: str) -> list[KnowledgePoint]:
    from backend.services.personal_generation_intent import _explicit_node_mentions
    nodes = list(db.scalars(select(KnowledgePoint).where(
        KnowledgePoint.is_active.is_(True), KnowledgePoint.is_assessable.is_(True),
        KnowledgePoint.is_reference_only.is_(False))))
    try:
        mentions = _explicit_node_mentions(text, nodes)
    except AppError as exc:
        raise PersonalTrainingError("personal_training_knowledge_point_ambiguous", 422) from exc
    return list(dict.fromkeys(row[4] for row in mentions))


def _latest_training(db, owner_session_id: UUID, *, status: str | None = None):
    query = select(PersonalTraining).where(PersonalTraining.owner_session_id == owner_session_id)
    if status:
        query = query.where(PersonalTraining.status == status)
    return db.scalar(query.order_by(PersonalTraining.updated_at.desc(), PersonalTraining.id.desc()).limit(1))


def _summary(row: dict) -> str:
    state = {"active": "进行中", "paused": "已暂停", "completed": "已结束", "cancelled": "已取消"}.get(row["status"], row["status"])
    return f"{row['title']}：{state}，已完成 {row['completed_count']}/{row['item_count']} 题，预计 {row['actual_minutes']} 分钟。"


def _question_type(text: str) -> str | None:
    mapping = {"单选": "single_choice", "选择题": "single_choice", "填空": "fill_blank",
               "计算": "calculation", "证明": "proof", "讨论": "subjective"}
    matches = {kind for label, kind in mapping.items() if label in text}
    return next(iter(matches)) if len(matches) == 1 else None


def _difficulty(text: str, fallback: str = "basic") -> str:
    if re.search(r"综合|挑战|困难|很难", text):
        return "comprehensive"
    if re.search(r"提高|稍难|难一点|更难", text):
        return "improved"
    if re.search(r"基础|简单", text):
        return "basic"
    return fallback if fallback in {"basic", "improved", "comprehensive"} else "basic"


def _user_message_for_error(exc: Exception) -> str:
    code = getattr(exc, "code", "")
    messages = {
        "personal_training_knowledge_point_required": "请说出一个现有知识点，或说明按真实错题安排。",
        "personal_training_knowledge_point_ambiguous": "这个知识点名称对应多个节点，请补充更完整的名称。",
        "knowledge_point_not_found": "没有找到对应的可训练知识点；没有创建专项。",
        "personal_training_questions_unavailable": "当前真实题库没有符合条件的题目，未创建或追加专项题目。",
        "personal_training_recent_mistakes_unavailable": "当前没有可用于这项专项的真实错题记录。",
        "personal_training_not_found": "当前会话没有可访问的专项训练。",
        "personal_training_state_conflict": "当前专项状态不支持这项操作；没有改动正式今日卷。",
        "personal_training_version_conflict": "专项已在其他操作中更新，请重新读取后再操作。",
        "personal_training_question_limit": "本专项题目数量已达到上限，未追加题目。",
        "personal_training_generated_question_invalid": "生成结果没有通过专项版本和资格核验，未加入训练。",
        "personal_training_generated_question_duplicate": "生成题与本专项已有题目重复，没有重复加入。",
        "personal_generation_scope_required": "请明确这次专项的知识点或题量分配；没有生成题目。",
        "personal_generation_scope_mismatch": "参考题目与指定知识点不一致；没有生成或加入专项题目。",
        "llm_not_configured": "AI 出题服务当前不可用；没有把题库题伪装成生成题。",
    }
    return messages.get(code, "专项操作没有完成，原专项和正式今日卷保持不变。")


def _make_ai_request(db, *, text: str, owner_session_id: UUID, current: PersonalTraining | None,
                     context, request_key: UUID, command: TrainingCommand) -> PersonalGenerationRequest:
    """Use the same bounded intent parser as ChatPage AI generation.

    In particular, a compound request such as “3 L'Hôpital choice questions,
    2 implicit differentiation fill-ins” must keep its per-node counts and
    types; reducing it to the last number silently changes the request.
    """
    from types import SimpleNamespace
    from backend.services.personal_generation_intent import _preferences, generation_intent

    explicit_nodes = _named_nodes(db, text)
    if command.recent_mistakes:
        # A request grounded in mistakes must use recorded wrong attempts even
        # when an active training has a different selected scope. Otherwise the
        # active training silently masks the evidence the user asked to use.
        recent_kps, _, _ = _recent_mistakes(
            db, [node.id for node in explicit_nodes], owner_session_id=owner_session_id)
        nodes = [db.get(KnowledgePoint, kp_id) for kp_id in recent_kps[:5]]
        nodes = [node for node in nodes if node is not None and node.is_active
            and node.is_assessable and not node.is_reference_only]
        if not nodes:
            raise PersonalTrainingError("personal_training_recent_mistakes_unavailable", 422)
    else:
        nodes = explicit_nodes
        if not nodes and current:
            nodes = [db.get(KnowledgePoint, UUID(str(value))) for value in current.selected_kp_ids or []]
            nodes = [node for node in nodes if node is not None and node.is_active
                and node.is_assessable and not node.is_reference_only]
    inherited_ids = [node.id for node in nodes]
    asks_for_context_variant = bool(re.search(
        r"变式|同类型|类似|相似|同类|这(?:道)?题|刚才(?:做错的)?题", text))
    parent_id = getattr(context, "question_id", None) if asks_for_context_variant else None
    if parent_id is None and re.search(r"变式|刚才错的题|错题.{0,8}(?:变式|再出)", text) and current:
        attempt = db.scalar(select(PersonalTrainingAttempt).join(
            PersonalTrainingItem, PersonalTrainingItem.id == PersonalTrainingAttempt.training_item_id
        ).where(PersonalTrainingItem.training_id == current.id,
            PersonalTrainingAttempt.result == "wrong").order_by(
                PersonalTrainingAttempt.submitted_at.desc(), PersonalTrainingAttempt.id.desc()).limit(1))
        parent_id = attempt.question_id if attempt else None
        if parent_id is None:
            raise PersonalTrainingError("personal_training_recent_mistakes_unavailable", 422)
    if not inherited_ids and parent_id:
        from backend.models.learning import Question
        parent = db.get(Question, parent_id)
        if parent is not None:
            node = db.get(KnowledgePoint, parent.kp_id)
            if node is not None and node.is_active and node.is_assessable and not node.is_reference_only:
                nodes = [node]
                inherited_ids = [node.id]
    if not inherited_ids:
        raise PersonalTrainingError("personal_training_knowledge_point_required", 422)
    if not 1 <= (command.count or 1) <= 5:
        raise PersonalTrainingError("personal_training_request_invalid", 422)

    # Feed only trusted, database-resolved context into the shared deterministic
    # parser. The parser returns semantic targets; actual IDs and eligibility
    # remain server supplied and are checked again by the generation service.
    parser_context = SimpleNamespace(surface="chat", daily_plan_id=None,
        knowledge_node_ids=inherited_ids, question_id=parent_id)
    try:
        if command.recent_mistakes and not explicit_nodes:
            # Mistake-based requests have no literal topic phrase to match. The
            # scope above is already resolved from persisted wrong attempts, so
            # distribute the requested total over those real weak nodes instead
            # of letting a current training's unrelated scope win by default.
            difficulty, requested_types = _preferences(text)
            grouped: dict[tuple[UUID, str, str], int] = {}
            target_index = 0
            for question_type, count in requested_types:
                for _ in range(count):
                    node = nodes[target_index % len(nodes)]
                    key = (node.id, question_type, difficulty)
                    grouped[key] = grouped.get(key, 0) + 1
                    target_index += 1
            targets = [GenerationTarget(kp_id=kp_id, question_type=question_type,
                difficulty=level, count=count) for (kp_id, question_type, level), count in grouped.items()]
            request = generation_intent(db, text, parser_context, request_key,
                generation_mode="ai_generated", confirmed_targets=targets)
        else:
            request = generation_intent(db, text, parser_context, request_key,
                generation_mode="ai_generated")
    except AppError as exc:
        raise PersonalTrainingError(exc.code, exc.status_code) from exc
    allowed_ids = {node.id for node in nodes}
    if any(target.kp_id not in allowed_ids for target in request.targets):
        raise PersonalTrainingError("personal_generation_scope_mismatch", 422)
    if parent_id and request.reference_question_id != parent_id:
        request = request.model_copy(update={"reference_question_id": parent_id})
    request = request.model_copy(update={"append_to_today": False, "plan_id": None, "surface": "chat"})
    return request


def execute_personal_training_command(
    factory, *, owner_session_id: UUID, message_id: UUID, text: str, now: datetime,
    provider=None, context=None,
) -> dict | None:
    command = parse_training_command(text)
    if command is None:
        return None
    action_key = f"chat-training-{message_id}"
    try:
        if command.action in {"list", "status", "mistakes"}:
            with factory() as db:
                if command.action == "list":
                    rows = list_trainings(db, owner_session_id=owner_session_id)
                    summaries = [{"training_id": row["training_id"], "title": row["title"],
                        "status": row["status"], "item_count": row["item_count"],
                        "completed_count": row["completed_count"], "actual_minutes": row["actual_minutes"],
                        "summary": _summary(row)} for row in rows]
                    return {"action": "list", "owner_session_id": str(owner_session_id),
                        "trainings": summaries, "summary": "当前会话还没有专项训练。" if not summaries else "\n".join(row["summary"] for row in summaries)}
                row = _latest_training(db, owner_session_id)
                if row is None:
                    return {"action": command.action, "owner_session_id": str(owner_session_id),
                        "summary": "当前会话没有已保存的专项训练。"}
                view = read_training(db, training_id=row.id, owner_session_id=owner_session_id)
                report = training_report(db, training_id=row.id, owner_session_id=owner_session_id)
                if command.action == "status":
                    return {"action": "status", "owner_session_id": str(owner_session_id),
                        "training_id": view["training_id"], "summary": _summary(view), "training": view}
                wrong = list(db.execute(select(PersonalTrainingItem.ordinal, PersonalTrainingItem.question_id,
                    PersonalTrainingAttempt.kp_id, PersonalTrainingAttempt.reason).join(
                    PersonalTrainingAttempt, PersonalTrainingAttempt.training_item_id == PersonalTrainingItem.id
                ).where(PersonalTrainingItem.training_id == row.id,
                    PersonalTrainingAttempt.result == "wrong").order_by(PersonalTrainingAttempt.submitted_at.desc())))
                names = {node.id: node.name for node in db.scalars(select(KnowledgePoint).where(
                    KnowledgePoint.id.in_({entry.kp_id for entry in wrong}))) } if wrong else {}
                details = [{"ordinal": ordinal, "question_id": str(question_id),
                    "knowledge_point": names.get(kp_id, "未知知识点"), "reason": reason}
                    for ordinal, question_id, kp_id, reason in wrong]
                summary = "本专项还没有记录错题。" if not details else "\n".join(
                    f"第{item['ordinal']}题（{item['knowledge_point']}）：{item['reason']}" for item in details)
                return {"action": "mistakes", "owner_session_id": str(owner_session_id),
                    "training_id": view["training_id"], "wrong_items": details, "report": report, "summary": summary}

        if command.action in {"ai_create", "ai_append"}:
            if provider is None:
                raise PersonalTrainingError("llm_not_configured", 503)
            with factory() as db:
                current = _latest_training(db, owner_session_id, status="active")
                if command.action == "ai_append" and current is None:
                    raise PersonalTrainingError("personal_training_not_found", 404)
                generation_key = uuid5(NAMESPACE_URL, f"personal-training-generation:{message_id}")
                body = _make_ai_request(db, text=text, owner_session_id=owner_session_id,
                    current=current, context=context, request_key=generation_key, command=command)
                target_minutes = command.minutes or 30
                current_id = current.id if current and command.action == "ai_append" else None
                current_version = current.version if current_id else None
            from backend.services.personal_question_service import run_generation
            generated = run_generation(factory, body, provider, now=now)
            ids = [UUID(value) for value in generated.get("question_ids", [])]
            batch_id = UUID(generated["batch_id"]) if generated.get("batch_id") else None
            if not ids or batch_id is None:
                return {"action": command.action, "status": "failed", "owner_session_id": str(owner_session_id),
                    "summary": generated.get("message") or "没有生成并保存通过校验的个人练习题；未创建或追加专项。",
                    "generation": generated}
            try:
                with factory.begin() as db:
                    if current_id:
                        view = append_personal_questions_to_training(db, training_id=current_id,
                            owner_session_id=owner_session_id, request_key=action_key,
                            expected_version=current_version, question_ids=ids,
                            generation_batch_id=batch_id, now=now,
                            allowed_kp_ids={UUID(str(value)) for value in (current.selected_kp_ids or [])}
                                | {target.kp_id for target in body.targets})
                        operation = "ai_append"
                    else:
                        view = create_training_from_personal_questions(db, owner_session_id=owner_session_id,
                            request_key=action_key, title="奶蛙 AI 个人专项", question_ids=ids,
                            generation_batch_id=batch_id, now=now, target_minutes=target_minutes,
                            difficulty=body.targets[0].difficulty,
                            question_type=body.targets[0].question_type,
                            expected_kp_ids={target.kp_id for target in body.targets})
                        operation = "ai_create"
            except (PersonalTrainingError, AppError) as exc:
                # Generation and training attachment are separate durable
                # transactions by design. Never claim the training was created
                # when attachment failed; surface the saved personal batch so
                # the learner can inspect/recover it without regenerating.
                return {"action": command.action, "status": "saved_questions_unattached",
                    "owner_session_id": str(owner_session_id),
                    "error_code": getattr(exc, "code", "personal_training_attach_failed"),
                    "summary": "个人练习题已生成并保存，但未能加入专项；正式今日卷未改变。请先检查个人练习题批次，再决定是否重试。",
                    "generation": generated}
            except Exception as exc:
                logger.warning("personal_training_attach_failed session_id=%s message_id=%s batch_id=%s exception_type=%s",
                    owner_session_id, message_id, batch_id, type(exc).__name__)
                return {"action": command.action, "status": "saved_questions_unattached",
                    "owner_session_id": str(owner_session_id), "error_code": "personal_training_attach_failed",
                    "summary": "个人练习题已生成并保存，但未能加入专项；正式今日卷未改变。请先检查个人练习题批次，再决定是否重试。",
                    "generation": generated}
            return {"action": operation, "generation_status": generated.get("status", "completed"),
                "owner_session_id": str(owner_session_id), "training_id": view["training_id"],
                "item_count": view["item_count"], "completed_count": view["completed_count"],
                "status": view["status"],
                "actual_minutes": view["actual_minutes"], "target_minutes": view["target_minutes"],
                "training": view, "generation": generated,
                "summary": f"已将 {len(ids)} 道通过生成校验的个人题加入独立专项（当前共 {view['item_count']} 道）。不影响正式今日卷。"}

        with factory.begin() as db:
            if command.action == "create":
                nodes = [] if command.recent_mistakes else _named_nodes(db, text)
                if not command.recent_mistakes and not nodes:
                    raise PersonalTrainingError("personal_training_knowledge_point_required", 422)
                count = command.count
                minutes = command.minutes or (max(5, count * 5) if count else 30)
                title = (nodes[0].name + "专项") if nodes else "错题驱动专项"
                view = create_training(db, owner_session_id=owner_session_id,
                    request_key=action_key, title=title, kp_ids=[node.id for node in nodes],
                    question_count=count, target_minutes=minutes,
                    difficulty=_difficulty(text, "any"), question_type=_question_type(text),
                    selection_basis="recent_mistakes" if command.recent_mistakes else "selected", now=now)
                return {"action": "create", "owner_session_id": str(owner_session_id),
                    "training_id": view["training_id"], "training": view,
                    "summary": f"专项已建立：实际分配 {view['item_count']} 道真实题库题，预计 {view['actual_minutes']} 分钟。"}
            if command.action == "resume":
                row = _latest_training(db, owner_session_id, status="paused")
                if row is None:
                    active = _latest_training(db, owner_session_id, status="active")
                    if active is not None:
                        view = read_training(db, training_id=active.id, owner_session_id=owner_session_id)
                        return {"action": "resume", "owner_session_id": str(owner_session_id),
                            "training_id": view["training_id"], "training": view,
                            "summary": "当前专项已经在进行中，可以直接继续答题。"}
            elif command.action == "pause":
                row = _latest_training(db, owner_session_id, status="active")
                if row is None:
                    paused = _latest_training(db, owner_session_id, status="paused")
                    if paused is not None:
                        view = read_training(db, training_id=paused.id, owner_session_id=owner_session_id)
                        return {"action": "pause", "owner_session_id": str(owner_session_id),
                            "training_id": view["training_id"], "training": view,
                            "summary": "当前专项已经暂停，记录和未提交答案都已保留。"}
            elif command.action == "finish":
                row = db.scalar(select(PersonalTraining).where(
                    PersonalTraining.owner_session_id == owner_session_id,
                    PersonalTraining.status.in_(["active", "paused"])
                ).order_by(PersonalTraining.updated_at.desc(), PersonalTraining.id.desc()).limit(1))
            else:
                row = _latest_training(db, owner_session_id, status="active")
            if command.action == "resume" and row is None:
                raise PersonalTrainingError("personal_training_not_found", 404)
            if row is None:
                raise PersonalTrainingError("personal_training_not_found", 404)
            if command.action in {"append", "append_ai"}:
                question_refs = None
                if command.action == "append" and re.search(
                        r'刚才|第\s*[一二两三四五六七八九十\d]+\s*道|这道|那道', text):
                    from backend.services.practice_preview_reference import latest_preview
                    reference, _ref_error = latest_preview(factory, owner_session_id, text, now)
                    if reference:
                        question_refs = [{"question_id": reference["question_id"],
                                          "question_version": reference["question_version"]}]
                    else:
                        current_view = read_training(db, training_id=row.id, owner_session_id=owner_session_id)
                        return {"action": "append", "owner_session_id": str(owner_session_id),
                                "training_id": str(row.id), "training": current_view,
                                "summary": "没有可引用的上一轮题目预览，请先查询题目并明确第几道；本次未追加。"}
                view = append_training_questions(db, training_id=row.id, owner_session_id=owner_session_id,
                    request_key=action_key, expected_version=row.version,
                    question_count=command.count or 1, now=now, question_refs=question_refs)
                added = view.get("added_count", 0)
                skipped = view.get("skipped_duplicate_count", 0)
                rejected = view.get("rejected_count", 0)
                if added:
                    prefix = "已将指定题目加入专项" if question_refs else "已从符合条件的题库追加"
                    summary = (f"{prefix}，本次新增 {added} 道，"
                               f"当前专项共 {view.get('item_count')} 道。")
                elif skipped:
                    summary = (f"这道题已经在专项中，本次未重复添加，"
                               f"当前专项共 {view.get('item_count')} 道。")
                elif rejected:
                    summary = ("指定题目未通过正式准入（needs_review/unverified 或版本失效），"
                               "未加入专项。")
                else:
                    summary = "本次没有新增题目。"
            elif command.action == "increase_difficulty":
                view = transition_training(db, training_id=row.id, owner_session_id=owner_session_id,
                    request_key=action_key, expected_version=row.version, action="increase_difficulty", now=now)
                summary = f"后续追加题难度已调整为 {view['difficulty']}；已在专项中的题目不变。"
            else:
                action = {"pause": "pause", "resume": "resume", "finish": "finish"}.get(command.action)
                if not action:
                    return None
                view = transition_training(db, training_id=row.id, owner_session_id=owner_session_id,
                    request_key=action_key, expected_version=row.version, action=action, now=now)
                summary = {"pause": "专项已暂停，可以之后继续。", "resume": "最近暂停的专项已继续。",
                    "finish": "专项已结束，正在按实际提交的答案整理报告。"}[action]
                if action == "finish":
                    finished_report = training_report(db, training_id=row.id, owner_session_id=owner_session_id)
                    weak = finished_report["wrong_knowledge_points"]
                    summary += ("\n本次记录到的薄弱点：" + "、".join(
                        f"{item['name']}（{item['wrong_count']} 次）" for item in weak)
                        if weak else "\n本次没有记录到错误答案。")
            return {"action": command.action, "owner_session_id": str(owner_session_id),
                "training_id": view["training_id"], "training": view, "summary": summary}
    except (PersonalTrainingError, AppError) as exc:
        return {"action": command.action, "status": "failed", "owner_session_id": str(owner_session_id),
            "error_code": getattr(exc, "code", "personal_training_failed"), "summary": _user_message_for_error(exc)}
