from typing import Literal

from pydantic import BaseModel


class QuestionTrustView(BaseModel):
    question_provenance: Literal["real_exam", "trusted_practice", "ai_generated_practice", "legacy_unknown"] = "legacy_unknown"
    content_trust: Literal["unreviewed", "needs_review", "source_attested", "verified"] = "unreviewed"
    source_status: Literal["verified", "traceable", "needs_review", "unknown", "not_applicable"] = "unknown"
    answer_provenance: Literal["verified_reference", "ai_generated", "legacy_transcription", "unknown"] = "unknown"
    answer_reliability: Literal["verified", "ai_generated_consistent", "ai_disagreement", "model_generated", "unverified", "unknown"] = "unknown"
    mapping_status: str = "unknown"
    source_attestation_current: bool = False
    answer_attestation_current: bool = False
    practice_eligible: bool = False
    grading_capability: Literal["deterministic", "final_answer_limited", "process_review_only", "unsupported"] = "unsupported"
    evidence_capability: str = "self_report_only"
    answer_comparison_method: str | None = None
    verified_grading_method: str | None = None
    blocking_reasons: list[str] = []


class AvailabilityNode(BaseModel):
    kp_id: str
    code: str
    name: str
    subject: str
    path: list[str]
    active_question_count: int
    practice_eligible_count: int
    available_to_append_count: int
    already_in_plan_count: int
    previously_attempted_count: int
    unused_count: int
    reference_count: int
    candidate_count: int | None = None
    candidate_inventory_status: str
    blocking_reasons: dict[str, int] = {}
    question_provenance_counts: dict[str, int] = {}
    answer_provenance_counts: dict[str, int] = {}
    grading_capability_counts: dict[str, int] = {}
    evidence_capability_counts: dict[str, int] = {}
    evidence_pool_status: Literal["SUFFICIENT", "INSUFFICIENT", "UNKNOWN"] = "UNKNOWN"
    evidence_pool_reasons: list[str] = []
    verified_objective_question_count: int = 0
    distinct_objective_question_count: int = 0
    unattempted_objective_question_count: int = 0
    variation_objective_question_count: int = 0


class QuestionAvailabilityView(BaseModel):
    subject: str | None = None
    scope_node_ids: list[str] = []
    excluded_node_ids: list[str] = []
    excluded_question_ids: list[str] = []
    question_type: str | None = None
    current_plan_id: str | None = None
    active_question_count: int
    practice_eligible_count: int
    available_to_append_count: int
    already_in_plan_count: int
    previously_attempted_count: int
    unused_count: int
    reference_count: int
    candidate_count: int | None = None
    candidate_inventory_status: str
    blocked_question_count: int
    blocking_reasons: dict[str, int] = {}
    question_provenance_counts: dict[str, int] = {}
    answer_provenance_counts: dict[str, int] = {}
    grading_capability_counts: dict[str, int] = {}
    evidence_capability_counts: dict[str, int] = {}
    evidence_pool_sufficient_node_count: int = 0
    evidence_pool_insufficient_node_count: int = 0
    evidence_pool_unknown_node_count: int = 0
    eligible_nodes: list[AvailabilityNode] = []
    node_list_truncated: bool = False
    inventory_note: str
