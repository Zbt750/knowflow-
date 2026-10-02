"""Small explainable dimensions mapped from metadata, not model guesses."""
from dataclasses import dataclass
from uuid import UUID
from backend.schemas.capability import CapabilityDimension, CapabilityProfile


@dataclass(frozen=True)
class CapabilityQuestion:
    id: UUID
    question_type: str
    question_role: str
    is_variant: bool
    gradable: bool
    skill_tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class CapabilityAttempt:
    question_id: UUID | None
    result: str
    assisted: bool | None
    category: str | None


LABELS = {
    "concept_conditions": "概念与条件",
    "final_result": "最终结果计算",
    "application_transfer": "变式与应用",
    "reasoning_process": "证明与讨论",
    "algorithm_process": "算法与程序",
    "other": "其他作答形式",
}
PROCESS_KEYS = frozenset({"reasoning_process", "algorithm_process", "other"})
STATUS_LABELS = {"not_verified": "尚未验证", "limited_evidence": "证据有限",
                 "independent_evidence": "已有独立证据", "needs_retest": "待复测"}


def capability_keys(question_type: str, question_role: str, is_variant: bool) -> tuple[str, ...]:
    if question_type in {"single_choice", "multiple_choice"}:
        keys = ["concept_conditions"]
    elif question_type in {"fill_blank", "calculation", "program_output", "code_execution"}:
        keys = ["final_result"]
    elif question_type in {"proof", "discussion"}:
        keys = ["reasoning_process"]
    elif question_type in {"program", "algorithm", "code"}:
        keys = ["algorithm_process"]
    else:
        keys = ["other"]
    # A proof/program's final answer never establishes its reasoning or transfer.
    if keys[0] not in PROCESS_KEYS and (is_variant or question_role in {"variant", "comprehensive"}):
        keys.append("application_transfer")
    return tuple(keys)


def project_capabilities(*, subject: str, questions: list[CapabilityQuestion],
        recent_attempts: list[CapabilityAttempt], confirmed_ids: set[UUID], pending_ids: set[UUID],
        history_truncated: bool = False, transfer_confirmed_ids: set[UUID] | None = None) -> CapabilityProfile:
    keys = ["concept_conditions", "final_result", "application_transfer", "reasoning_process"]
    if "408" in subject:
        keys.append("algorithm_process")
    mapped = {q.id: capability_keys(q.question_type, q.question_role, q.is_variant) for q in questions}
    for value in mapped.values():
        for key in value:
            if key not in keys: keys.append(key)
    dimensions = []
    for key in keys:
        pool = [q for q in questions if key in mapped[q.id]]
        ids = {q.id for q in pool}
        attempts = [a for a in recent_attempts if a.question_id in ids]
        # Current graders only observe final answers; process capabilities stay unverified.
        graded_ids = {q.id for q in pool if q.gradable} if key not in PROCESS_KEYS else set()
        pending = pending_ids & graded_ids
        eligible = transfer_confirmed_ids if key == "application_transfer" and transfer_confirmed_ids is not None else confirmed_ids
        independent = (eligible & graded_ids) - pending
        status = "needs_retest" if pending else "independent_evidence" if independent else "limited_evidence" if attempts else "not_verified"
        if pending:
            reason = f"{len(pending)} 道题待独立复测；立即改正或看解析后完成不替代复测。"
        elif independent:
            reason = f"当前有 {len(independent)} 道不同题的最终答案独立证据，不代表全面掌握。"
        elif key in PROCESS_KEYS:
            reason = "尚无可靠的过程核验；作答、自述与 AI 辅助审阅不确认该能力。"
        elif not pool:
            reason = "当前没有这一维度的在线题，不能据此判断不会；原卷引用不算在线题。"
        elif not graded_ids:
            reason = "当前题目缺少可用的可靠判题配置，不把完成记录当成能力确认。"
        else:
            reason = "尚无当前有效的独立正确证据；自评、辅助完成及旧记录不能补充确认。"
        dimensions.append(CapabilityDimension(key=key, label=LABELS[key], status=status,
            status_label=STATUS_LABELS[status], reason=reason,
            evidence_scope="process" if key in PROCESS_KEYS else "final_answer",
            online_question_count=len(pool), reliable_grading_question_count=len(graded_ids),
            independent_question_count=len(independent), independent_question_ids=sorted(independent, key=str),
            pending_review_question_count=len(pending), recent_attempt_count=len(attempts),
            recent_assisted_attempt_count=sum(a.assisted is True for a in attempts),
            recent_ungraded_attempt_count=sum(a.result == "unknown" or a.category == "unable_to_grade" for a in attempts),
            observed_skill_tags=sorted({str(t)[:80] for q in pool if q.id in independent for t in q.skill_tags})[:16]))
    return CapabilityProfile(dimensions=dimensions, history_truncated=history_truncated,
        unmapped_pending_review_count=len(pending_ids - set(mapped)))
