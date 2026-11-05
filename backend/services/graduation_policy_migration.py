"""Deterministic, hash-guarded policy conversion. No ORM writes in this module."""
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json

from backend.mastery.policy import LEGACY_POLICY_FIELDS, VERSIONED_POLICY_FIELDS, MasteryPolicy


def policy_snapshot(row: dict) -> dict:
    return {"kp_id": str(row["kp_id"]), **{k: deepcopy(row.get(k)) for k in LEGACY_POLICY_FIELDS},
        "policy_version": row.get("policy_version", 1),
        "required_question_origins": deepcopy(row.get("required_question_origins") or {})}


def policy_hash(row: dict) -> str:
    return sha256(json.dumps(policy_snapshot(row), ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), default=str).encode()).hexdigest()


def convert_policy(row: dict) -> dict:
    result = policy_snapshot(row)
    quota = result["required_question_types"].pop("external_exam", None)
    if result["policy_version"] != 1 or type(quota) is not int or quota < 1:
        raise ValueError("A positive legacy external_exam quota is required")
    result["policy_version"] = 2
    result["required_question_origins"] = {"real_exam": quota}
    validation = {k:v for k,v in result.items() if k != "kp_id"}
    validation["excluded_question_types"] = frozenset(validation["excluded_question_types"])
    validation["required_skill_tags"] = frozenset(validation["required_skill_tags"])
    validation["review_intervals_days"] = tuple(validation["review_intervals_days"])
    MasteryPolicy(**validation)
    return result


def remove_exam_source_quotas(row: dict) -> dict:
    """Remove hard exam-origin quotas without changing other graduation gates.

    Historical v1 rows sometimes encoded an external-exam count as a
    ``question_type`` quota; v2 rows store the same constraint in
    ``required_question_origins``.  The former is converted to the existing
    distinct-question floor when necessary, so practice quantity is preserved
    while the exam source is no longer mandatory.  Policy/evidence version is
    deliberately unchanged: this is not a receipt-semantic migration.
    """
    result = policy_snapshot(row)
    types = dict(result.get("required_question_types") or {})
    external_exam_count = types.pop("external_exam", 0)
    result["required_question_types"] = types
    result["required_question_origins"] = {}
    if type(external_exam_count) is int and external_exam_count > 0:
        result["min_real_questions"] = max(
            int(result.get("min_real_questions") or 0), external_exam_count
        )
    validation = {k: v for k, v in result.items() if k != "kp_id"}
    validation["excluded_question_types"] = frozenset(validation["excluded_question_types"] or [])
    validation["required_skill_tags"] = frozenset(validation["required_skill_tags"] or [])
    validation["review_intervals_days"] = tuple(validation["review_intervals_days"] or (7, 15, 30))
    MasteryPolicy(**validation)
    return result


def review_policy_guard(row: dict, node: dict | None, reference_count: int,
                        audited: dict, audit_time: datetime) -> dict:
    expected = {"kp_id": audited["node_id"], **audited["before_policy"],
        "policy_version": 1, "required_question_origins": {}}
    target = convert_policy(expected)
    result = {"node_id": str(audited["node_id"]), "node_code": audited["node_code"],
        "old_hash": policy_hash(expected), "current_hash": policy_hash(row) if row else None,
        "expected_new_hash": policy_hash(target), "old_policy_version": 1,
        "new_policy_version": 2, "old_external_exam_quota": expected["required_question_types"]["external_exam"],
        "new_real_exam_quota": target["required_question_origins"]["real_exam"],
        "expected_before": policy_snapshot(expected), "expected_after": target,
        "preserved_fields": [k for k in LEGACY_POLICY_FIELDS if k != "required_question_types"]}
    node_matches = bool(node and all(node.get(current) == audited[previous]
        for current,previous in (("code","node_code"),("name","node_name"),("subject","subject"),
            ("is_active","node_active"),("is_reference_only","reference_only")))
        and str(node["id"]) == str(audited["node_id"]) and node.get("is_assessable"))
    if row and row.get("policy_version", 1) == 2:
        matches = policy_hash(row) == policy_hash(target) and node_matches
        result.update(status="NOOP_ALREADY_MIGRATED" if matches else "POLICY_CHANGED_SINCE_AUDIT",
            reason="already_versioned" if matches else "versioned_hash_mismatch" if node_matches else "node_mapping_changed")
        return result
    if not row or not node_matches or reference_count != audited["reference_count"]:
        result.update(status="POLICY_CHANGED_SINCE_AUDIT", reason="missing_row_or_changed_node_reference_mapping")
        return result
    if policy_hash(row) != policy_hash(expected):
        result.update(status="POLICY_CHANGED_SINCE_AUDIT", reason="canonical_hash_mismatch")
        return result
    modified = row.get("updated_at")
    if isinstance(modified, str):
        modified = datetime.fromisoformat(modified)
    if modified and modified.astimezone(timezone.utc) > audit_time.astimezone(timezone.utc):
        result.update(status="POLICY_CHANGED_SINCE_AUDIT", reason="modified_after_audit")
        return result
    quota = row["required_question_types"].get("external_exam")
    formula_matches = (audited.get("matches_reference_seed_formula") is True
        and (row.get("note") or "").startswith("历年真题索引策略：")
        and quota == min(3, reference_count) and row["min_confirmations"] == quota
        and row["min_real_questions"] == quota and row["required_variant_count"] == 0
        and row["min_day_span"] == min(2, quota-1) and row["required_skill_tags"] == [node["name"]]
        and row.get("required_question_origins", {}) == {})
    result.update(status="ELIGIBLE" if formula_matches else "CUSTOM_OR_NONMATCHING_POLICY",
        reason="exact_audited_seed_policy" if formula_matches else "seed_formula_no_longer_matches")
    return result
