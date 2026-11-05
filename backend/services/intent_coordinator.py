"""统一意图协调器：把多层规则/LLM 结果收敛为一份最终意图（含有序任务）。

优先级：安全/取消 > 明确业务规则 > 上下文指代 > LLM 结构化 > 主动澄清。
协调器只做“意图判定”，不执行写操作；执行与校验仍由既有业务服务负责。
"""
from __future__ import annotations

import re
from typing import Any

_CANCEL = r"(?:取消|撤回|不要了|算了|先不做)"
_SEQUENCE = re.compile(r"(?:先|首先)(?P<first>[^，,。；;]+)[，,。；;]?\s*(?:然后|再|之后|接着)(?P<rest>.+)$")
_MULTI_SPLIT = re.compile(r"[，,。；;]\s*(?:然后|再|接着|之后|最后)\s*")


def split_tasks(message: str) -> list[dict[str, str]]:
    """识别有序多任务；无法确定顺序时返回单任务。"""
    text = (message or "").strip()
    match = _SEQUENCE.search(text)
    if not match:
        return [{"order": 1, "action": "unknown", "text": text}] if text else []
    parts = [match.group("first").strip()] + [p.strip() for p in _MULTI_SPLIT.split(match.group("rest")) if p.strip()]
    return [{"order": index + 1, "action": "unknown", "text": part} for index, part in enumerate(parts)][:3]


def _action_for(text: str) -> str:
    if re.search(r"提示", text):
        return "hint"
    if re.search(r"讲解|解释|解析|讲讲", text):
        return "explain_current_question"
    if re.search(r"生成|出(?:一|两|几)?道|变式", text):
        return "generate_question"
    if re.search(r"加入|添加|放进|加到", text):
        return "add_to_today"
    if re.search(r"检索|题库|找(?:几)?道", text):
        return "find_questions"
    if re.search(r"减少|增加|调整|缩短|压缩|恢复", text):
        return "adjust_plan"
    return "unknown"


def resolve_intent(
    message: str,
    *,
    training_action: str | None = None,
    bank_confirmation: bool = False,
    similar_append: bool = False,
    route=None,
    llm_intent: dict[str, Any] | None = None,
) -> dict[str, Any]:
    text = (message or "").strip()
    tasks = split_tasks(text)
    for task in tasks:
        task["action"] = _action_for(task["text"])

    # 1. 安全/取消
    if re.search(_CANCEL, text) and re.search(r"安排|计划|方案|需求|专项", text):
        return {"primary_intent": "cancel", "action": "cancel", "confidence": 1.0,
                "source": "rule", "matched_rule": "safety_cancel", "reference": "none",
                "target": "none", "constraints": [], "tasks": tasks, "needs_clarification": False}
    # 2. 明确业务规则
    if training_action:
        return {"primary_intent": "personal_training", "action": training_action, "confidence": 1.0,
                "source": "rule", "matched_rule": "personal_training_command", "reference": "current",
                "target": "training", "constraints": [], "tasks": tasks, "needs_clarification": False}
    if bank_confirmation:
        return {"primary_intent": "confirm", "action": "confirm", "confidence": 1.0,
                "source": "rule", "matched_rule": "bank_confirmation", "reference": "preview",
                "target": "today", "constraints": [], "tasks": tasks, "needs_clarification": False}
    if similar_append:
        return {"primary_intent": "add_to_today", "action": "add_to_today", "confidence": 1.0,
                "source": "context", "matched_rule": "similar_append", "reference": "similar_items",
                "target": "today", "constraints": [], "tasks": tasks, "needs_clarification": False}
    if route is not None and not getattr(route, "fallback", False):
        return {"primary_intent": getattr(route, "capability", "qa"), "action": getattr(route, "intent", "qa"),
                "confidence": float(getattr(route, "confidence", 1.0) or 1.0), "source": "rule",
                "matched_rule": getattr(route, "reason", None), "reference": "current",
                "target": "today" if getattr(route, "capability", "") == "planner" else "none",
                "constraints": [], "tasks": tasks, "needs_clarification": False}
    # 3/4. LLM 结构化（含需澄清）
    if llm_intent:
        return {"primary_intent": str(llm_intent.get("intent", "qa")).lower(),
                "action": str(llm_intent.get("action") or "unknown"),
                "confidence": float(llm_intent.get("confidence") or 0.0), "source": "llm",
                "matched_rule": "bounded_classifier",
                "reference": llm_intent.get("reference") or "current",
                "target": llm_intent.get("target") or "none",
                "constraints": list(llm_intent.get("constraints") or []), "tasks": tasks,
                "needs_clarification": bool(llm_intent.get("needs_clarification")),
                "clarification_reason": llm_intent.get("clarification_reason")}
    # 5. 主动澄清
    return {"primary_intent": "qa", "action": "unknown", "confidence": 0.3, "source": "fallback",
            "matched_rule": None, "reference": "none", "target": "none", "constraints": [],
            "tasks": tasks, "needs_clarification": True,
            "clarification_reason": "没有把握理解这条消息，请说明想让我做什么。"}
