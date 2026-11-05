"""Append-only continuation runtime for the already authorized 40-request audit.

This runtime keeps the canonical V2 ledger and all prior V3 artifacts immutable.
It accepts only the existing isolated PostgreSQL cluster and records a new
database continuation snapshot instead of rewriting the historical baseline.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.naiwa_v3_runtime_20261022 as paid
from scripts import naiwa_agent_full_v2_20261021 as legacy
from scripts.naiwa_freeze_gate_20261021 import atomic_json, process_started
from desktop.postgres import _run

PARENT_OUT = ROOT / "storage/quality-audits/naiwa-freeze-preflight-20261021/naiwa-v3-20261022"
PARENT_RUN = ROOT / "storage/manual-experience/naiwa-real-20261020/agent-full-v3-20261022"
_tag = os.environ.get("NAIWA_V33_CONTINUATION_TAG", "r3")
if not _tag.replace("-", "").isalnum() or len(_tag) > 24:
    raise RuntimeError("invalid_continuation_tag")
OUT = ROOT / f"storage/quality-audits/naiwa-v33-closeout-20261023/paid-continuation-{_tag}"
_default_run = ROOT / f"storage/manual-experience/naiwa-real-20261020/agent-full-v33-continue-20261023-{_tag}"
_run_override = os.environ.get("NAIWA_V33_CONTINUATION_RUN")
RUN = Path(_run_override).resolve() if _run_override else _default_run
# The fresh user-authorized round has its own append-only ledger. Historical
# ledgers remain read-only evidence and are checked by hash before and during
# the run; none of their reservations are imported into this round's count.
PARENT_LEDGER_DIR = legacy.LEDGER_DIR
PARENT_LEDGER = legacy.LEDGER_PATH
_ledger_tag = os.environ.get("NAIWA_V33_EXPLORATORY_LEDGER_TAG", _tag)
if not _ledger_tag.replace("-", "").isalnum() or len(_ledger_tag) > 24:
    raise RuntimeError("invalid_exploratory_ledger_tag")
LEDGER_DIR = legacy.ROUND.parent / f"round40-v33-exploratory-{_ledger_tag}"
LEDGER = LEDGER_DIR / "provider-ledger.json"
AUTHORIZATION_FILE = Path(r"C:\Users\ZBT\.codex\attachments\386c0c50-513f-48a5-8400-f6b076e05439\已粘贴的文本.txt")
NODE_DRIVER = ROOT / "frontend/acceptance/naiwa-v33-paid-continuation.cjs"
if not LEDGER_DIR.resolve().is_relative_to(legacy.ROUND.parent.resolve()):
    raise RuntimeError("independent_ledger_outside_gate_parent")

# A local hard ceiling for this differentiated acceptance run.  The user-facing
# categories map onto the already authorized gate scenes; the existing A-scene
# cap of three is stricter than this turn's four-call allowance and already has
# two reservations, so only one additional A-scene request can be made.
ROUND_CATEGORY_TO_GATE_SCENE = {
    "A": "A", "B": "C", "C": "E", "D": "D",
    "E": "B", "F": "F", "G": "H", "H": "R",
}
ROUND_CATEGORY_NEW_CAPS = {"A": 4, "B": 4, "C": 4, "D": 3,
                           "E": 2, "F": 3, "G": 2, "H": 2}
ROUND_GATE_SCENE_CAPS = {
    ROUND_CATEGORY_TO_GATE_SCENE[category]: (
        min(3, paid.LEGACY_CAPS["A"]) if category == "A"
        else min(ROUND_CATEGORY_NEW_CAPS[category], paid.LEGACY_CAPS[ROUND_CATEGORY_TO_GATE_SCENE[category]])
    )
    for category in ROUND_CATEGORY_TO_GATE_SCENE
}


class DifferentiatedRoundGate(paid.V3Gate):
    """Enforce this turn's smaller per-category caps before atomic reservation."""

    @staticmethod
    def round_cap_reached(records, scene):
        cap = ROUND_GATE_SCENE_CAPS.get(scene)
        return cap is not None and sum(row.get("case_id") == scene for row in records) >= cap

    def begin(self, request):
        # Keep the round-cap check under the same reservation locks used by the
        # base gate.  The parent V3 gate re-enters these locks before reserving.
        with self.authorization.hold(), self.lock, self.disk_lock:
            self.reload()
            scene = paid.SCENE.get()
            if self.round_cap_reached(self.records, scene):
                raise self.refusal("scene_cap")
            return super().begin(request)


paid.V3Gate = DifferentiatedRoundGate


def read(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_new(path: Path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, default=str)


def persist(path: Path, value):
    atomic_json(Path(path), value)


def create_round_ledger(ledger_path: Path, control_path: Path):
    """Create a fresh closed ledger once; never copy or overwrite a prior round."""
    ledger_path, control_path = Path(ledger_path), Path(control_path)
    if ledger_path.exists() or control_path.exists():
        raise RuntimeError("new_round_ledger_path_already_exists")
    document = {
        "limits": {"max_requests": 40},
        "scene_limits": paid.LEGACY_CAPS,
        "purpose_policy": {name: sorted(values) for name, values in paid.PURPOSE_POLICY.items()},
        "seal_on_scene_cap": False,
        "requests": [],
        "stop_reason": None,
    }
    save_new(ledger_path, document)
    save_new(control_path, {
        "paid_enabled": False,
        "authorization_received": False,
        "active_scene": None,
        "reason": "independent_round_ledger_starts_closed",
    })
    return document


def source_files():
    return sorted(set(_base_files() + [Path(__file__).resolve(), NODE_DRIVER.resolve(),
                                     ROOT / 'scripts/naiwa_edge_authorization.py',
                                     ROOT / 'scripts/naiwa_differentiated_test_runtime_20261024.py',
                                     ROOT / 'scripts/naiwa_closeout_fixtures_20261024.py',
                                     ROOT / 'tests/fixtures/naiwa_closeout_lhopital_20261024.md',
                                     ROOT / 'storage/quality-audits/naiwa-differentiated-acceptance-20261024/service_probe.py']))


def source_hashes():
    return {p.relative_to(ROOT).as_posix(): legacy.sha(p) for p in source_files() if p.is_file()}


ISOLATED_PORTS = (63044, 63045, 63046)


def assert_isolated_ports_free():
    """Guard only ports this isolated runtime will bind; leave daily ports alone."""
    for port in ISOLATED_PORTS:
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError as exc:
                raise RuntimeError(f"isolated_port_not_free:{port}") from exc


def record_source_revision(changed_paths, reason):
    """Advance the stopped isolated runtime's code epoch without rewriting its prior manifest."""
    active_path = RUN / "active-source-hashes.json"
    active = read(active_path)
    previous = active["source_sha256"]
    current = source_hashes()
    actual = sorted(name for name in set(previous) | set(current)
        if previous.get(name) != current.get(name))
    expected = sorted(str(name).replace("\\", "/") for name in changed_paths)
    if not expected or actual != expected:
        raise RuntimeError(f"source_revision_scope_mismatch:actual={actual}:expected={expected}")
    epoch = int(active["epoch"]) + 1
    revision_path = RUN / f"source-revision-{epoch}.json"
    prior_manifest_path = RUN / f"source-manifest-epoch-{active['epoch']}.json"
    if revision_path.exists() or prior_manifest_path.exists():
        raise RuntimeError("source_revision_record_already_exists")
    save_new(prior_manifest_path, active)
    revision = {
        "epoch": epoch,
        "previous_epoch": active["epoch"],
        "previous_manifest_sha256": legacy.sha(active_path),
        "source_sha256": current,
        "changed_paths": actual,
        "reason": reason,
        "time": time.time(),
    }
    save_new(revision_path, revision)
    persist(active_path, revision)
    print(json.dumps({"status": "SOURCE_EPOCH_RECORDED", "epoch": epoch,
        "changed_paths": actual, "manifest_sha256": legacy.sha(active_path)}, ensure_ascii=True))


_base_files = paid.files
paid.files = source_files
paid.hashes = source_hashes
paid.OUT = OUT
paid.RUN = RUN
paid.LEDGER_DIR = LEDGER_DIR
paid.LEDGER = LEDGER
paid.bind()


def install_integrity_callback():
    """Protect a full per-epoch snapshot; allow only this run's registered records to mutate."""
    from sqlalchemy.engine import make_url

    original_verify = legacy.verify_integrity

    def verify(**kwargs):
        validate_parent_ledger()
        paid.validate_history()
        runtime_data = read(RUN / "runtime-data.json")
        registry = read(RUN / "session-registry.json")
        mutable_sessions = [row["session_id"] for row in registry.get("sessions", [])]
        current_path = OUT / f"database-integrity-{time.time_ns()}.json"
        current = legacy.snapshot_database(current_path)
        epoch = read(RUN / "active-source-hashes.json")["epoch"]
        baseline_path = OUT / f"database-repair-before-epoch-{epoch}.json"
        if not baseline_path.is_file():
            raise RuntimeError("repair_epoch_database_baseline_missing")
        baseline = read(baseline_path)
        session_ids = {str(value) for value in mutable_sessions}
        mutable_requests = [row["id"] for row in current.get("practice_requests", [])
            if str(row.get("source_conversation_id")) in session_ids]
        diff = legacy.compare_snapshot(
            baseline,
            current,
            mutable_session_ids=mutable_sessions,
            mutable_plan_id=runtime_data.get("today_plan_id"),
            mutable_practice_request_ids=mutable_requests,
        )
        result_path = OUT / f"database-integrity-{time.time_ns()}.json"
        persist(result_path, {
            "scene": kwargs.get("scene"),
            "request_id": str(getattr(kwargs.get("request"), "url", "")),
            "snapshot": str(current_path),
            "diff": diff,
            "checked_at": time.time(),
        })
        if not diff["preexisting_rows_preserved"]:
            raise RuntimeError("continuation_database_integrity_failed")
        # Preserve the original function for audit comparison only; it is not
        # called because it is bound to the older, pre-continuation snapshot.
        _ = original_verify, make_url

    legacy.verify_integrity = verify


def validate_parent_ledger():
    """Keep the earlier 40-call phase immutable while this round counts from zero."""
    baseline = read(OUT / "continuation-preflight.json")
    if legacy.sha(PARENT_LEDGER) != baseline["parent_ledger_sha256"]:
        raise RuntimeError("parent_canonical_ledger_changed_stop")
    if legacy.sha(PARENT_LEDGER_DIR / "control.json") != baseline["parent_control_sha256"]:
        raise RuntimeError("parent_canonical_control_changed_stop")


def prepare():
    if OUT.exists() or RUN.exists() or LEDGER_DIR.exists():
        raise RuntimeError("continuation_paths_already_exist_do_not_overwrite")
    if not AUTHORIZATION_FILE.is_file():
        raise RuntimeError("current_round_authorization_evidence_missing")
    if not (PARENT_OUT / "protected-start.json").is_file() or not (PARENT_OUT / "zero-network-status.json").is_file():
        raise RuntimeError("parent_v3_protection_evidence_missing")

    expected = read(PARENT_OUT / "protected-start.json")
    protected_before = read(paid.STAGE0 / "protected-before.json")
    excluded = {
        PARENT_LEDGER.relative_to(ROOT).as_posix(),
        (PARENT_LEDGER_DIR / "control.json").relative_to(ROOT).as_posix(),
    }
    current_protected = {name: legacy.sha(ROOT / name) for name in protected_before if name not in excluded}
    if current_protected != expected:
        raise RuntimeError("protected_history_hash_mismatch_stop")
    parent_runtime = read(PARENT_OUT / "runtime-v2.json")
    parent_control = read(PARENT_OUT / "control.json")
    if parent_runtime.get("status") != "stopped" or parent_control.get("paid_enabled"):
        raise RuntimeError("parent_paid_runtime_not_closed_and_stopped")
    parent_active = read(PARENT_RUN / "active-source-hashes.json")
    prior_ledger = read(PARENT_LEDGER)
    if len(prior_ledger.get("requests", [])) != 1 or prior_ledger.get("stop_reason"):
        raise RuntimeError("canonical_40_ledger_count_or_stop_state_invalid")
    if any(not row.get("finished") for row in prior_ledger["requests"]):
        raise RuntimeError("canonical_40_ledger_has_unfinished_request")
    if prior_ledger["requests"][0].get("case_id") != "A":
        raise RuntimeError("canonical_first_request_scene_mismatch")
    if read(PARENT_LEDGER_DIR / "control.json").get("paid_enabled"):
        raise RuntimeError("canonical_parent_control_not_closed")

    OUT.mkdir(parents=True, exist_ok=False)
    RUN.mkdir(parents=True, exist_ok=False)
    LEDGER_DIR.mkdir(parents=True, exist_ok=False)
    (RUN / "session-registry.json").write_text(json.dumps({"sessions": []}, ensure_ascii=False, indent=2), encoding="utf-8")
    # Store an empty, schema-complete round ledger before the runtime can start.
    # This is a new authorization budget, not a copy or reset of any old ledger.
    create_round_ledger(LEDGER, LEDGER_DIR / "control.json")
    runtime_protected = dict(expected)
    runtime_protected[PARENT_LEDGER.relative_to(ROOT).as_posix()] = legacy.sha(PARENT_LEDGER)
    runtime_protected[(PARENT_LEDGER_DIR / "control.json").relative_to(ROOT).as_posix()] = legacy.sha(
        PARENT_LEDGER_DIR / "control.json"
    )
    (OUT / "protected-start.json").write_text(json.dumps(runtime_protected, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "zero-network-status.json").write_text(
        json.dumps(read(PARENT_OUT / "zero-network-status.json"), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    persist(OUT / "control.json", {
        "paid_enabled": False,
        "authorization_received": False,
        "active_scene": None,
        "reason": "continuation_prepared_closed_waiting_for_scene_authorization",
    })
    hashes = source_hashes()
    changed_paths = sorted(
        name
        for name in set(parent_active["source_sha256"]) | set(hashes)
        if parent_active["source_sha256"].get(name) != hashes.get(name)
    )
    active = {
        "epoch": int(parent_active["epoch"]) + 1,
        "source_sha256": hashes,
        "changed_paths": changed_paths,
        "parent_source_epoch_sha256": legacy.sha(PARENT_RUN / "active-source-hashes.json"),
        "reason": "append_only_v33_continuation_after_zero_paid_closeout",
        "recorded_at": time.time(),
    }
    persist(RUN / "active-source-hashes.json", active)

    parent_base = read(PARENT_OUT / "v3-baseline.json")
    baseline = {
        "parent_v3_baseline_sha256": legacy.sha(PARENT_OUT / "v3-baseline.json"),
        "parent_database_snapshot_sha256": legacy.sha(PARENT_OUT / "database-before.json"),
        "parent_cluster_id": parent_base["cluster_id"],
        "isolated_database": legacy.DATABASE,
        "parent_canonical_ledger_path": str(PARENT_LEDGER),
        "parent_ledger_sha256": legacy.sha(PARENT_LEDGER),
        "parent_control_sha256": legacy.sha(PARENT_LEDGER_DIR / "control.json"),
        "parent_historical_request_count": len(prior_ledger["requests"]),
        "new_ledger_path": str(LEDGER),
        "new_ledger_sha256_at_preparation": legacy.sha(LEDGER),
        "new_round_physical_request_count": 0,
        "global_limit": 40,
        "effective_scene_limits": {**paid.LEGACY_CAPS, "A": 3},
        "global_remaining_at_preparation": 40,
        "scene_remaining_at_preparation": {
            scene: cap
            for scene, cap in {**paid.LEGACY_CAPS, "A": 3}.items()
        },
        "old_ledgers_sha256": parent_base["old_ledger_sha256"],
        "source_epoch": active,
        "paid_enabled": False,
        "real_model_requests_in_preparation": 0,
        "database_policy": "preserve all inherited rows; continuation baseline is a new immutable snapshot; never rewrite parent snapshots",
    }
    persist(OUT / "continuation-preflight.json", baseline)
    persist(OUT / "v3-baseline.json", {
        "old_ledger_sha256": {
            path.relative_to(ROOT).as_posix(): legacy.sha(path)
            for path in legacy.OLD_LEDGERS
        },
        "cluster_id": parent_base["cluster_id"],
        "parent_historical_requests_not_counted": len(prior_ledger["requests"]),
        "new_round_requests": 0,
        "global_limit": 40,
        "effective_A_cap": 3,
        "parent_v3_baseline_sha256": legacy.sha(PARENT_OUT / "v3-baseline.json"),
    })
    persist(OUT / "source-drift-from-parent.json", {
        "parent_epoch": parent_active["epoch"],
        "new_epoch": active["epoch"],
        "changed_paths": changed_paths,
        "current_source_sha256": hashes,
    })
    persist(RUN / "authorization-provenance.json", {
        "source": str(AUTHORIZATION_FILE),
        "source_sha256": legacy.sha(AUTHORIZATION_FILE),
        "authorized_global_cap": 40,
        "inherited_requests": 0,
        "historical_ledgers_are_read_only": True,
        "independent_new_ledger": str(LEDGER),
        "no_budget_reset": True,
        "scenario_transfer": False,
        "authorization_reused_from_current_user_message": True,
    })
    if legacy.sha(LEDGER) != read(OUT / "continuation-preflight.json")["new_ledger_sha256_at_preparation"]:
        raise RuntimeError("new_round_ledger_initialization_mismatch")
    paid.validate_history()
    persist(OUT / "preparation-verification.json", {
        "status": "PREPARED_CLOSED",
        "protected_history_hashes_match": True,
        "parent_runtime_stopped": True,
        "parent_ledger_sha256": legacy.sha(PARENT_LEDGER),
        "parent_ledger_count": len(prior_ledger["requests"]),
        "new_ledger_sha256": legacy.sha(LEDGER),
        "new_ledger_count": len(read(LEDGER)["requests"]),
        "new_ledger_stop_reason": read(LEDGER).get("stop_reason"),
        "paid_enabled": False,
        "model_calls": 0,
        "changed_source_paths": changed_paths,
    })
    print(json.dumps({"status": "PREPARED_CLOSED", "ledger_count": 0, "global_limit": 40,
                      "effective_A_limit": 3, "paid_enabled": False, "changed_source_paths": changed_paths}, ensure_ascii=True))


def attach_paths():
    paid.OUT = OUT
    paid.RUN = RUN
    paid.LEDGER_DIR = LEDGER_DIR
    paid.LEDGER = LEDGER
    paid.files = source_files
    paid.hashes = source_hashes
    paid.bind()
    install_integrity_callback()


def real_app():
    attach_paths()
    if os.environ.get("NAIWA_FRESH_TEST_DATABASE") == "1":
        # Fresh disposable databases use an identity guard, not the retained
        # experience snapshot. The physical provider gate and ledger are unchanged.
        from scripts.naiwa_differentiated_test_runtime_20261024 import verify_fresh_database_identity
        legacy.verify_integrity = verify_fresh_database_identity
    app = paid.real_app()
    if os.environ.get('NAIWA_EDGE_AUTH') != '1':
        return app
    from scripts.naiwa_edge_authorization import EdgeAuthorization
    epoch = read(RUN / 'active-source-hashes.json')['epoch']
    return EdgeAuthorization(app, run_dir=RUN, epoch=epoch, scene='A',
                             database=legacy.DATABASE, port=63044,
                             environment=os.environ.get('APP_ENV'))


def serve():
    import httpx

    attach_paths()
    if source_hashes() != read(RUN / "active-source-hashes.json")["source_sha256"]:
        raise RuntimeError("continuation_source_hash_mismatch")
    validate_parent_ledger()
    paid.validate_history()
    if not (OUT / "preparation-verification.json").is_file():
        raise RuntimeError("continuation_preparation_required")
    control = read(OUT / "control.json")
    if control.get("paid_enabled"):
        raise RuntimeError("continuation_must_start_paid_closed")
    gate = paid.gate()
    if gate.stop_reason or any(not row.get("finished") for row in gate.records):
        raise RuntimeError("canonical_ledger_not_ready_for_continuation")

    assert_isolated_ports_free()
    pg, owner = legacy.pg_owner_preflight()
    if owner["cluster_id"] != read(OUT / "continuation-preflight.json")["parent_cluster_id"]:
        raise RuntimeError("continuation_cluster_id_mismatch")
    pg.lock.acquire()
    children, logs = [], []
    runtime = None
    stage = "retained_cluster_start"
    failure = None
    try:
        epoch = int(read(RUN / "active-source-hashes.json")["epoch"])
        stop_path = RUN / f"stop.request-epoch-{epoch}.txt"
        runtime_path = OUT / "runtime-v2.json"
        if runtime_path.is_file():
            previous_runtime = read(runtime_path)
            archived_runtime = OUT / f"runtime-v2-epoch-{previous_runtime.get('source_epoch', 'unknown')}.json"
            if not archived_runtime.exists():
                save_new(archived_runtime, previous_runtime)
            elif previous_runtime.get("source_epoch") != epoch:
                raise RuntimeError("runtime_epoch_archive_collision")
        if (RUN / "loaded-code.json").is_file():
            loaded_epoch = read(RUN / "loaded-code.json").get("source_epoch", "unknown")
            archived_loaded = RUN / f"loaded-code-epoch-{loaded_epoch}.json"
            if not archived_loaded.exists():
                save_new(archived_loaded, read(RUN / "loaded-code.json"))
        start = _run([
            pg.binary("pg_ctl"), "-D", str(pg.cluster), "-l", str(OUT / f"postgres-epoch-{epoch}.log"), "-o",
            f"-p {pg.port} -c listen_addresses=127.0.0.1 -c log_statement=none -c log_min_error_statement=panic",
            "-w", "-t", "30", "start",
        ], timeout=45, capture=False)
        identity = pg._identity()
        if start.returncode or not identity:
            raise RuntimeError("owned_isolated_postgres_start_identity_unconfirmed")
        pg._owned_identity = identity
        stage = "database_snapshot"
        runtime = {
            "status": "starting",
            "launch_id": uuid4().hex,
            "workspace": str(ROOT),
            "supervisor_pid": os.getpid(),
            "supervisor_started": process_started(os.getpid()),
            "postgres_identity": list(identity),
            "postgres_pid": identity[0],
            "cluster_id": owner["cluster_id"],
            "database": {"db": legacy.DATABASE, "role": "kaoyan_app", "port": str(pg.port)},
            "ports": {"postgres": pg.port, "api": 63045, "web": 63046},
            "provider": "deepseek-flash",
            "api_key_logged": False,
            "source_epoch": epoch,
            "source_sha256": source_hashes(),
            "stop_request": str(stop_path),
        }
        persist(OUT / "runtime-v2.json", runtime)
        repair_baseline_path = OUT / f"database-repair-before-epoch-{epoch}.json"
        if repair_baseline_path.exists():
            raise RuntimeError("repair_epoch_database_baseline_already_exists")
        current = legacy.snapshot_database(repair_baseline_path, allow_live_identity=identity)
        parent = read(PARENT_OUT / "database-before.json")
        inherited_diff = legacy.compare_snapshot(parent, current)
        if not inherited_diff["preexisting_rows_preserved"]:
            raise RuntimeError("inherited_v3_database_row_drift_stop")
        persist(OUT / f"inherited-database-diff-epoch-{epoch}.json", {
            "against_parent_snapshot": str(PARENT_OUT / "database-before.json"),
            "continuation_snapshot": str(repair_baseline_path),
            "all_parent_rows_preserved": True,
            "diff": inherited_diff,
            "cluster_id": owner["cluster_id"],
            "captured_at": time.time(),
        })
        prior_continuation = read(OUT / "database-continuation-before.json")
        registry_before = read(RUN / "session-registry.json")
        prior_diff = legacy.compare_snapshot(prior_continuation, current,
            mutable_session_ids=[row["session_id"] for row in registry_before.get("sessions", [])],
            mutable_plan_id=read(RUN / "runtime-data.json").get("today_plan_id")
                if (RUN / "runtime-data.json").is_file() else None)
        if not prior_diff["preexisting_rows_preserved"]:
            persist(OUT / f"epoch-{epoch}-prior-database-diff-failure.json", prior_diff)
            raise RuntimeError("prior_continuation_rows_changed_stop")
        a1 = read(OUT / "explore-A1-capability-intro-journey.json")
        expected_session_id = a1.get("sseUrl", "").split("/sessions/")[-1].split("/")[0]
        known_request = next((row for row in current.get("practice_requests", [])
            if str(row.get("id")) == "b74ee57c-ad75-48a7-a92c-a66266646554"), None)
        if (not known_request or known_request.get("status") != "draft"
                or str(known_request.get("source_conversation_id")) != expected_session_id):
            raise RuntimeError("known_A1_misroute_state_changed_before_repair_epoch")
        persist(OUT / f"repair-baseline-epoch-{epoch}.json", {
            "snapshot": str(repair_baseline_path),
            "snapshot_sha256": legacy.sha(repair_baseline_path),
            "cluster_id": owner["cluster_id"],
            "database_identity": current["identity"],
            "schema_revision": current["schema_revision"],
            "baseline_semantics": "new post-A1 incident baseline; it does not replace or claim completeness for the predecessor snapshot",
            "known_incident": {
                "request_id": str(known_request["id"]),
                "status": known_request["status"],
                "source_conversation_id": str(known_request["source_conversation_id"]),
                "source_message_id": str(known_request["source_message_id"]),
                "user_request": known_request["user_request"],
            },
            "predecessor_diff": prior_diff,
            "time": time.time(),
        })
        if any(row.get("status") in {"running", "queued", "pending"} for row in current["learning_tasks"]):
            raise RuntimeError("active_learning_task_exists_stop")
        if any(row.get("status") in {"generating", "streaming", "pending"} for row in current["chat_messages"]):
            raise RuntimeError("active_chat_message_exists_stop")

        study_date = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
        plans = [row for row in current["daily_plans"] if row.get("study_date") == study_date and row.get("status") == "active"]
        if len(plans) > 1:
            raise RuntimeError("multiple_active_today_plans_stop")
        runtime_data = {
            "cluster_id": owner["cluster_id"],
            "today_plan_id": str(plans[0]["id"]) if plans else None,
            "study_date": study_date,
            "today_plan_count": len(plans),
        }
        if (RUN / "runtime-data.json").is_file():
            archive = RUN / f"runtime-data-epoch-{epoch - 1}.json"
            if not archive.exists():
                save_new(archive, read(RUN / "runtime-data.json"))
        persist(RUN / "runtime-data.json", runtime_data)
        nonce = os.urandom(32).hex()
        (RUN / "browser-nonce.txt").write_text(nonce, encoding="ascii")
        effective, key = legacy._load_live_settings()
        from sqlalchemy.engine import URL
        db_url = URL.create(
            "postgresql+psycopg",
            username="kaoyan_app",
            password=pg._passwords["kaoyan_app"],
            host="127.0.0.1",
            port=pg.port,
            database=legacy.DATABASE,
        ).render_as_string(hide_password=False)
        env = {
            **os.environ,
            "APP_ENV": "test",
            "DATABASE_URL": db_url,
            "TEST_DATABASE_URL": db_url,
            "KAOYAN_OWNED_TEST_PORT": str(pg.port),
            "PHASE45E_OWNED_TEST_PORT": str(pg.port),
            "LLM_API_KEY": key,
            "LLM_BASE_URL": effective.llm_base_url,
            "LLM_MODEL": effective.llm_model,
            "LLM_STREAM_INCLUDE_USAGE": "true",
            "MODEL_SETTINGS_PATH": str(RUN / "model-settings.bin"),
            "UPLOAD_DIR": str(legacy.HOME / "uploads"),
            "CHROMA_DIR": str(legacy.HOME / "chroma"),
            "MODEL_CACHE_DIR": str(ROOT / "storage/models"),
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "ANONYMIZED_TELEMETRY": "False",
            "DO_NOT_TRACK": "1",
            "OTEL_SDK_DISABLED": "true",
            "PYTHONIOENCODING": "utf-8",
            "ALLOWED_WEB_ORIGINS": json.dumps(["http://127.0.0.1:63046"]),
            "VITE_API_PROXY_TARGET": "http://127.0.0.1:63045",
            "NAIWA_REAL_RETEST_BUDGET7": "0",
            "NAIWA_FINAL_ROUND_STAGE2": "0",
            "NAIWA_V2_REAL_AUTHORIZED": "explicit_existing_cap40_only",
        }
        commands = [
            [sys.executable, "-m", "uvicorn", "scripts.naiwa_v33_paid_continuation_20261023:real_app",
             "--factory", "--host", "127.0.0.1", "--port", "63045"],
            [r"D:\应用安装包\node.exe", "node_modules/vite/bin/vite.js", "--host", "127.0.0.1",
             "--port", "63046", "--strictPort"],
        ]
        runtime["commands"] = commands
        for name, command, cwd in zip(("backend", "frontend"), commands, (ROOT, ROOT / "frontend")):
            stage = f"start_{name}"
            log = (OUT / f"{name}-epoch-{epoch}.log").open("x", encoding="utf-8")
            logs.append(log)
            children.append(subprocess.Popen(
                command, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            ))
        runtime.update(
            backend_pid=children[0].pid,
            frontend_pid=children[1].pid,
            backend_started=process_started(children[0].pid),
            frontend_started=process_started(children[1].pid),
        )
        persist(OUT / "runtime-v2.json", runtime)
        stage = "service_health_check"
        with httpx.Client(trust_env=False, timeout=3, follow_redirects=False) as client:
            for _ in range(90):
                if any(child.poll() is not None for child in children):
                    raise RuntimeError("continuation_child_exited_check_logs")
                try:
                    response = client.get("http://127.0.0.1:63046/api/health")
                    if response.status_code == 200 and response.headers.get("x-naiwa-experience") == "naiwa-v3-20261022":
                        if response.json().get("database") != "connected":
                            raise RuntimeError("continuation_database_health_not_connected")
                        if read(OUT / "control.json").get("paid_enabled"):
                            raise RuntimeError("paid_control_must_be_closed_at_startup")
                        runtime.update(status="running", health=response.json())
                        persist(OUT / "runtime-v2.json", runtime)
                        stage = "acceptance_wait"
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(1)
            else:
                raise RuntimeError("continuation_startup_health_timeout")
        while not stop_path.exists():
            if any(child.poll() is not None for child in children):
                raise RuntimeError("continuation_child_exited_during_acceptance")
            time.sleep(1)
    except Exception as exc:
        failure = {"stage": stage, "error_type": type(exc).__name__}
        if runtime is not None:
            runtime.update(status="failed", failure=failure, failure_recorded_at=time.time())
            persist(OUT / "runtime-v2.json", runtime)
        raise
    finally:
        try:
            attach_paths()
            paid.gate().seal("v33_paid_continuation_stopped")
        except Exception:
            pass
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=25)
        for log in logs:
            log.close()
        if pg._owned_identity is not None:
            pg.stop()
        else:
            pg.lock.release()
        if runtime:
            runtime.update(status="failed" if failure else "stopped", stopped_at=time.time())
            if failure:
                runtime["failure"] = failure
            persist(OUT / "runtime-v2.json", runtime)


def open_scene(scene: str):
    attach_paths()
    validate_parent_ledger()
    paid.open_scene(scene)


def close_paid(reason="operator_closed"):
    attach_paths()
    paid.bind()
    legacy.close_paid(reason)


def stop():
    close_paid("v33_stop_requested")
    runtime = read(OUT / "runtime-v2.json")
    stop_path = Path(runtime["stop_request"])
    if stop_path.exists():
        raise RuntimeError("epoch_stop_request_already_exists")
    stop_path.write_text(str(time.time()), encoding="ascii")


def status():
    attach_paths()
    gate = paid.gate()
    runtime_path = OUT / "runtime-v2.json"
    runtime = read(runtime_path) if runtime_path.exists() else None
    observed = {"process_identity_matches": False, "process_checks": {}, "ports_listening": {}}
    if runtime and runtime.get("status") == "running":
        for name in ("supervisor", "backend", "frontend"):
            try:
                actual = process_started(runtime[f"{name}_pid"])
                observed["process_checks"][name] = actual == runtime[f"{name}_started"]
            except (OSError, KeyError, TypeError, ValueError):
                observed["process_checks"][name] = False
        observed["process_identity_matches"] = all(observed["process_checks"].values())
        for name, port in (("postgres", 63044), ("api", 63045), ("web", 63046)):
            with socket.socket() as probe:
                try:
                    observed["ports_listening"][name] = probe.connect_ex(("127.0.0.1", port)) == 0
                except OSError:
                    observed["ports_listening"][name] = False
    if runtime and runtime.get("status") == "running" and (
        not observed["process_identity_matches"] or not all(observed["ports_listening"].values())
    ):
        observed["effective_status"] = "stale_runtime_metadata"
    elif runtime:
        observed["effective_status"] = runtime.get("status")
    else:
        observed["effective_status"] = "not_started"
    print(json.dumps({
        "runtime": runtime,
        "observed_runtime": observed,
        "ledger_sha256": legacy.sha(LEDGER),
        "parent_ledger_sha256": legacy.sha(PARENT_LEDGER),
        "ledger_count": len(gate.records),
        "scene_counts": {scene: sum(row.get("case_id") == scene for row in gate.records) for scene in gate.scene_caps},
        "stop_reason": gate.stop_reason,
        "paid_enabled": read(OUT / "control.json").get("paid_enabled") if (OUT / "control.json").exists() else False,
    }, ensure_ascii=True, indent=2, default=str))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("prepare | serve | open SCENE | close | stop | status | record-revision PATH[,PATH...] REASON")
    action = sys.argv[1]
    if action == "prepare":
        prepare()
    elif action == "serve":
        serve()
    elif action == "open" and len(sys.argv) == 3:
        open_scene(sys.argv[2])
    elif action == "close":
        close_paid("v33_operator_closed")
    elif action == "stop":
        stop()
    elif action == "status":
        status()
    elif action == "record-revision" and len(sys.argv) >= 4:
        record_source_revision(sys.argv[2].split(","), " ".join(sys.argv[3:]))
    else:
        raise SystemExit("invalid continuation action")
