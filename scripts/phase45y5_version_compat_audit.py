"""Read-only Phase 4.5Y-5 version compatibility audit.

Only connects to the two known Phase 45Y rehearsal databases on port 59227,
inside BEGIN READ ONLY transactions. It never connects to the real 5433 DB.
Outputs the machine-readable conflict matrix and event-binding audit under the
ignored quality-audits directory. It intentionally does not apply a merge.
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import psycopg
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "storage/quality-audits/phase45y3-20261014-run01"
OUT = RUN / "phase45y5"
LIVE_CLONE = "phase45y3_devclone_test"
SEALED = "phase45y3_sealed_candidate_test"
PORT = 59227
LIVE_SYSTEM_ID = "7686825087296682120"
EXPECTED_ISOLATED_SYSTEM_ID = "7696351896186319976"
SNAPSHOT = ROOT / "storage/quality-audits/phase45z-final-20261013/validation-retry1/formal-content-snapshot.json"

sys.path.insert(0, str(ROOT))
from backend.services.auto_question_review import question_snapshot_payload  # noqa: E402
from backend.services.answer_verification import answer_version_sha256  # noqa: E402
from backend.services.golden_learning_slice import digest  # noqa: E402


def question_ids_sha256(ids: list[Any]) -> str:
    return hashlib.sha256(json.dumps(list(ids), ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def table_fingerprint(conn, table: str, *, exclude_columns: set[str] | None = None) -> dict[str, Any]:
    exclude_columns = exclude_columns or set()
    columns = [r["column_name"] for r in conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position",
        (table,),
    ).fetchall() if r["column_name"] not in exclude_columns]
    if not columns:
        raise RuntimeError(f"no fingerprintable columns for {table}")
    quoted = ",".join(f'"{c}"' for c in columns)
    rows = [dict(r) for r in conn.execute(f'SELECT {quoted} FROM public."{table}" ORDER BY "{columns[0]}"').fetchall()]
    raw = json.dumps(rows, sort_keys=True, default=str).encode("utf-8")
    return {"rows": len(rows), "sha256": hashlib.sha256(raw).hexdigest(), "columns": columns}


def connect(name: str):
    if name not in {LIVE_CLONE, SEALED}:
        raise RuntimeError(f"database not allow-listed: {name}")
    conn = psycopg.connect(
        host="127.0.0.1", port=PORT, dbname=name, user="postgres",
        options="-c default_transaction_read_only=on",
        row_factory=dict_row,
        application_name="phase45y5_readonly_version_audit",
    )
    conn.execute("BEGIN READ ONLY")
    conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
    identity = conn.execute(
        "SELECT current_database() AS db, current_setting('port') AS port, "
        "current_setting('transaction_read_only') AS ro, "
        "(SELECT system_identifier::text FROM pg_control_system()) AS system_id, "
        "(SELECT version_num FROM alembic_version) AS revision"
    ).fetchone()
    if identity["db"] != name or identity["port"] != str(PORT) or identity["ro"] != "on":
        raise RuntimeError(f"identity/read-only guard failed: {identity}")
    if identity["system_id"] != EXPECTED_ISOLATED_SYSTEM_ID or identity["system_id"] == LIVE_SYSTEM_ID:
        raise RuntimeError(f"unexpected PostgreSQL cluster: {identity['system_id']}")
    return conn, identity


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0]) if rows else []
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def canonical_question(row: dict[str, Any]) -> SimpleNamespace:
    # The payload helper ignores unrelated SQLAlchemy state and computes the
    # exact qualification/grading hash used by AUTO_REVIEW v8.
    return SimpleNamespace(**row)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    snapshot_rows = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    snapshot = {str(row["id"]): row for row in snapshot_rows}
    if len(snapshot) != 1804:
        raise RuntimeError(f"unexpected sealed snapshot size: {len(snapshot)}")
    with (RUN / "question-merge-preview.csv").open(encoding="utf-8-sig", newline="") as fh:
        preview = list(csv.DictReader(fh))
    conflict_rows = [r for r in preview if r["status"] == "CONFLICT"]
    if len(conflict_rows) != 387:
        raise RuntimeError(f"expected 387 conflicts, got {len(conflict_rows)}")
    conflict_ids = [r["question_id"] for r in conflict_rows]
    formal_ids = list(snapshot)

    target, target_identity = connect(LIVE_CLONE)
    candidate, candidate_identity = connect(SEALED)
    try:
        if target_identity["system_id"] != candidate_identity["system_id"]:
            raise RuntimeError("rehearsal databases are not on the known isolated cluster")
        protected_tables = ("question_attempts", "learning_events", "kp_states", "daily_plans", "practice_items")
        protected_before = {table: table_fingerprint(target, table) for table in protected_tables}
        qcols = [r["column_name"] for r in candidate.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name='questions' ORDER BY ordinal_position"
        ).fetchall()]
        selected = ",".join(f'"{c}"' for c in qcols)
        target_rows = {str(r["id"]): r for r in target.execute(
            f"SELECT {selected} FROM questions WHERE id=ANY(%s::uuid[])", (conflict_ids,)
        ).fetchall()}
        candidate_rows = {str(r["id"]): r for r in candidate.execute(
            f"SELECT {selected} FROM questions WHERE id=ANY(%s::uuid[])", (conflict_ids,)
        ).fetchall()}
        if set(target_rows) != set(conflict_ids) or set(candidate_rows) != set(conflict_ids):
            raise RuntimeError("conflict Question rows are incomplete in rehearsal DBs")
        all_candidate_rows = {str(r["id"]): r for r in candidate.execute(
            f"SELECT {selected} FROM questions WHERE id=ANY(%s::uuid[])", (formal_ids,)
        ).fetchall()}
        if set(all_candidate_rows) != set(formal_ids):
            raise RuntimeError("candidate DB does not contain the exact formal snapshot ID set")
        candidate_kp_codes = {str(r["id"]): r["code"] for r in candidate.execute(
            "SELECT id, code FROM knowledge_points"
        ).fetchall()}
        sealed_snapshot_mismatches = []
        for qid, snap in snapshot.items():
            q = all_candidate_rows[qid]
            fields = []
            for snapshot_field, question_field in (("stem", "stem"), ("options", "options"),
                    ("answer", "correct_answer"), ("explanation", "explanation")):
                if snap.get(snapshot_field) != q.get(question_field):
                    fields.append(snapshot_field)
            if candidate_kp_codes.get(str(q["kp_id"])) != snap.get("node_code"):
                fields.append("node_code")
            if fields:
                sealed_snapshot_mismatches.append({"question_id": qid, "fields": fields})

        version_schema = {}
        for db_name, conn in ((LIVE_CLONE, target), (SEALED, candidate)):
            tables = {r["table_name"] for r in conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
            ).fetchall()}
            column_rows = conn.execute(
                "SELECT table_name, column_name FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name IN ('questions','practice_items','question_attempts','learning_events')"
            ).fetchall()
            cols_by_table: dict[str, set[str]] = defaultdict(set)
            for r in column_rows:
                cols_by_table[r["table_name"]].add(r["column_name"])
            version_schema[db_name] = {
                "question_content_versions_table": "question_content_versions" in tables,
                "questions_has_current_content_version_id": "current_content_version_id" in cols_by_table["questions"],
                "practice_items_has_content_version_id": "question_content_version_id" in cols_by_table["practice_items"],
                "question_attempts_has_content_version_id": "question_content_version_id" in cols_by_table["question_attempts"],
                "learning_events_has_content_version_id": "question_content_version_id" in cols_by_table["learning_events"],
                "attempt_has_snapshot_hash_in_json": "grading_evidence" in cols_by_table["question_attempts"],
            }

        candidate_policies = candidate.execute(
            "SELECT kp_id::text AS kp_id, graduation_set_version, graduation_question_ids "
            "FROM kp_mastery_policies ORDER BY kp_id"
        ).fetchall()
        candidate_sets = candidate.execute(
            "SELECT kp_id::text AS kp_id, set_version, question_ids, question_ids_sha256 "
            "FROM kp_graduation_question_set_versions ORDER BY kp_id, set_version"
        ).fetchall()
        active_sets = [p for p in candidate_policies if int(p["graduation_set_version"] or 0) > 0]
        active_members: list[str] = []
        active_set_hash_matches = 0
        active_set_member_map_mismatches = []
        for policy in active_sets:
            current_set = next((s for s in candidate_sets if s["kp_id"] == policy["kp_id"]
                                and int(s["set_version"]) == int(policy["graduation_set_version"])), None)
            if current_set is None:
                active_set_member_map_mismatches.append({"kp_id": policy["kp_id"], "reason": "current_set_missing"})
                continue
            set_ids = [str(x) for x in (current_set["question_ids"] or [])]
            if set_ids != [str(x) for x in (policy["graduation_question_ids"] or [])]:
                active_set_member_map_mismatches.append({"kp_id": policy["kp_id"], "reason": "policy_set_ids_differ"})
            active_members.extend(set_ids)
            if question_ids_sha256(current_set["question_ids"] or []) == current_set["question_ids_sha256"]:
                active_set_hash_matches += 1
        actual_set_member = {str(r["qid"]): str(r["kpid"]) for r in candidate.execute(
            "SELECT q.id::text AS qid, q.kp_id::text AS kpid FROM questions q WHERE q.id=ANY(%s::uuid[])",
            (formal_ids,),
        ).fetchall()}
        expected_set_member = {qid: str(policy["kp_id"]) for policy in active_sets
                                for qid in (policy["graduation_question_ids"] or [])}
        set_wrong_node = sorted(qid for qid in formal_ids if expected_set_member.get(qid) != actual_set_member.get(qid))

        target_states = {r["kp_id"]: r for r in target.execute(
            "SELECT kp_id::text AS kp_id, state, mastered_at, graduation_set_version FROM kp_states ORDER BY kp_id"
        ).fetchall()}
        candidate_states = {r["kp_id"]: r for r in candidate.execute(
            "SELECT kp_id::text AS kp_id, state, mastered_at, graduation_set_version FROM kp_states ORDER BY kp_id"
        ).fetchall()}
        started_ids = [kid for kid, state in target_states.items()
                       if state["state"] != "unseen" or state["mastered_at"] is not None]
        started_bindings = [{
            "kp_id": kid,
            "target_state": target_states[kid]["state"],
            "target_mastered_at": target_states[kid]["mastered_at"],
            "target_set_binding": target_states[kid]["graduation_set_version"],
            "sealed_candidate_state": candidate_states.get(kid, {}).get("state"),
            "sealed_candidate_mastered_at": candidate_states.get(kid, {}).get("mastered_at"),
            "sealed_candidate_binding": candidate_states.get(kid, {}).get("graduation_set_version"),
        } for kid in started_ids]
        protected_after = {table: table_fingerprint(target, table) for table in protected_tables}
        if protected_before != protected_after:
            raise RuntimeError("repeatable-read rehearsal changed a protected history fingerprint")

        target_refs = target.execute(
            "SELECT qid, attempts, linked_events, practice_items, completed_items FROM ("
            " SELECT q.id AS qid, count(DISTINCT a.id) AS attempts, "
            " count(DISTINCT e.id) AS linked_events, count(DISTINCT p.id) AS practice_items, "
            " count(DISTINCT p.id) FILTER (WHERE p.completed_at IS NOT NULL) AS completed_items "
            " FROM questions q LEFT JOIN question_attempts a ON a.question_id=q.id "
            " LEFT JOIN learning_events e ON e.source_id=a.id "
            " LEFT JOIN practice_items p ON p.question_id=q.id "
            " WHERE q.id=ANY(%s::uuid[]) GROUP BY q.id) s", (conflict_ids,)
        ).fetchall()
        refs = {str(r["qid"]): r for r in target_refs}

        # Confirm each sealed current pointer resolves to a content-hash-bound
        # AUTO_REVIEW event. No event is inserted or modified.
        current_event_ids = [str(r["auto_review_event_id"]) for r in all_candidate_rows.values() if r["auto_review_event_id"]]
        events = {str(r["id"]): r for r in candidate.execute(
            "SELECT id, question_id, event_type, qualification_class, review_version, "
            "question_snapshot_sha256, answer_sha256, audit_sha256, audit_snapshot, created_at "
            "FROM question_auto_review_events WHERE id=ANY(%s::uuid[])", (current_event_ids,)
        ).fetchall()}
        event_results: list[dict[str, Any]] = []
        for qid, qrow in all_candidate_rows.items():
            event_id = str(qrow.get("auto_review_event_id")) if qrow.get("auto_review_event_id") else ""
            event = events.get(event_id)
            computed_question_hash = digest(question_snapshot_payload(canonical_question(qrow)))
            computed_answer_hash = answer_version_sha256(canonical_question(qrow))
            audit = event.get("audit_snapshot") if event else None
            stages = (audit or {}).get("stages", {}) if isinstance(audit, dict) else {}
            checks = {
                "pointer_resolves": event is not None,
                "event_question_matches": bool(event and str(event["question_id"]) == qid),
                "event_is_qualified": bool(event and event["event_type"] == "qualified"),
                "snapshot_hash_matches": bool(event and event["question_snapshot_sha256"] == computed_question_hash),
                "answer_hash_matches": bool(event and event["answer_sha256"] == computed_answer_hash),
                "audit_hash_matches": bool(event and event["audit_sha256"] == digest(audit)),
                "audit_binds_snapshot": bool(event and audit.get("bound_question_snapshot_sha256") == event["question_snapshot_sha256"]),
                "all_stages_pass": bool(stages and all(isinstance(v, dict) and v.get("status") == "PASS" for v in stages.values())),
            }
            event_results.append({
                "question_id": qid, "event_id": event_id or None,
                "qualification_class": event.get("qualification_class") if event else None,
                "review_version": event.get("review_version") if event else None,
                "computed_question_snapshot_sha256": computed_question_hash,
                "computed_answer_sha256": computed_answer_hash,
                "checks": checks,
                "status": "PASS" if all(checks.values()) else "BLOCKED",
            })

        formal_event_rows = candidate.execute(
            "SELECT id, question_id, event_type, qualification_class, review_version, "
            "question_snapshot_sha256, answer_sha256, audit_sha256, audit_snapshot, "
            "idempotency_key, related_event_id, previous_state, created_at "
            "FROM question_auto_review_events WHERE question_id=ANY(%s::uuid[]) ORDER BY created_at, id",
            (formal_ids,),
        ).fetchall()
        formal_event_preview = []
        q_hashes = {qid: digest(question_snapshot_payload(canonical_question(qrow)))
                    for qid, qrow in all_candidate_rows.items()}
        a_hashes = {qid: answer_version_sha256(canonical_question(qrow))
                    for qid, qrow in all_candidate_rows.items()}
        for event in formal_event_rows:
            qid = str(event["question_id"])
            audit = event["audit_snapshot"]
            audit_integrity = (
                event["audit_sha256"] == digest(audit)
                and (audit or {}).get("bound_question_snapshot_sha256") == event["question_snapshot_sha256"]
            )
            snapshot_matches = event["question_snapshot_sha256"] == q_hashes[qid]
            answer_matches = event["answer_sha256"] == a_hashes[qid]
            if not snapshot_matches or not answer_matches:
                status = "STALE_CONTENT_VERSION"
                disposition = "EXCLUDE_FROM_CURRENT_VERSION_PUBLICATION"
            elif not audit_integrity:
                status = "AUDIT_INTEGRITY_ERROR"
                disposition = "BLOCK_EVENT"
            else:
                status = "MATCH_FINAL_CONTENT_VERSION"
                disposition = "IMPORT_ONLY_WITH_MATCHING_QUESTION_VERSION"
            formal_event_preview.append({
                "event_id": str(event["id"]), "question_id": qid,
                "event_type": event["event_type"], "qualification_class": event["qualification_class"],
                "review_version": event["review_version"],
                "event_question_snapshot_sha256": event["question_snapshot_sha256"],
                "current_question_snapshot_sha256": q_hashes[qid],
                "event_answer_sha256": event["answer_sha256"],
                "current_answer_sha256": a_hashes[qid],
                "snapshot_matches": snapshot_matches, "answer_matches": answer_matches,
                "audit_integrity": audit_integrity,
                "current_pointer_event": str(all_candidate_rows[qid].get("auto_review_event_id")) == str(event["id"]),
                "disposition": disposition, "status": status,
            })

        classifications: list[dict[str, Any]] = []
        for old in conflict_rows:
            qid = old["question_id"]
            live, sealed = target_rows[qid], candidate_rows[qid]
            differences = [c for c in qcols if live.get(c) != sealed.get(c)]
            semantic = sorted(set(differences) & {
                "stem", "options", "correct_answer", "question_type", "grading_mode", "grading_config", "kp_id", "skill_tags"
            })
            metadata = sorted(set(differences) & {
                "question_provenance", "content_trust", "source_status", "answer_provenance", "answer_reliability",
                "auto_review_event_id", "source_attestation_key", "source_attestation_sha256", "answer_attestation_key", "answer_attestation_sha256"
            })
            labels = []
            if metadata:
                labels.append("A_METADATA_DIFF")
            if "explanation" in differences:
                labels.append("B_EXPLANATION_DIFF")
            if set(differences) & {"stem", "options"}:
                labels.append("C_STEM_OR_OPTIONS_DIFF")
            if semantic:
                labels.append("D_ANSWER_TYPE_OR_GRADING_SEMANTICS_DIFF")
            ref = refs.get(qid, {})
            if any(int(ref.get(k) or 0) for k in ("attempts", "linked_events", "practice_items", "completed_items")):
                labels.append("E_HISTORICAL_REFERENCE")
            event_result = next(row for row in event_results if row["question_id"] == qid)
            classifications.append({
                "question_id": qid,
                "node_code": old["node_code"],
                "current_live_version_hash": old["live_content_sha256"],
                "sealed_version_hash": old["candidate_snapshot_sha256"],
                "changed_fields": ";".join(differences),
                "risk_labels": ";".join(labels),
                "semantic_changed_fields": ";".join(semantic),
                "metadata_changed_fields": ";".join(metadata),
                "attempt_count": int(ref.get("attempts") or 0),
                "linked_learning_event_count": int(ref.get("linked_events") or 0),
                "practice_item_count": int(ref.get("practice_items") or 0),
                "completed_practice_item_count": int(ref.get("completed_items") or 0),
                "sealed_current_review_event_status": event_result["status"],
                "decision": "BLOCK_UNTIL_IMMUTABLE_CONTENT_VERSION_AND_PRACTICE_ITEM_BINDING",
            })

        # This list is a machine-readable, non-SQL merge disposition. No database
        # writes occur: inserts and version updates are intentionally NOT applied.
        merge_rows: list[dict[str, Any]] = []
        for row in preview:
            status = row["status"]
            if status == "INSERT":
                action = "INSERT_REHEARSAL_PENDING_VERSION_SCHEMA"
            elif status == "CONFLICT":
                action = "VERSIONED_UPDATE_BLOCKED_RUNTIME_UNSUPPORTED"
            elif status.startswith("PRESERVE_"):
                action = "PRESERVE_TARGET_ONLY"
            else:
                action = "EXCLUDE_NONFORMAL_CANDIDATE"
            merge_rows.append({**row, "phase45y5_action": action, "applied": "NO"})

        event_status_counts = Counter(row["status"] for row in event_results)
        formal_event_status_counts = Counter(row["status"] for row in formal_event_preview)
        risk_counts = Counter(label for row in classifications for label in row["risk_labels"].split(";") if label)
        reference_counts = {
            "question_ids_with_attempts": sum(int(r["attempt_count"]) > 0 for r in classifications),
            "attempt_rows": sum(int(r["attempt_count"]) for r in classifications),
            "question_ids_with_learning_events": sum(int(r["linked_learning_event_count"]) > 0 for r in classifications),
            "linked_learning_event_rows": sum(int(r["linked_learning_event_count"]) for r in classifications),
            "question_ids_with_any_practice_item": sum(int(r["practice_item_count"]) > 0 for r in classifications),
            "practice_item_rows": sum(int(r["practice_item_count"]) for r in classifications),
            "completed_practice_item_rows": sum(int(r["completed_practice_item_count"]) for r in classifications),
        }
        summary = {
            "status": "PHASE45Y5_MERGE_SIMULATION_BLOCKED",
            "generated_at_local": datetime.now().astimezone().isoformat(timespec="seconds"),
            "database_access": {
                "target_database": LIVE_CLONE, "candidate_database": SEALED, "port": PORT,
                "target_revision": target_identity["revision"], "candidate_revision": candidate_identity["revision"],
                "system_identifier": target_identity["system_id"], "transaction_mode": "READ ONLY",
                "real_5433_connected": False, "database_writes": False,
            },
            "candidate": {
                "formal_question_count": len(snapshot),
                "math2_count": sum(1 for r in snapshot.values() if str(r.get("node_code", "")).startswith("math.")),
                "cs408_count": sum(1 for r in snapshot.values() if str(r.get("node_code", "")).startswith("cs408.")),
                "sealed_snapshot_content_and_node_mapping_mismatches": len(sealed_snapshot_mismatches),
                "sealed_snapshot_mismatch_samples": sealed_snapshot_mismatches[:10],
                "current_review_event_checks": dict(event_status_counts),
                "formal_ids_with_current_review_pointer": len(event_results),
                "version_schema": version_schema[SEALED],
                "graduation_sets": {
                    "all_version_rows": len(candidate_sets), "active_v3_sets": len(active_sets),
                    "active_member_entries": len(active_members), "unique_active_member_ids": len(set(active_members)),
                    "active_set_hashes_matching": active_set_hash_matches,
                    "formal_id_coverage_exact": set(active_members) == set(formal_ids),
                    "member_to_question_kp_mismatches": len(set_wrong_node),
                "member_to_question_kp_mismatch_samples": [
                    {"question_id": qid, "set_kp_id": expected_set_member.get(qid),
                     "question_kp_id": actual_set_member.get(qid)} for qid in set_wrong_node[:10]
                ],
                    "policy_set_mismatches": len(active_set_member_map_mismatches),
                },
                "target_started_node_count": len(started_ids),
                "started_node_bindings": started_bindings,
            },
            "historical_data": {
                "fingerprints_before": protected_before,
                "fingerprints_after": protected_after,
                "before_after_equal_in_repeatable_read_snapshot": protected_before == protected_after,
                "merge_applied": False,
            },
            "conflicts": {
                "count": len(classifications), "multi_label_risk_counts": dict(risk_counts),
                "historical_references": reference_counts,
                "classification_csv": "storage/quality-audits/phase45y3-20261014-run01/phase45y5/question-version-compatibility.csv",
            },
            "merge_preview": {
                "missing_question_inserts": sum(r["status"] == "INSERT" for r in preview),
                "same_id_version_conflicts": len(classifications),
                "live_only_preserved": sum(r["status"].startswith("PRESERVE_") for r in preview),
                "candidate_nonformal_excluded": sum(r["status"] == "EXCLUDE_NONFORMAL_CANDIDATE_ONLY" for r in preview),
                "question_rows_applied": 0, "official_release_published": False,
            },
            "review_event_audit": {
                "current_pointer_status_counts": dict(event_status_counts),
                "all_current_pointers_pass": event_status_counts == {"PASS": len(event_results)} and len(event_results) == 1804,
                "current_pointer_rows_csv": "storage/quality-audits/phase45y3-20261014-run01/phase45y5/current-review-event-audit.csv",
                "failed_question_ids": [row["question_id"] for row in event_results if row["status"] != "PASS"],
                "formal_event_rows_total": len(formal_event_preview),
                "formal_event_status_counts": dict(formal_event_status_counts),
                "formal_event_preview_csv": "storage/quality-audits/phase45y3-20261014-run01/phase45y5/formal-review-event-import-preview.csv",
                "event_insertions_applied": 0,
            },
            "blockers": [
                "Schema has no immutable Question content-version table or version FK on PracticeItem.",
                "QuestionAttempt contains answer/grading evidence hashes but not the full historical stem/options/explanation; LearningEvent refers to Attempt rather than a Question version.",
                "PracticeItem rendering, grading, assistance and review paths resolve mutable item.question; updating the 387 current Question rows would reinterpret old unattempted/attempted plans.",
                "Therefore the 1417 inserts and 387 version publications were not applied; the 1804-item release and 253 current sets were not published in this rehearsal.",
            ],
            "minimum_compatibility_repair": [
                "Add append-only question_content_versions containing full display/grading/trust snapshot and canonical content hash.",
                "Add current version pointer to Question and immutable version FK to PracticeItem; backfill every existing item to the premerge snapshot before updating any Question.",
                "Route all PracticeItem display, answer grading, eligibility, hints/solutions and history replay through the bound version snapshot.",
                "Bind new PracticeItems to the current version; create a new version on protected content/answer/grading/trust changes; retain old Question and audit events.",
                "Add integration tests proving old plan renders/grades old snapshot, new plan uses sealed snapshot, and Attempt/LearningEvent/KpState remain unchanged by content release.",
            ],
            "minimum_compatibility_repair_required": not version_schema[SEALED]["question_content_versions_table"],
        }
        write_csv(OUT / "question-version-compatibility.csv", classifications)
        write_csv(OUT / "merge-result.csv", merge_rows)
        write_csv(OUT / "current-review-event-audit.csv", [{
            "question_id": row["question_id"], "event_id": row["event_id"],
            "qualification_class": row["qualification_class"], "review_version": row["review_version"],
            "computed_question_snapshot_sha256": row["computed_question_snapshot_sha256"],
            "computed_answer_sha256": row["computed_answer_sha256"],
            "checks": json.dumps(row["checks"], ensure_ascii=False, sort_keys=True), "status": row["status"],
        } for row in event_results])
        write_csv(OUT / "formal-review-event-import-preview.csv", formal_event_preview)
        (OUT / "merge-result.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
        print(json.dumps({
            "status": summary["status"], "database_access": summary["database_access"],
            "candidate": {k: v for k, v in summary["candidate"].items() if k != "started_node_bindings"},
            "conflicts": summary["conflicts"], "merge_preview": summary["merge_preview"],
            "review_event_audit": summary["review_event_audit"],
            "historical_data": summary["historical_data"],
            "outputs": [str(OUT / "question-version-compatibility.csv"), str(OUT / "merge-result.csv"), str(OUT / "current-review-event-audit.csv"), str(OUT / "formal-review-event-import-preview.csv"), str(OUT / "merge-result.json")],
        }, ensure_ascii=False, indent=2, default=str))
    finally:
        target.rollback()
        candidate.rollback()
        target.close()
        candidate.close()


if __name__ == "__main__":
    main()
