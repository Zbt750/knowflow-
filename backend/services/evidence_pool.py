"""Assess question opportunity separately from the learner's mastery state.

This is an inventory diagnostic, not a graduation policy. It never writes
KpState, changes thresholds, or treats repeated attempts on one item as distinct
question opportunities.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from collections import Counter
from hashlib import sha256
import json
from typing import Iterable


SUFFICIENT = "SUFFICIENT"
INSUFFICIENT = "INSUFFICIENT"
UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class EvidencePoolAssessment:
    status: str
    reasons: tuple[str, ...]
    practice_question_count: int
    verified_objective_question_count: int
    distinct_objective_question_count: int
    unattempted_objective_question_count: int
    variation_objective_question_count: int
    scope: str = "verified_objective_opportunity_v1"

    def public_dict(self) -> dict:
        result = asdict(self)
        result["reasons"] = list(self.reasons)
        return result


def _content_identity(question) -> str:
    payload = {key: getattr(question, key, None) for key in ("question_type", "stem", "options")}
    return sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                              separators=(",", ":"), default=str).encode()).hexdigest()


def _has_ai_answer(eligibility) -> bool:
    value = getattr(eligibility, "answer_provenance", None)
    return isinstance(value, str) and value.lower() == "ai_generated"


def assess_evidence_pool(*, questions: Iterable, eligibility_by_id: dict,
                         attempted_question_ids: set, known: bool = True, policy=None) -> EvidencePoolAssessment:
    """Return whether this node offers a small, credible objective evidence path.

    `SUFFICIENT` requires at least two distinct verified-objective questions, an
    available variant and at least one currently unattempted opportunity. This
    deliberately does not say the learner has mastered the topic and does not
    duplicate or alter the configured graduation thresholds.
    """
    if not known:
        return EvidencePoolAssessment(UNKNOWN, (), 0, 0, 0, 0, 0)

    rows = list(questions)
    practice = [q for q in rows if getattr(eligibility_by_id.get(q.id), "practice_eligible", False)]
    objective = [q for q in practice
                 if getattr(eligibility_by_id.get(q.id), "evidence_capability", None) == "verified_objective"]
    distinct = {_content_identity(q): q for q in objective}
    distinct_rows = list(distinct.values())
    unattempted = [q for q in distinct_rows if q.id not in attempted_question_ids]
    variants = [q for q in distinct_rows if bool(getattr(q, "is_variant", False))]
    versioned = policy is not None and policy.policy_version in {2, 3}
    needed = max(policy.min_confirmations, policy.min_real_questions) if versioned else 2
    variant_quota = policy.required_variant_count if versioned else 1

    reasons: list[str] = []
    if not practice:
        reasons.append("NO_PRACTICE_QUESTION")
    if not objective:
        if any(_has_ai_answer(eligibility_by_id.get(q.id)) for q in rows):
            reasons.append("ANSWER_RELIABILITY_TOO_LOW")
        if rows and not any(
            getattr(eligibility_by_id.get(q.id), "grading_capability", None)
            in {"deterministic", "final_answer_limited"} for q in practice
        ):
            reasons.append("GRADING_UNSUPPORTED")
    if len(distinct_rows) < needed:
        reasons.append("NO_DISTINCT_QUESTION")
    if distinct_rows and len(variants) < variant_quota:
        reasons.append("NO_VARIATION")
    if distinct_rows and not unattempted and not versioned:
        reasons.append("NO_DELAYED_VERIFICATION_OPPORTUNITY")

    # Be explicit when the only usable comparison is model-authored. Such items
    # can still be used for practice, but cannot satisfy this strict opportunity
    # diagnostic for independent objective evidence.
    if practice and not objective and any(_has_ai_answer(eligibility_by_id.get(q.id)) for q in practice) \
            and "ANSWER_RELIABILITY_TOO_LOW" not in reasons:
        reasons.append("ANSWER_RELIABILITY_TOO_LOW")

    required = len(distinct_rows) >= needed and len(variants) >= variant_quota
    if versioned:
        types = Counter(q.question_type for q in distinct_rows)
        tags = {tag for q in distinct_rows for tag in (getattr(q, "skill_tags", None) or [])}
        for kind, quota in policy.required_question_types.items():
            if types[kind] < quota: reasons.append(f"MISSING_REQUIRED_TYPE:{kind}")
        for tag in sorted(policy.required_skill_tags - tags):
            reasons.append(f"MISSING_REQUIRED_SKILL_TAG:{tag}")
        required = required and all(types[k] >= v for k,v in policy.required_question_types.items()) \
            and policy.required_skill_tags.issubset(tags)
    else:
        required = required and bool(unattempted)
    return EvidencePoolAssessment(
        SUFFICIENT if required else INSUFFICIENT,
        tuple(dict.fromkeys(reasons)),
        len(practice), len(objective), len(distinct_rows), len(unattempted), len(variants),
        "configured_policy_objective_opportunity_v2" if versioned else "verified_objective_opportunity_v1",
    )
