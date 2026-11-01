"""统一题目准入：验证状态决定题目能否进入正式练习/推荐/专项。

规则：
- rejected：任何正常使用都拒绝（创建版本时已拦截，历史数据兜底）。
- verified：允许正式使用。
- needs_review / unverified：只允许在个人题库查看；不得默认进入推荐、今日卷、
  专项训练、正式练习或聊天选题。
公共题库题目没有数学验证记录，按原有资格规则处理，不受本模块影响。
"""
from __future__ import annotations

from backend.models.learning import Question, QuestionVersion


def verification_status(question: Question, version: QuestionVersion | None = None) -> str:
    config = getattr(question, "grading_config", None) or {}
    status = (config.get("math_verification") or {}).get("status")
    if status:
        return str(status)
    if version is None:
        version = getattr(question, "version", None)
    snapshot = (version.snapshot_json or {}) if version is not None else {}
    return str((snapshot.get("math_verification") or {}).get("status") or "unverified")


def formal_use_allowed(question: Question, version: QuestionVersion | None = None) -> bool:
    """个人题只有 verified 能进入正式练习；公共题维持原有资格判断。"""
    if getattr(question, "bank_scope", None) != "personal":
        return True
    return verification_status(question, version) == "verified"


def admission(question: Question, *, surface: str, version: QuestionVersion | None = None) -> dict:
    status = verification_status(question, version)
    personal = getattr(question, "bank_scope", None) == "personal"
    if status == "rejected":
        return {"allowed": False, "status": status, "reason": "verification_rejected"}
    if not personal or status == "verified":
        return {"allowed": True, "status": status, "reason": "ok"}
    if surface in {"personal_bank", "bank_search_display"}:
        return {"allowed": True, "status": status, "reason": "view_only_needs_review"}
    return {"allowed": False, "status": status, "reason": "verification_required_for_formal_use"}
