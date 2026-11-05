"""Resolve explicit generation and its source from persisted conversation facts.

This is request context, not a second learning-state system. The result is
stored on the assistant turn, so confirmation/retry never guesses a new source.
"""
import re
from sqlalchemy import select
from backend.models.chat import ChatMessage
from backend.models.learning import Question, PracticeItem
from backend.services.personal_generation_intent import explicitly_generate, _preferences
from backend.services.question_versions import question_for_practice_item, question_version_reference


def is_source_problem(text):
    return bool(re.search(r"求|证明|计算|已知|设|当|原题|题目[：:]", text)
        and re.search(r"[=∑∫∞^]|\\(?:sum|int|frac|lim|begin)|[a-zA-Z].*[<>]|级数|矩阵|函数|算法", text))


def needs_reference(text):
    return bool(re.search(r"类似|相似|同类|同类型|变式|这(?:道)?题|这道|那道|刚才|换一道", text))


def question_statement(question):
    return question.stem + ("\n" + "\n".join(f"{key}. {value}" for key, value in question.options.items()) if question.options else "")


def source_candidates(text, source):
    parts = re.split(r"(?:^|\n)\s*(?:第[一二三\d]+题[：:]?|[1-9][.、])", text)
    if len(parts) <= 2:
        return []
    return [{"reference_text": part.strip(), "reference_source": source,
        "reference_question_type": "proof" if "证明" in part else "calculation"}
        for part in parts[1:] if part.strip()]


def resolve_generation_context(db, session_id, body, ctx, *, continuation=None):
    if body.qa_action != "auto":
        return None
    if continuation is not None:
        saved = (continuation.metadata_ or {}).get("generation_context")
        if saved:
            return dict(saved)
    history = list(db.scalars(select(ChatMessage).where(
        ChatMessage.session_id == session_id).order_by(ChatMessage.seq.desc()).limit(30)))
    latest = next((m for m in history if m.role == "assistant"), None)
    pending = (latest.metadata_ or {}).get("generation_context") if latest else None
    instruction = body.question
    supplied = None
    live_pending = pending and (latest.metadata_ or {}).get("personal_generation_confirmation_status") not in {"cancelled", "superseded", "expired"}
    choice = re.fullmatch(r"(?:用|选|选用|就用)?第?([一二三四五1-5])(?:道|个)?题[。！]?", instruction.strip())
    if live_pending and pending.get("reference_candidates") and choice:
        ordinal = {"一":1,"二":2,"三":3,"四":4,"五":5}.get(choice[1], int(choice[1]) if choice[1].isdigit() else 0)
        if 1 <= ordinal <= len(pending["reference_candidates"]):
            selected = pending["reference_candidates"][ordinal - 1]
            return {**pending, **selected, "waiting_reference": False, "reference_candidates": []}
    if (live_pending and not explicitly_generate(instruction) and len(instruction) < 80 and not re.search(r"为什么|解释|讲解|检查", instruction)
            and re.search(r"难度.{0,8}(?:提高|提升|降低|更大|调高|调低)|(?:再|更)(?:难|简单|综合)|(?:改成|换成|改为).{0,8}(?:选择题|填空题|计算题|证明题|大题|程序题)", instruction)):
        updated = dict(pending)
        updated["instruction"] = pending["instruction"].split("\n最新出题要求：", 1)[0] + "\n最新出题要求：" + instruction
        difficulty, types = _preferences(instruction)
        if re.search(r"难|简单|基础|提高|提升|降低|综合", instruction):
            updated["override_difficulty"] = "basic" if re.search(r"简单|基础|降低|调低", instruction) else difficulty
        if re.search(r"选择题|填空题|计算题|证明题|大题|程序题", instruction):
            updated["override_type"] = types[0][0]
        return updated
    if not explicitly_generate(instruction):
        # Only a source-like answer to a live pending request continues it.
        # “解释/检查这道题” always remains a separate QA request.
        if (not pending or not (pending.get("waiting_reference") or (latest.metadata_ or {}).get("personal_generation_confirmation"))
                or (latest.metadata_ or {}).get("personal_generation_confirmation_status") in {"cancelled", "superseded", "expired"}
                or not is_source_problem(instruction)
                or re.search(r"^(?:请|帮我)?(?:解释|讲解|检查|分析)", instruction)):
            return None
        supplied = instruction
        instruction = pending["instruction"]
    result = {"instruction": instruction, "waiting_reference": False}
    if not needs_reference(instruction):
        return result

    # An explicitly pasted source has priority over the practice sheet location.
    marker = re.search(r"(?:原题|参考题|题目)[：:]\s*([\s\S]+)", body.question)
    if marker:
        supplied = marker[1]
    if supplied:
        choices = source_candidates(supplied, {"kind":"current_user_message"})
        if choices:
            result.update(waiting_reference=True, reference_ambiguous=True, reference_candidates=choices,
                reference_source={"kind":"current_user_message"})
            return result
        result.update(reference_text=supplied, reference_source={"kind": "current_user_message"},
            reference_question_type="proof" if "证明" in supplied else "calculation")
        return result

    # An explicit pasted original wins; otherwise “这题” refers to the active
    # practice snapshot, not an older user message elsewhere in this session.
    if ctx.question_id:
        item = db.get(PracticeItem, ctx.practice_item_id) if ctx.practice_item_id else None
        question = question_for_practice_item(db, item) if item else db.get(Question, ctx.question_id)
        if question:
            result.update(reference_text=question_statement(question),
                reference_question_type=question.question_type,
                reference_question_id=str(question.id),
                reference_question_version=question_version_reference(question),
                reference_source={"kind": "question", "question_id": str(question.id),
                    "question_version_id": question_version_reference(question), "kp_id": str(question.kp_id)})
            return result

    # Never use model prose as a saved question. Only persisted question IDs or
    # identifiable statements from USER messages can supply an original.
    recent_user = next((m for m in history if m.role == "user" and
        not explicitly_generate(m.content) and is_source_problem(m.content)), None)
    if recent_user:
        choices = source_candidates(recent_user.content, {"kind":"user_message", "message_id":str(recent_user.id)})
        if choices:
            result.update(waiting_reference=True, reference_ambiguous=True, reference_candidates=choices)
            return result
        result.update(reference_text=recent_user.content,
            reference_source={"kind": "user_message", "message_id": str(recent_user.id)},
            reference_question_type="proof" if "证明" in recent_user.content else "calculation")
        return result
    ids = ((latest.metadata_ or {}).get("personal_generation") or {}).get("question_ids", []) if latest else []
    if len(ids) == 1:
        from uuid import UUID
        question = db.get(Question, UUID(ids[0]))
        if question:
            result.update(reference_text=question_statement(question),
                reference_question_type=question.question_type,
                reference_question_id=str(question.id),
                reference_question_version=question_version_reference(question),
                reference_source={"kind": "question", "question_id": str(question.id),
                    "question_version_id": question_version_reference(question), "kp_id": str(question.kp_id)})
            return result
    result["waiting_reference"] = True
    result["reference_ambiguous"] = len(ids) > 1
    if len(ids) > 1:
        from uuid import UUID
        result["reference_candidates"] = []
        for ident in ids:
            question = db.get(Question, UUID(ident))
            if question:
                result["reference_candidates"].append({"reference_text": question_statement(question),
                    "reference_question_type": question.question_type,
                    "reference_source": {"kind":"question", "question_id":str(question.id),
                        "question_version_id":question_version_reference(question), "kp_id":str(question.kp_id)}})
    return result
