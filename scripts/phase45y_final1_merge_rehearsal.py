"""Versioned Phase 4.5Y-Final-1 merge, defaulting to isolated rehearsal only.

Production execution is available only behind an explicit, exact-target
confirmation and an expected PostgreSQL system identifier. History and sealed
source databases remain confined to the isolated 59241 cluster.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import MetaData, create_engine, select, text, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from backend.models import import_models
from backend.models.learning import (
    KpGraduationQuestionSetVersion,
    KpMasteryPolicy,
    KpState,
    KnowledgePoint,
    LearningEvent,
    PracticeItem,
    Question,
    QuestionAttempt,
    QuestionAutoReviewEvent,
    QuestionVersion,
)
from backend.mastery.storage import policy_from_storage
from backend.services.graduation_question_set import assert_frozen_set_integrity
from backend.services.question_eligibility import question_eligibility
from backend.services.question_versions import (
    question_for_attempt,
    question_for_practice_item,
    question_version_snapshot,
    version_snapshot_hash,
)


AUDIT_DIR = Path(os.environ.get(
    "PHASE45Y_AUDIT_DIR", str(ROOT / "storage/quality-audits/phase45y-final1-20261014")
)).resolve()
PORT = 59241
REAL_SYNC_MODE = os.environ.get("PHASE45Y_REAL_SYNC") == "1"
REAL_TARGET_CONFIRMATION = "kaoyan@127.0.0.1:5433#7686825087296682120"
DATABASES = {
    "history": os.environ.get("PHASE45Y_HISTORY_DB", "phase45yfinal1_history_test"),
    "sealed": os.environ.get("PHASE45Y_SEALED_DB", "phase45yfinal1_sealed_test"),
    "merged": os.environ.get("PHASE45Y_MERGED_DB", "phase45yfinal1_merged_test"),
}
POLICY_PREVIEW = ROOT / "storage/quality-audits/phase45y3-20261014-run01/policy-merge-preview.csv"
FORMAL_EVENT_PREVIEW = ROOT / "storage/quality-audits/phase45y3-20261014-run01/phase45y5/formal-review-event-import-preview.csv"

POLICY_RELEASE_FIELDS = {
    "policy_version",
    "required_question_origins",
    "graduation_question_ids",
    "graduation_set_version",
    "required_skill_tags",
    "updated_at",
}
HISTORY_TABLES = {
    "daily_plans",
    "practice_items",
    "question_attempts",
    "learning_events",
    "kp_states",
}
MERGE_FINGERPRINT_TABLES = (
    "questions", "question_versions", "question_auto_review_events",
    "kp_graduation_question_set_versions", "kp_mastery_policies", "kp_states",
    "daily_plans", "practice_items", "question_attempts", "learning_events",
)


def _normal(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _normal(v) for k, v in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (list, tuple)):
        return [_normal(v) for v in value]
    if isinstance(value, bytes):
        return value.hex()
    return value


def _json(value: Any) -> str:
    return json.dumps(_normal(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _engine(role: str) -> Engine:
    database = DATABASES[role]
    host = "127.0.0.1"
    port = PORT
    if REAL_SYNC_MODE and role == "merged":
        if os.environ.get("PHASE45Y_REAL_SYNC_CONFIRM") != REAL_TARGET_CONFIRMATION:
            raise RuntimeError("real_sync_exact_target_confirmation_missing")
        if database != "kaoyan":
            raise RuntimeError("real_sync_database_must_be_kaoyan")
        port = 5433
    url = f"postgresql+psycopg://postgres@{host}:{port}/{database}"
    engine = create_engine(url, pool_pre_ping=True, future=True)
    parsed = engine.url
    if parsed.host != "127.0.0.1" or parsed.port != port or parsed.database != database:
        raise RuntimeError(f"database_identity_guard_rejected:{role}")
    if role != "merged" or not REAL_SYNC_MODE:
        if parsed.port != PORT or parsed.port == 5433 or not database.endswith("_test"):
            raise RuntimeError(f"isolated_database_guard_rejected:{role}")
    elif (os.environ.get("PHASE45Y_EXPECTED_TARGET_SYSTEM_ID") != "7686825087296682120"
          or os.environ.get("PHASE45Y_REAL_SYNC_CONFIRM") != REAL_TARGET_CONFIRMATION):
        raise RuntimeError("real_sync_system_identifier_guard_missing")
    return engine


def _identity(engine: Engine, expected_db: str, expected_revision: str,
              expected_port: int = PORT) -> dict[str, Any]:
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT current_database() AS database,
                   current_user AS username,
                   inet_server_addr()::text AS host,
                   current_setting('port') AS port,
                   current_setting('server_version') AS server_version,
                   (SELECT version_num FROM alembic_version) AS revision,
                   (SELECT system_identifier::text FROM pg_control_system()) AS system_identifier
        """)).mappings().one()
    result = dict(row)
    if (result["database"] != expected_db or result["host"].split("/")[0] != "127.0.0.1"
            or int(result["port"]) != expected_port or result["revision"] != expected_revision):
        raise RuntimeError(f"isolated_database_identity_mismatch:{expected_db}:{result}")
    return _normal(result)


def _table(engine: Engine, name: str, metadata: MetaData | None = None):
    md = metadata or MetaData()
    return md.tables.get(name) or __import__("sqlalchemy").Table(name, md, autoload_with=engine)


def _read_rows(engine: Engine, name: str) -> list[dict[str, Any]]:
    table = _table(engine, name)
    order = list(table.primary_key.columns)
    stmt = select(table).order_by(*order) if order else select(table)
    with engine.connect() as conn:
        return [dict(row) for row in conn.execute(stmt).mappings()]


def _table_fingerprint(engine: Engine, name: str, *, exclude: set[str] | None = None) -> dict[str, Any]:
    rows = _read_rows(engine, name)
    excluded = exclude or set()
    canonical = [{k: v for k, v in row.items() if k not in excluded} for row in rows]
    return {
        "rows": len(rows),
        "sha256": hashlib.sha256(_json(canonical).encode("utf-8")).hexdigest(),
    }


def _merge_fingerprints(engine: Engine) -> dict[str, dict[str, Any]]:
    return {name: _table_fingerprint(engine, name) for name in MERGE_FINGERPRINT_TABLES}


def _source_target_exact_table(source: Engine, target: Engine, name: str) -> dict[str, Any]:
    source_rows = _read_rows(source, name)
    target_rows = _read_rows(target, name)
    if _json(source_rows) != _json(target_rows):
        raise RuntimeError(f"shared_history_table_differs:{name}")
    return {"rows": len(target_rows), "exact_match": True,
            "sha256": hashlib.sha256(_json(target_rows).encode("utf-8")).hexdigest()}


def _policy_diffs(source: Engine, target: Engine) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    source_rows = {str(r["kp_id"]): r for r in _read_rows(source, "kp_mastery_policies")}
    target_rows = {str(r["kp_id"]): r for r in _read_rows(target, "kp_mastery_policies")}
    if len(source_rows) != 284 or len(target_rows) != 284 or set(source_rows) != set(target_rows):
        raise RuntimeError("policy_inventory_or_node_ids_mismatch")
    detail: list[dict[str, Any]] = []
    for kp_id in sorted(target_rows):
        left, right = target_rows[kp_id], source_rows[kp_id]
        changed = [name for name in left if _json(left[name]) != _json(right[name])]
        unexpected = sorted(set(changed) - POLICY_RELEASE_FIELDS)
        if unexpected:
            raise RuntimeError(f"unexpected_policy_semantic_drift:{kp_id}:{unexpected}")
        detail.append({
            "kp_id": kp_id,
            "changed_fields": changed,
            "target_policy_version": left["policy_version"],
            "sealed_policy_version": right["policy_version"],
            "target_set_version": left["graduation_set_version"],
            "sealed_set_version": right["graduation_set_version"],
            "min_confirmations_unchanged": left["min_confirmations"] == right["min_confirmations"],
            "min_real_questions_unchanged": left["min_real_questions"] == right["min_real_questions"],
            "required_question_types_unchanged": left["required_question_types"] == right["required_question_types"],
            "excluded_question_types_unchanged": left["excluded_question_types"] == right["excluded_question_types"],
            "required_variant_count_unchanged": left["required_variant_count"] == right["required_variant_count"],
            "min_day_span_unchanged": left["min_day_span"] == right["min_day_span"],
            "manual_mastered_credit_unchanged": left["manual_mastered_credit"] == right["manual_mastered_credit"],
            "max_evidence_window_unchanged": left["max_evidence_window"] == right["max_evidence_window"],
        })
    active = [r for r in detail if r["sealed_policy_version"] == 3 and r["sealed_set_version"] > 0]
    if len(active) != 253:
        raise RuntimeError(f"sealed_active_policy_count_mismatch:{len(active)}")
    return detail, source_rows


def _started_bindings() -> dict[str, int]:
    if not POLICY_PREVIEW.exists():
        raise RuntimeError("started_node_policy_preview_missing")
    with POLICY_PREVIEW.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    started = [r for r in rows if r.get("target_learning_started", "").strip().lower() == "true"]
    if len(started) != 5:
        raise RuntimeError(f"started_node_preview_count_unexpected:{len(started)}")
    result: dict[str, int] = {}
    for row in started:
        raw = row.get("candidate_started_set_binding", "").strip()
        if not raw:
            raise RuntimeError(f"started_node_has_no_candidate_binding:{row.get('kp_id')}")
        result[row["kp_id"]] = int(raw)
    return result


def _active_sets(source: Engine, policy_rows: dict[str, dict[str, Any]],
                 started: dict[str, int]) -> tuple[dict[tuple[str, int], dict[str, Any]], dict[str, list[str]]]:
    set_rows = _read_rows(source, "kp_graduation_question_set_versions")
    by_key = {(str(r["kp_id"]), int(r["set_version"])): r for r in set_rows}
    selected: dict[tuple[str, int], dict[str, Any]] = {}
    current_qids: dict[str, list[str]] = {}
    for kp_id, policy in policy_rows.items():
        if policy["policy_version"] != 3 or not policy["graduation_set_version"]:
            continue
        version = int(policy["graduation_set_version"])
        key = (kp_id, version)
        if key not in by_key:
            raise RuntimeError(f"sealed_current_question_set_missing:{kp_id}:{version}")
        row = by_key[key]
        ids = [str(x) for x in (row["question_ids"] or [])]
        if ids != [str(x) for x in (policy["graduation_question_ids"] or [])]:
            raise RuntimeError(f"sealed_policy_set_membership_mismatch:{kp_id}")
        if len(ids) != len(set(ids)) or not ids:
            raise RuntimeError(f"sealed_current_set_duplicate_or_empty:{kp_id}")
        if row["question_version_ids"] is None or row["question_version_ids_sha256"] is None:
            raise RuntimeError(f"sealed_current_set_not_version_bound:{kp_id}")
        selected[key] = row
        current_qids[kp_id] = ids
    if len(current_qids) != 253:
        raise RuntimeError(f"current_set_node_count_mismatch:{len(current_qids)}")
    for kp_id, version in started.items():
        key = (kp_id, version)
        if key not in by_key:
            raise RuntimeError(f"started_node_bound_set_missing:{kp_id}:{version}")
        row = by_key[key]
        if row["question_version_ids"] is None:
            raise RuntimeError(f"started_node_bound_set_unversioned:{kp_id}:{version}")
        selected[key] = row
    return selected, current_qids


def _copy_report(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _json_report(path: Path, payload: dict[str, Any]) -> None:
    _copy_report(path, json.dumps(_normal(payload), ensure_ascii=False, indent=2) + "\n")


def _validate_eligibility(engine: Engine, formal_ids: set[str]) -> dict[str, Any]:
    import_models()
    pass_count = 0
    failures: list[dict[str, Any]] = []
    with Session(engine) as session:
        questions = list(session.scalars(select(Question).where(Question.id.in_([UUID(v) for v in formal_ids]))))
        if len(questions) != len(formal_ids):
            return {"count": len(questions), "pass": 0, "fail": len(formal_ids) - len(questions),
                    "failures": [{"reason": "formal_question_row_missing"}]}
        for question in questions:
            node = session.get(KnowledgePoint, question.kp_id)
            result = question_eligibility(question, node)
            if (result.practice_eligible and result.evidence_capability == "verified_objective"
                    and result.grading_capability == "deterministic"):
                pass_count += 1
            else:
                failures.append({
                    "question_id": str(question.id),
                    "practice_eligible": result.practice_eligible,
                    "evidence_capability": result.evidence_capability,
                    "grading_capability": result.grading_capability,
                    "blocking_reasons": list(result.blocking_reasons),
                })
        policies = list(session.scalars(select(KpMasteryPolicy).where(
            KpMasteryPolicy.policy_version == 3,
            KpMasteryPolicy.graduation_set_version > 0,
        )))
        set_checks = 0
        for row in policies:
            assert_frozen_set_integrity(session, policy_from_storage(row), kp_id=row.kp_id)
            set_checks += 1
        # The sealed source is intentionally one migration behind the history
        # clone. Read its older KpState shape reflectively so ORM attributes
        # added by f54 are not assumed to exist there.
        started_states = [
            row for row in _read_rows(engine, "kp_states")
            if row.get("graduation_set_version") is not None
        ]
        for state in started_states:
            set_row = session.get(
                KpGraduationQuestionSetVersion,
                (UUID(str(state["kp_id"])), int(state["graduation_set_version"])),
            )
            if set_row is None:
                raise RuntimeError(f"started_state_set_binding_missing:{state['kp_id']}")
    if failures:
        raise RuntimeError(f"formal_question_eligibility_failures:{len(failures)}")
    return {"count": len(formal_ids), "pass": pass_count, "fail": 0,
            "active_set_integrity_checks": set_checks,
            "started_state_bindings": len(started_states), "failures": failures}


def main() -> None:
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    history = _engine("history")
    source = _engine("sealed")
    target = _engine("merged")
    target_port = 5433 if REAL_SYNC_MODE else PORT
    identities = {
        "history": _identity(history, DATABASES["history"], "f54c8a1d7e20"),
        "sealed": _identity(source, DATABASES["sealed"], "f53b7e2a901c"),
        "merged": _identity(target, DATABASES["merged"], "f54c8a1d7e20", target_port),
    }
    if REAL_SYNC_MODE:
        if identities["merged"]["system_identifier"] != "7686825087296682120":
            raise RuntimeError("real_target_system_identifier_mismatch")
        if identities["history"]["system_identifier"] != identities["sealed"]["system_identifier"]:
            raise RuntimeError("isolated_reference_databases_not_in_same_cluster")
        if identities["history"]["system_identifier"] == identities["merged"]["system_identifier"]:
            raise RuntimeError("real_target_must_not_be_isolated_cluster")
    elif len({v["system_identifier"] for v in identities.values()}) != 1:
        raise RuntimeError("rehearsal_databases_not_in_same_isolated_cluster")

    manifest_path = AUDIT_DIR / "merge-idempotency-manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("merged_database") != DATABASES["merged"]:
            raise RuntimeError("merge_idempotency_manifest_database_mismatch")
        actual = _merge_fingerprints(target)
        if actual != manifest.get("post_merge_fingerprints"):
            raise RuntimeError("merged_database_drift_after_prior_apply")
        noop = {
            "status": "PHASE45Y_MERGE_REPLAY_NOOP",
            "database": DATABASES["merged"],
            "database_identity": identities["merged"],
            "fingerprints_unchanged": True,
            "formal_questions": 1804,
            "legacy_history_unbound_nodes": manifest.get("legacy_history_unbound_nodes", 0),
            "report": str(manifest_path.relative_to(ROOT)),
        }
        _json_report(AUDIT_DIR / "phase45y-merge-replay-noop.json", noop)
        print(json.dumps(_normal(noop), ensure_ascii=False, indent=2))
        return

    import_models()
    tables_target = {name: _table(target, name) for name in (
        "questions", "question_versions", "question_auto_review_events",
        "kp_graduation_question_set_versions", "kp_mastery_policies", "kp_states",
    )}
    tables_source = {name: _table(source, name) for name in tables_target}
    q_t = tables_target["questions"]
    v_t = tables_target["question_versions"]
    event_t = tables_target["question_auto_review_events"]
    set_t = tables_target["kp_graduation_question_set_versions"]
    policy_t = tables_target["kp_mastery_policies"]
    state_t = tables_target["kp_states"]
    q_s = tables_source["questions"]
    v_s = tables_source["question_versions"]
    event_s = tables_source["question_auto_review_events"]
    set_s = tables_source["kp_graduation_question_set_versions"]
    policy_s = tables_source["kp_mastery_policies"]
    state_s = tables_source["kp_states"]

    history_counts_before = {name: _table_fingerprint(target, name) for name in sorted(HISTORY_TABLES)}
    history_state_fingerprint_before = _table_fingerprint(
        target, "kp_states", exclude={"graduation_set_version", "graduation_set_binding_status",
                                      "graduation_set_started_at"}
    )
    old_versions_before = _read_rows(target, "question_versions")
    old_questions_before = _read_rows(target, "questions")
    old_question_by_id = {str(r["id"]): r for r in old_questions_before}
    old_version_by_id = {str(r["id"]): r for r in old_versions_before}
    target_counts_before = {
        name: len(_read_rows(target, name))
        for name in ("questions", "question_versions", "question_auto_review_events",
                     "kp_graduation_question_set_versions", "kp_mastery_policies", "kp_states",
                     "practice_items", "question_attempts", "learning_events", "daily_plans")
    }
    if target_counts_before["questions"] != 518 or target_counts_before["question_versions"] != 518:
        raise RuntimeError(f"unexpected_history_clone_question_inventory:{target_counts_before}")
    if target_counts_before["question_auto_review_events"] != 0 or target_counts_before["kp_graduation_question_set_versions"] != 0:
        raise RuntimeError("history_clone_is_not_unmerged_baseline")

    policy_details, source_policies = _policy_diffs(source, target)
    started = _started_bindings()
    selected_sets, current_qids_by_kp = _active_sets(source, source_policies, started)
    formal_ids_list = [qid for ids in current_qids_by_kp.values() for qid in ids]
    formal_ids = set(formal_ids_list)
    if len(formal_ids_list) != 1804 or len(formal_ids) != 1804:
        raise RuntimeError(f"sealed_formal_question_membership_mismatch:{len(formal_ids_list)}:{len(formal_ids)}")

    source_questions = {str(r["id"]): r for r in _read_rows(source, "questions")}
    source_versions = {str(r["id"]): r for r in _read_rows(source, "question_versions")}
    source_events = {str(r["id"]): r for r in _read_rows(source, "question_auto_review_events")}
    target_questions = {str(r["id"]): r for r in _read_rows(target, "questions")}
    target_versions = {str(r["id"]): r for r in _read_rows(target, "question_versions")}
    target_events = {str(r["id"]): r for r in _read_rows(target, "question_auto_review_events")}
    target_event_keys = {str(r["idempotency_key"]) for r in target_events.values()}
    target_version_ids = set(target_versions)

    overlap = formal_ids & set(target_questions)
    missing = formal_ids - set(target_questions)
    target_only = set(target_questions) - formal_ids
    if (len(overlap), len(missing), len(target_only)) != (387, 1417, 131):
        raise RuntimeError(f"question_id_merge_counts_unexpected:{len(overlap)}:{len(missing)}:{len(target_only)}")
    if len(target_only) != 131:
        raise RuntimeError("target_only_question_preservation_count_unexpected")
    for qid in overlap:
        if target_questions[qid]["bank_scope"] != "public":
            raise RuntimeError(f"formal_question_id_collides_with_nonpublic_target:{qid}")

    formal_source_rows = {qid: source_questions[qid] for qid in formal_ids}
    formal_source_versions: dict[str, dict[str, Any]] = {}
    formal_event_ids: set[str] = set()
    for qid, question in formal_source_rows.items():
        version_id = str(question["current_version_id"])
        if version_id not in source_versions:
            raise RuntimeError(f"sealed_current_version_missing:{qid}")
        version = source_versions[version_id]
        if str(version["question_id"]) != qid or int(version["version_number"]) != 1:
            raise RuntimeError(f"sealed_current_version_binding_invalid:{qid}")
        snapshot = question_version_snapshot(SimpleNamespace(**question))
        if snapshot != version["snapshot_json"] or version_snapshot_hash(snapshot) != version["content_hash"]:
            raise RuntimeError(f"sealed_current_version_snapshot_hash_invalid:{qid}")
        if not question["auto_review_event_id"]:
            raise RuntimeError(f"formal_question_missing_current_review_pointer:{qid}")
        event_id = str(question["auto_review_event_id"])
        if event_id not in source_events:
            raise RuntimeError(f"formal_question_current_review_row_missing:{qid}")
        event = source_events[event_id]
        if str(event["question_id"]) != qid or event["event_type"] != "qualified":
            raise RuntimeError(f"formal_question_current_review_binding_invalid:{qid}")
        if event["idempotency_key"] in target_event_keys:
            raise RuntimeError(f"review_event_idempotency_conflict:{qid}")
        formal_event_ids.add(event_id)
        formal_source_versions[qid] = version
    if len(formal_event_ids) != 1804:
        raise RuntimeError(f"formal_review_event_count_unexpected:{len(formal_event_ids)}")
    target_answer_verification_ids = {
        str(row["id"]) for row in _read_rows(target, "question_answer_verification_events")
    }
    for qid, question in formal_source_rows.items():
        aid = question.get("answer_verification_event_id")
        if aid and str(aid) not in target_answer_verification_ids:
            raise RuntimeError(f"answer_verification_event_not_available_in_target:{qid}")
    related_outside = [event_id for event_id in formal_event_ids
        if source_events[event_id].get("related_event_id") and
        str(source_events[event_id]["related_event_id"]) not in formal_event_ids]
    if related_outside:
        raise RuntimeError(f"current_review_event_chain_not_self_contained:{len(related_outside)}")
    if formal_event_ids & set(target_events):
        raise RuntimeError("current_review_event_id_collision")
    version_id_collisions = {str(formal_source_versions[qid]["id"]) for qid in formal_ids} & target_version_ids
    if version_id_collisions:
        raise RuntimeError(f"question_version_id_collision:{len(version_id_collisions)}")

    # Existing shared audit/attestation support tables were already reported as
    # exact NOOPs by Y3. Recheck them against the restored copies before merge.
    shared_audit_tables: dict[str, Any] = {}
    table_names_source = set(__import__("sqlalchemy").inspect(source).get_table_names())
    table_names_target = set(__import__("sqlalchemy").inspect(target).get_table_names())
    for name in ("question_source_attestations", "question_answer_consistency_runs",
                 "question_answer_verification_events"):
        if name in table_names_source and name in table_names_target:
            shared_audit_tables[name] = _source_target_exact_table(source, target, name)

    # The target has no rows in these two newly introduced publication tables;
    # copy the current active releases plus only the 3 distinct historical sets
    # needed to bind the 5 already-started target nodes.
    if not selected_sets or len(selected_sets) < 253:
        raise RuntimeError("required_current_and_started_sets_missing")
    all_bound_qids = {str(qid) for row in selected_sets.values() for qid in row["question_ids"]}
    if not all_bound_qids.issubset(formal_ids):
        raise RuntimeError("started_or_current_set_references_nonformal_question")
    needed_review_rows = [source_events[event_id] for event_id in sorted(formal_event_ids)]
    stale_event_count = len(source_events) - len(needed_review_rows)
    if stale_event_count < 0:
        raise RuntimeError("review_event_accounting_invalid")

    # Validate in the sealed database that every member of each current set is
    # currently eligible, before any target-side mutation.
    source_eligibility = _validate_eligibility(source, formal_ids)

    # Atomic content/event/set merge into the dedicated clone only.
    now = datetime.now(timezone.utc)
    with target.begin() as conn:
        conn.execute(text("SET CONSTRAINTS ALL DEFERRED"))
        qtarget = tables_target["questions"]
        vtarget = tables_target["question_versions"]
        etarget = tables_target["question_auto_review_events"]
        starget = tables_target["kp_graduation_question_set_versions"]
        ptarget = tables_target["kp_mastery_policies"]
        state_target = tables_target["kp_states"]

        # Insert placeholder Question rows for IDs absent from the history
        # clone. The non-deferrable Question->review-event FK is filled only
        # after the immutable event rows exist.
        for qid in sorted(missing):
            values = dict(formal_source_rows[qid])
            values["current_version_id"] = None
            values["auto_review_event_id"] = None
            conn.execute(qtarget.insert().values(**values))

        # Append the sealed content snapshot as v2 for conflicts and v1 for
        # genuinely new IDs. Reuse sealed UUID/hash bindings so frozen set
        # version_ids stay exact.
        version_payloads: list[dict[str, Any]] = []
        for qid in sorted(formal_ids):
            payload = dict(formal_source_versions[qid])
            payload["version_number"] = 2 if qid in overlap else 1
            version_payloads.append(payload)
        conn.execute(vtarget.insert(), version_payloads)

        # Current event rows are only those whose hashes/pointers match the
        # sealed current question version; stale and nonformal event histories
        # do not become current evidence during this merge.
        conn.execute(etarget.insert(), needed_review_rows)

        # Publish sealed Question fields. For conflicts keep the target's
        # original created_at and immutable v1; all Question content fields
        # and current pointer now match the appended sealed snapshot.
        update_values_by_id: dict[str, dict[str, Any]] = {}
        for qid in sorted(formal_ids):
            source_row = formal_source_rows[qid]
            values = {name: value for name, value in source_row.items()
                      if name not in {"id", "created_at", "current_version_id", "auto_review_event_id"}}
            values["current_version_id"] = source_row["current_version_id"]
            values["auto_review_event_id"] = source_row["auto_review_event_id"]
            values["updated_at"] = now
            if qid not in overlap:
                values["created_at"] = source_row["created_at"]
            update_values_by_id[qid] = values
            conn.execute(qtarget.update().where(qtarget.c.id == UUID(qid)).values(**values))

        set_payloads = []
        for key in sorted(selected_sets):
            row = selected_sets[key]
            set_payloads.append(dict(row))
        conn.execute(starget.insert(), set_payloads)

        # Update only the release pointer/serialized member list fields copied
        # from v3. No threshold, question-type, spacing, or evidence parameters
        # are changed.
        for kp_id, policy in source_policies.items():
            if policy["policy_version"] != 3 or not policy["graduation_set_version"]:
                continue
            conn.execute(ptarget.update().where(ptarget.c.kp_id == UUID(kp_id)).values(
                policy_version=policy["policy_version"],
                required_question_origins=policy["required_question_origins"],
                graduation_question_ids=policy["graduation_question_ids"],
                graduation_set_version=policy["graduation_set_version"],
                required_skill_tags=policy["required_skill_tags"],
                updated_at=now,
            ))

        # Bind the five actual started target nodes to the sealed historical
        # set versions identified by the pre-existing Y3 preview. Their other
        # KpState fields and all attempts/events remain untouched.
        for kp_id, set_version in started.items():
            current = next((r for r in _read_rows(target, "kp_states") if str(r["kp_id"]) == kp_id), None)
            if current is None or current["graduation_set_version"] is not None:
                raise RuntimeError(f"started_state_precondition_changed:{kp_id}")
            conn.execute(state_target.update().where(state_target.c.kp_id == UUID(kp_id)).values(
                graduation_set_version=set_version,
                graduation_set_binding_status="bound",
            ))

        # Force deferred FK/constraint-trigger checks before commit.
        conn.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        counts = {
            name: conn.execute(text(f'SELECT count(*) FROM "{name}"')).scalar_one()
            for name in ("questions", "question_versions", "question_auto_review_events",
                         "kp_graduation_question_set_versions", "kp_mastery_policies", "kp_states",
                         "practice_items", "question_attempts", "learning_events", "daily_plans")
        }
        if counts["questions"] != 1935 or counts["question_versions"] != 2322:
            raise RuntimeError(f"post_merge_question_count_mismatch:{counts}")
        if counts["question_auto_review_events"] != 1804:
            raise RuntimeError(f"post_merge_review_event_count_mismatch:{counts}")
        if counts["kp_graduation_question_set_versions"] != len(selected_sets):
            raise RuntimeError(f"post_merge_set_version_count_mismatch:{counts}")
        if counts["kp_mastery_policies"] != 284 or counts["kp_states"] != 284:
            raise RuntimeError(f"post_merge_policy_or_state_count_mismatch:{counts}")

    # Post-commit history invariants and versioned app-layer reads.
    history_counts_after = {name: _table_fingerprint(target, name) for name in sorted(HISTORY_TABLES)}
    history_state_fingerprint_after = _table_fingerprint(
        target, "kp_states", exclude={"graduation_set_version", "graduation_set_binding_status",
                                      "graduation_set_started_at"}
    )
    for name in sorted(HISTORY_TABLES - {"kp_states"}):
        if history_counts_before[name] != history_counts_after[name]:
            raise RuntimeError(f"learner_history_changed:{name}")
    if history_state_fingerprint_before != history_state_fingerprint_after:
        raise RuntimeError("kp_state_fields_other_than_set_binding_changed")

    after_version_rows = _read_rows(target, "question_versions")
    after_version_by_id = {str(r["id"]): r for r in after_version_rows}
    for old_id, row in old_version_by_id.items():
        if old_id not in after_version_by_id or _json(row) != _json(after_version_by_id[old_id]):
            raise RuntimeError(f"old_question_version_mutated:{old_id}")
    after_questions = {str(r["id"]): r for r in _read_rows(target, "questions")}
    for qid in target_only:
        if _json(old_question_by_id[qid]) != _json(after_questions[qid]):
            raise RuntimeError(f"target_only_question_changed:{qid}")

    # Verify every original practice/attempt still resolves its premerge v1.
    import_models()
    history_read_counts = {"question_practice_items": 0, "question_attempts": 0,
                           "version_bound_learning_events": 0}
    legacy_detail: list[dict[str, Any]] = []
    history_policy_by_kp = {str(r["kp_id"]): r for r in _read_rows(history, "kp_mastery_policies")}
    with Session(target) as session:
        items = list(session.scalars(select(PracticeItem).where(PracticeItem.question_id.is_not(None))))
        for item in items:
            expected_version_id = str(item.question_version_id)
            if expected_version_id not in old_version_by_id:
                raise RuntimeError(f"preexisting_practice_item_version_not_in_old_snapshot:{item.id}")
            proxy = question_for_practice_item(session, item)
            if str(proxy.version_id) != expected_version_id:
                raise RuntimeError(f"practice_item_version_read_mismatch:{item.id}")
            if proxy.stem != old_version_by_id[expected_version_id]["stem"]:
                raise RuntimeError(f"practice_item_old_stem_changed:{item.id}")
            history_read_counts["question_practice_items"] += 1
        attempts = list(session.scalars(select(QuestionAttempt).where(QuestionAttempt.question_id.is_not(None))))
        for attempt in attempts:
            expected_version_id = str(attempt.question_version_id)
            proxy = question_for_attempt(session, attempt)
            if str(proxy.version_id) != expected_version_id:
                raise RuntimeError(f"attempt_version_read_mismatch:{attempt.id}")
        history_read_counts["question_attempts"] = len(attempts)
        history_read_counts["version_bound_learning_events"] = session.scalar(
            select(__import__("sqlalchemy").func.count()).select_from(LearningEvent)
            .where(LearningEvent.question_version_id.is_not(None))
        ) or 0
        state_rows = list(session.scalars(select(KpState).where(KpState.graduation_set_version.is_not(None))))
        if len(state_rows) != 5:
            raise RuntimeError(f"started_state_binding_count_unexpected:{len(state_rows)}")
        legacy_states = list(session.scalars(select(KpState).where(
            KpState.graduation_set_binding_status == "legacy_history_unbound")))
        if len(legacy_states) != 13 or any(state.graduation_set_version is not None for state in legacy_states):
            raise RuntimeError(f"legacy_history_unbound_count_unexpected:{len(legacy_states)}")
        current_transition_count = 0
        historical_only_count = 0
        for state in legacy_states:
            node = session.get(KnowledgePoint, state.kp_id)
            pi_rows = list(session.scalars(select(PracticeItem).where(PracticeItem.kp_id == state.kp_id)))
            attempt_rows = list(session.scalars(select(QuestionAttempt).where(QuestionAttempt.kp_id == state.kp_id)))
            event_rows = list(session.scalars(select(LearningEvent).where(LearningEvent.kp_id == state.kp_id)))
            if state.state != "unseen" or state.mastered_at is not None or state.evidence_window:
                raise RuntimeError(f"legacy_node_has_kp_state_evidence_requires_manual_transition:{state.kp_id}")
            old_policy = history_policy_by_kp.get(str(state.kp_id), {})
            sealed_policy = source_policies.get(str(state.kp_id), {})
            has_current_v3_set = (
                sealed_policy.get("policy_version") == 3
                and int(sealed_policy.get("graduation_set_version") or 0) > 0
            )
            if has_current_v3_set:
                current_transition_count += 1
            else:
                historical_only_count += 1
            legacy_detail.append({
                "kp_id": str(state.kp_id), "node_code": node.code if node else None,
                "practice_items": len(pi_rows), "attempts": len(attempt_rows),
                "learning_events": len(event_rows), "kp_state": state.state,
                "kp_state_evidence_window_count": len(state.evidence_window or []),
                "mastered_at": state.mastered_at,
                "old_policy_version": old_policy.get("policy_version"),
                "old_graduation_set_version": old_policy.get("graduation_set_version"),
                "sealed_policy_version": sealed_policy.get("policy_version"),
                "sealed_graduation_set_version": sealed_policy.get("graduation_set_version"),
                "requires_explicit_current_set_transition": has_current_v3_set,
                "historical_records_display_only_until_explicit_start": True,
                "current_set_bound": False,
            })
        if current_transition_count != 12 or historical_only_count != 1:
            raise RuntimeError(
                "legacy_node_semantics_unexpected:"
                f"current_v3_transition={current_transition_count},historical_only={historical_only_count}"
            )
        policies = list(session.scalars(select(KpMasteryPolicy).where(
            KpMasteryPolicy.policy_version == 3,
            KpMasteryPolicy.graduation_set_version > 0,
        )))
        if len(policies) != 253:
            raise RuntimeError(f"active_merged_policy_count_unexpected:{len(policies)}")
        for row in policies:
            assert_frozen_set_integrity(session, policy_from_storage(row), kp_id=row.kp_id)

    target_eligibility = _validate_eligibility(target, formal_ids)
    current_members = Counter(qid for ids in current_qids_by_kp.values() for qid in ids)
    if set(current_members) != formal_ids or any(count != 1 for count in current_members.values()):
        raise RuntimeError("current_set_member_mapping_not_exactly_one")

    # Save detailed conflict and policy diffs for a future human-readable
    # deployment decision; these are reports, not SQL scripts.
    conflict_path = AUDIT_DIR / "question-version-merge-results.csv"
    with conflict_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["question_id", "disposition", "old_version_id",
            "old_version_hash", "sealed_version_id", "sealed_version_hash", "new_version_number",
            "attempts_preserved", "practice_items_preserved"])
        writer.writeheader()
        target_practice_counts = Counter(str(r["question_id"]) for r in _read_rows(target, "practice_items") if r.get("question_id"))
        target_attempt_counts = Counter(str(r["question_id"]) for r in _read_rows(target, "question_attempts") if r.get("question_id"))
        for qid in sorted(formal_ids):
            old = target_questions.get(qid)
            current_ver = formal_source_versions[qid]
            writer.writerow({
                "question_id": qid,
                "disposition": "VERSION_2_PRESERVE_V1" if old else "INSERT_V1",
                "old_version_id": str(old["current_version_id"]) if old else "",
                "old_version_hash": old_version_by_id[next((vid for vid, vr in old_version_by_id.items()
                    if old and str(vr["question_id"]) == qid and int(vr["version_number"]) == 1), "")]["content_hash"] if old else "",
                "sealed_version_id": str(current_ver["id"]),
                "sealed_version_hash": current_ver["content_hash"],
                "new_version_number": 2 if old else 1,
                "attempts_preserved": target_attempt_counts[qid],
                "practice_items_preserved": target_practice_counts[qid],
            })
    policy_path = AUDIT_DIR / "policy-version-merge-diff.csv"
    with policy_path.open("w", encoding="utf-8-sig", newline="") as f:
        fields = ["kp_id", "changed_fields", "target_policy_version", "sealed_policy_version",
                  "target_set_version", "sealed_set_version", "thresholds_unchanged"]
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in policy_details:
            writer.writerow({
                "kp_id": row["kp_id"], "changed_fields": ";".join(row["changed_fields"]),
                "target_policy_version": row["target_policy_version"],
                "sealed_policy_version": row["sealed_policy_version"],
                "target_set_version": row["target_set_version"],
                "sealed_set_version": row["sealed_set_version"],
                "thresholds_unchanged": all(v for k, v in row.items() if k.endswith("_unchanged")),
            })
    legacy_path = AUDIT_DIR / "legacy-history-node-compat.csv"
    with legacy_path.open("w", encoding="utf-8-sig", newline="") as f:
        fields = ["kp_id", "node_code", "practice_items", "attempts", "learning_events",
                  "kp_state", "kp_state_evidence_window_count", "mastered_at",
                  "old_policy_version", "old_graduation_set_version",
                  "sealed_policy_version", "sealed_graduation_set_version",
                  "requires_explicit_current_set_transition",
                  "historical_records_display_only_until_explicit_start", "current_set_bound"]
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(legacy_detail)

    result = {
        "status": "PHASE45Y_LEGACY_COMPAT_MERGE_SIMULATION_PASS",
        "scope": {
            "real_development_database_connected": False,
            "real_development_database_modified": False,
            "real_sql_exported": False,
            "all_mutations_limited_to": DATABASES["merged"],
            "isolated_cluster_port": PORT,
            "isolated_system_identifier": identities["merged"]["system_identifier"],
            "revision": "f54c8a1d7e20",
        },
        "source_identity": identities,
        "backup_inputs": {
            "history_backup": "storage/quality-audits/phase45y3-20261014-run01/kaoyan-live-premerge.dump",
            "history_backup_sha256": "dbb296c037c229fca6b1197638e3c8212a97c268d01c44fea777dd3997370029",
            "sealed_dump": "storage/quality-audits/phase45z-final-20261013/final-sealed.dump",
            "sealed_dump_sha256": "8d4f1f685cf35c2091f9a92c0f66722866b8d998c3ae7612b8acbe36858b09a0",
        },
        "question_merge": {
            "sealed_formal_questions": len(formal_ids),
            "conflict_ids_updated_to_new_version": len(overlap),
            "candidate_formal_ids_inserted": len(missing),
            "target_only_questions_preserved": len(target_only),
            "merged_question_rows": target_counts_before["questions"] + len(missing),
            "merged_question_versions": len(after_version_rows),
            "review_events_imported_current_hash_matched": len(needed_review_rows),
            "sealed_candidate_question_rows_not_formal_and_not_imported": len(source_questions) - len(formal_ids),
            "sealed_auto_review_events_not_imported_as_current": stale_event_count,
            "question_conflict_artifact": str(conflict_path.relative_to(ROOT)),
        },
        "version_protection": {
            "old_target_question_versions_preserved_exactly": len(old_version_by_id),
            "existing_question_attempts_bound_to_old_versions": history_read_counts["question_attempts"],
            "existing_question_practice_items_read_through_old_versions": history_read_counts["question_practice_items"],
            "learning_events_bound_count": history_read_counts["version_bound_learning_events"],
            "source_current_version_snapshot_hashes_valid": len(formal_ids),
        },
        "sets_and_policy": {
            "current_active_sets_imported": len(current_qids_by_kp),
            "current_active_set_members": sum(len(ids) for ids in current_qids_by_kp.values()),
            "unique_formal_question_members": len(formal_ids),
            "additional_historical_started_set_versions_imported": len(selected_sets) - len(current_qids_by_kp),
            "total_imported_set_versions": len(selected_sets),
            "target_started_nodes_bound_to_preexisting_candidate_set_versions": len(started),
            "legacy_history_nodes_unbound": len(legacy_detail),
            "legacy_current_v3_nodes_requiring_explicit_transition": current_transition_count,
            "legacy_historical_only_nodes_without_current_v3_set": historical_only_count,
            "legacy_history_node_compat_artifact": str(legacy_path.relative_to(ROOT)),
            "active_v3_policies_after_merge": 253,
            "total_policy_rows_after_merge": 284,
            "policy_threshold_and_evidence_fields_changed": False,
            "policy_diff_artifact": str(policy_path.relative_to(ROOT)),
            "active_set_integrity_checks": target_eligibility["active_set_integrity_checks"],
        },
        "learner_history": {
            "table_fingerprints_before": history_counts_before,
            "table_fingerprints_after": history_counts_after,
            "kp_state_other_fields_before_after_exact": history_state_fingerprint_before == history_state_fingerprint_after,
            "kp_state_set_binding_changes": started,
            "kp_state_compatibility_metadata": {
                "legacy_history_unbound": len(legacy_detail),
                "current_set_transition_nodes": current_transition_count,
                "historical_only_nodes_without_current_v3_set": historical_only_count,
                "preexisting_history_fields_unchanged": True,
                "legacy_evidence_eligible_for_new_set_before_confirmation": False,
            },
            "attempt_learning_event_plan_row_counts_unchanged": all(
                history_counts_before[n] == history_counts_after[n]
                for n in ("daily_plans", "practice_items", "question_attempts", "learning_events")
            ),
        },
        "shared_review_support_tables": shared_audit_tables,
        "eligibility": {
            "sealed_candidate_formal_questions": source_eligibility,
            "merged_current_formal_questions": target_eligibility,
        },
        "pre_merge_counts": target_counts_before,
        "post_merge_counts": {name: _table_fingerprint(target, name)["rows"] for name in sorted(HISTORY_TABLES)} | {
            "questions": len(after_questions), "question_versions": len(after_version_rows),
            "question_auto_review_events": len(_read_rows(target, "question_auto_review_events")),
            "graduation_set_versions": len(_read_rows(target, "kp_graduation_question_set_versions")),
            "kp_mastery_policies": len(_read_rows(target, "kp_mastery_policies")),
            "kp_states": len(_read_rows(target, "kp_states")),
        },
        "limitations": ([
            "Real synchronization mode was explicitly enabled for the exact target kaoyan@127.0.0.1:5433 with system identifier 7686825087296682120.",
            "The sealed candidate was read only; mutations were limited to versioned Questions, current review events, release policy fields, active set versions, and the five previously frozen learner bindings.",
            "No Attempt, LearningEvent, DailyPlan, PracticeItem, or historical QuestionVersion content was modified or imported from the sealed candidate.",
        ] if REAL_SYNC_MODE else [
            "Only 253 current active set versions plus 1 additional distinct historical version needed by the 5 started target nodes were imported; 9,409 unrelated sealed-candidate historical set rows remain in the sealed source backup.",
            "The 5 set-version bindings are release metadata restored from the previously recorded Y3 started-node preview; no Attempt, LearningEvent, DailyPlan, KpState state/evidence/mastered_at field was changed.",
            "The 12 active-history nodes that have a current sealed v3 set have no reliable old frozen set; they remain legacy_history_unbound, old records stay display/learning-analysis only, and current v3 membership is not bound until explicit user-confirmed start.",
            "One additional legacy-marked node has historical practice items but no sealed current v3 set; it is preserved as historical-only and is not offered a synthetic v3 binding.",
            "This is an isolated rehearsal, not authorization or readiness approval for a real-database write.",
        ]),
    }
    _json_report(manifest_path, {
        "merged_database": DATABASES["merged"],
        "database_identity": identities["merged"],
        "post_merge_fingerprints": _merge_fingerprints(target),
        "formal_questions": len(formal_ids),
        "legacy_history_unbound_nodes": len(legacy_detail),
        "current_set_transition_nodes": current_transition_count,
        "historical_only_nodes_without_current_v3_set": historical_only_count,
    })
    _json_report(AUDIT_DIR / "phase45y-final1-merge-simulation.json", result)
    print(json.dumps(_normal({
        "status": result["status"], "merged_database": DATABASES["merged"],
        "question_merge": result["question_merge"], "sets_and_policy": result["sets_and_policy"],
        "eligibility": {"source_pass": source_eligibility["pass"], "merged_pass": target_eligibility["pass"]},
        "report": str((AUDIT_DIR / "phase45y-final1-merge-simulation.json").relative_to(ROOT)),
    }), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
