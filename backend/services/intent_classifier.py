"""LLM 意图兜底分类：仅在规则无法匹配时调用，输出受限枚举，不产生业务 ID。"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

logger = logging.getLogger(__name__)

# 与 route_message 的 bounded_classifier 兼容的白名单。
ALLOWED = {"QA", "PLANNER_QUERY", "PLANNER_RECOMMEND", "PLANNER_PLAN", "PLANNER_MODIFY"}
# 给执行层补充的细粒度动作（不直接执行，仅作诊断与后续业务参数参考）。
ACTIONS = {
    "answer_question", "explain_current_question", "hint", "solution",
    "find_questions", "find_similar", "add_to_today", "add_to_training",
    "generate_question", "generate_variant", "adjust_plan", "adjust_count",
    "adjust_budget", "restore_plan", "replace_question", "query_inventory",
    "confirm", "cancel", "unknown",
}

SYSTEM = (
    "你是奶蛙学习助手的意图分类器。只输出一个 JSON 对象，不要解释、不要 Markdown。\n"
    "字段：intent（QA/PLANNER_QUERY/PLANNER_RECOMMEND/PLANNER_PLAN/PLANNER_MODIFY 之一）、"
    "action（简短动作名）、confidence（0~1）、knowledge_scope（字符串数组，可空）、"
    "question_count（整数或 null）、time_budget（分钟整数或 null）、"
    "reference（current/history/none）、target（today/training/bank/none）、"
    "constraints（字符串数组）、needs_clarification（布尔）、clarification_reason（字符串或 null）。\n"
    "规则：只理解意图，不编造题目 ID、版本 ID、会话 ID；信息不足时 needs_clarification=true。"
)


def _extract_json(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    raw = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", raw)
    candidate = fenced.group(1) if fenced else raw
    start, end = candidate.find("{"), candidate.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        value = json.loads(candidate[start:end + 1])
    except (json.JSONDecodeError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def _context_payload(context, history) -> str:
    payload: dict[str, Any] = {
        "question_id_present": bool(getattr(context, "question_id", None)),
        "study_context": bool(getattr(context, "daily_plan_id", None) or getattr(context, "practice_item_id", None)),
        "knowledge_nodes": len(getattr(context, "knowledge_node_ids", []) or []),
        "history": [{"role": m.get("role"), "text": (m.get("text") or "")[:120]} for m in (history or [])[-4:]],
    }
    return json.dumps(payload, ensure_ascii=False)


def classify(provider, message: str, context, history=None, *, timeout=8.0) -> tuple[str | None, dict[str, Any] | None]:
    """返回 (route_enum, structured_intent)。任何失败返回 (None, None)。"""
    if provider is None or not message:
        return None, None
    started = time.monotonic()
    try:
        prompt = [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": _context_payload(context, history) + "\n用户消息：" + message[:1500]},
        ]
        raw, _usage = provider.complete(prompt, attempt=1)
    except Exception as exc:  # 网络/超时/权限等失败一律回退
        logger.warning("intent_classifier_failed: %s: %s", type(exc).__name__, str(exc)[:200], exc_info=True)
        return None, None
    intent = _extract_json(raw)
    if intent is None:
        return None, None
    route = str(intent.get("intent") or "").upper()
    if route not in ALLOWED:
        return None, None
    confidence = intent.get("confidence")
    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        confidence = 0.0
    intent["confidence"] = confidence
    action = str(intent.get("action") or "unknown")
    intent["action"] = action if action in ACTIONS else "unknown"
    intent["_elapsed_ms"] = int((time.monotonic() - started) * 1000)
    if confidence < 0.55 or intent.get("needs_clarification"):
        # 低置信度/需澄清：不授权写操作，交由上层澄清或安全兜底。
        return None, intent
    return route, intent
