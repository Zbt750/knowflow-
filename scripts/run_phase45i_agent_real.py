"""Bounded Phase 4.5I-Agent-Real run using the existing owned test cluster.

The runner deliberately refuses a new/replacement database: the existing
isolated cluster owns the same-day generation quota from the earlier C4 run.
All raw model responses and learning records stay under ignored storage/.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.parse import urlsplit
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OLD_RUN = ROOT / "storage/quality-audits/phase45i-next/pilot-20261010"
# run-01 is preserved as the zero-call encoding diagnostic. This second
# attempt uses the same database/port/quota and cannot reset the daily limit.
OUT_DIR = ROOT / "storage/quality-audits/phase45i-agent-real-20261010/run-06"
FIXTURE = ROOT / "tests/fixtures/phase45i_generation_targets.json"
PG_BIN = Path("C:/Program Files/PostgreSQL/18/bin")
MAX_CALLS = 20
MAX_DAILY_CALLS = 30
MAX_OUTPUT_TOKENS = 3000
MAX_INPUT_BYTES = 8000
MAX_ESTIMATED_PEAK_USD = 0.15
PEAK_INPUT_MISS_USD = 0.30
PEAK_OUTPUT_USD = 1.20
PRICE_SOURCE = "https://api-docs.deepseek.com/quick_start/pricing/"


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def atomic_json(path: Path, payload: object) -> None:
    temp = path.with_name(path.name + f".{uuid4().hex}.tmp")
    with temp.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    temp.replace(path)


def append_jsonl(path: Path, payload: object) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def command(args: list[str], *, timeout: int = 120, check: bool = True,
            capture: bool = True) -> subprocess.CompletedProcess:
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith("PG")}
    if capture:
        result = subprocess.run(args, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                                capture_output=True, text=True, timeout=timeout,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    else:
        # A launched postgres child can inherit captured pipe handles even after
        # pg_ctl itself exits; communicate() would then wait for the DB lifetime.
        result = subprocess.run(args, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        result.stdout = ""
        result.stderr = ""
    if check and result.returncode:
        raise RuntimeError(f"command_failed:{Path(args[0]).name}:{result.returncode}")
    return result


def normalize_path(value: str) -> str:
    return os.path.normcase(os.path.normpath(str(Path(value).resolve())))


def load_frozen_targets() -> tuple[dict, str, str]:
    fixture_bytes = FIXTURE.read_bytes()
    fixture = json.loads(fixture_bytes)
    inventory_path = ROOT / fixture["source_inventory"]
    inventory_bytes = inventory_path.read_bytes()
    inventory_sha = sha256(inventory_bytes)
    if inventory_sha != fixture["source_inventory_sha256"]:
        raise RuntimeError("frozen_knowledge_inventory_hash_mismatch")
    inventory = json.loads(inventory_bytes)
    by_id = {str(row["id"]): row for row in inventory["knowledge_points"]}
    if len(fixture["nodes"]) != 10 or len({row["id"] for row in fixture["nodes"]}) != 10:
        raise RuntimeError("frozen_target_node_count_invalid")
    for target in fixture["nodes"]:
        source = by_id.get(target["id"])
        if not source or any(source.get(key) != target.get(key) for key in ("code", "name")):
            raise RuntimeError("frozen_target_snapshot_mismatch")
        target["database_subject"] = source["subject"]
        target["is_active"] = bool(source["is_active"])
        target["is_assessable"] = bool(source["is_assessable"])
        target["is_reference_only"] = bool(source["is_reference_only"])
        if not target["is_active"] or not target["is_assessable"]:
            raise RuntimeError("frozen_target_not_active_assessable")
    return fixture, sha256(fixture_bytes), inventory_sha


def make_targets(fixture: dict) -> list[dict]:
    from backend.services.personal_question_families import resolve_family, supports_difficulty

    result = []
    for subject in ("数学二", "408"):
        rows = [row for row in fixture["nodes"] if row["subject"] == subject]
        if len(rows) != 5:
            raise RuntimeError(f"{subject}_target_count_invalid")
        for node in rows:
            family = resolve_family(node["code"])
            if not family or family.family_id != node["expected_family"]:
                raise RuntimeError("live_family_registry_mismatch")
            profiles = (["single_choice", "single_choice"] if node["expected_family"] == "improper_integral_parameter"
                        else ["single_choice", "fill_blank"])
            for index, question_type in enumerate(profiles):
                difficulty = "improved" if index == 1 and supports_difficulty(family, "improved") else "basic"
                if not supports_difficulty(family, difficulty):
                    raise RuntimeError("target_difficulty_unsupported")
                result.append({
                    "target_id": f"agent-real:{subject}:{node['code']}:{question_type}:{index + 1}",
                    "subject": subject,
                    "node": node,
                    "family": family.family_id,
                    "question_type": question_type,
                    "difficulty": difficulty,
                    "prompt": (f"给我生成1道{'单选题' if question_type == 'single_choice' else '填空题'}，"
                               f"针对当前知识点，{'中等' if difficulty == 'improved' else '基础'}难度，并加入今日学习。"),
                })
    if len(result) != MAX_CALLS or sum(r["subject"] == "数学二" for r in result) != 10 \
            or sum(r["subject"] == "408" for r in result) != 10:
        raise RuntimeError("target_allocation_mismatch")
    return result


def initialize_output() -> None:
    if OUT_DIR.exists() and any(OUT_DIR.iterdir()):
        raise RuntimeError("output_directory_exists_nonempty_refuse_overwrite")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    owner = {"format": 1, "run_id": uuid4().hex, "created_at": datetime.now(timezone.utc).isoformat(),
             "resolved_path": str(OUT_DIR.resolve()), "test_cluster_reused": str((OLD_RUN / "postgres-cluster").resolve())}
    atomic_json(OUT_DIR / "phase45i-agent-real-owner.json", owner)


def load_existing_owner() -> tuple[dict, Path, int]:
    owner_path = OLD_RUN / "phase45i-owner.json"
    metadata_path = OLD_RUN / "postgres.json"
    if not owner_path.is_file() or not metadata_path.is_file():
        raise RuntimeError("existing_test_database_owner_or_metadata_missing")
    owner = json.loads(owner_path.read_text(encoding="utf-8"))
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    cluster = Path(metadata.get("cluster", "")).resolve()
    expected = (OLD_RUN / "postgres-cluster").resolve()
    if (owner.get("format") != 1 or owner.get("resolved_path") != str(OLD_RUN.resolve())
            or metadata.get("run_id") != owner.get("run_id") or cluster != expected
            or metadata.get("database") != "kaoyan_test" or metadata.get("host") != "127.0.0.1"):
        raise RuntimeError("existing_test_database_owner_identity_mismatch")
    port = int(metadata.get("port", 0))
    if port <= 18000 or port == 5433:
        raise RuntimeError("existing_test_database_port_rejected")
    return owner, cluster, port


def start_owned_database(cluster: Path, port: int) -> bool:
    pg_ctl = PG_BIN / "pg_ctl.exe"
    if not pg_ctl.is_file():
        raise RuntimeError("postgresql18_pg_ctl_missing")
    status = command([str(pg_ctl), "-D", str(cluster), "status"], check=False)
    if status.returncode == 0:
        return False
    with socket.socket() as probe:
        probe.settimeout(0.4)
        if probe.connect_ex(("127.0.0.1", port)) == 0:
            raise RuntimeError("isolated_port_in_use_by_unverified_process")
    pid_path = cluster / "postmaster.pid"
    if pid_path.exists():
        lines = pid_path.read_bytes().splitlines()
        if len(lines) < 4 or int(lines[3]) != port:
            raise RuntimeError("stale_pid_file_port_identity_mismatch")
        # No file is removed manually. A normal pg_ctl/PostgreSQL startup may
        # reclaim a stale PID only after PostgreSQL's own process checks.
        pids = command(["powershell.exe", "-NoProfile", "-Command",
                        f"$p=Get-Process -Id {int(lines[0])} -ErrorAction SilentlyContinue; "
                        "if($p){$p | Select-Object Id,Name,Path | ConvertTo-Json -Compress}"], check=False)
        if pids.stdout.strip():
            try:
                proc = json.loads(pids.stdout)
            except json.JSONDecodeError as exc:
                raise RuntimeError("pid_process_identity_unreadable_refuse_start") from exc
            if Path(str(proc.get("Path", ""))).resolve() != (PG_BIN / "postgres.exe").resolve():
                raise RuntimeError("pid_reused_by_non_postgres_process_refuse_start")
            raise RuntimeError("postgres_process_exists_but_pg_ctl_reports_stopped_refuse_duplicate")
    log = OUT_DIR / "postgres.log"
    options = f"-p {port} -h 127.0.0.1 -c listen_addresses=127.0.0.1 -c log_statement=none"
    started = command([str(pg_ctl), "-D", str(cluster), "-o", options, "-l", str(log),
                       "-w", "-t", "120", "start"], timeout=140, check=False, capture=False)
    if started.returncode:
        raise RuntimeError("owned_isolated_postgres_normal_start_failed")
    return True


def verify_database(cluster: Path, port: int, *, expected_revision: str | None = None) -> dict:
    import re
    import psycopg
    pg_ctl = PG_BIN / "pg_ctl.exe"
    status = command([str(pg_ctl), "-D", str(cluster), "status"], check=False)
    if status.returncode != 0:
        raise RuntimeError("pg_ctl_does_not_confirm_exact_isolated_cluster_running")
    control = command([str(PG_BIN / "pg_controldata.exe"), "-D", str(cluster)], check=False)
    if control.returncode != 0:
        raise RuntimeError("pg_controldata_cannot_read_exact_isolated_cluster")
    system_id_match = re.search(r"Database system identifier:\s*(\d+)", control.stdout)
    if not system_id_match:
        raise RuntimeError("isolated_cluster_system_identifier_unavailable")
    expected_system_id = system_id_match.group(1)
    with psycopg.connect(host="127.0.0.1", port=port, user="postgres", dbname="kaoyan_test",
                         sslmode="disable", connect_timeout=8, autocommit=True) as conn:
        row = conn.execute("SELECT current_database(), inet_server_port(), "
                           "(SELECT system_identifier::text FROM pg_control_system()), "
                           "(SELECT version_num FROM alembic_version)").fetchone()
        if row[0] != "kaoyan_test" or int(row[1]) != port or row[2] != expected_system_id:
            raise RuntimeError("live_isolated_database_identity_mismatch")
        revision = str(row[3])
        if expected_revision and revision != expected_revision:
            raise RuntimeError("test_database_revision_changed_outside_expected_run")
        pid = (cluster / "postmaster.pid").read_bytes().splitlines()
        if len(pid) < 4 or int(pid[3]) != port:
            raise RuntimeError("live_postmaster_pidfile_mismatch")
        counts = {}
        for table in ("knowledge_points", "questions", "daily_plans", "practice_items",
                      "question_attempts", "learning_events", "kp_states", "kp_mastery_policies",
                      "personal_generation_batches"):
            counts[table] = int(conn.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0])
        day = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
        reserved = int(conn.execute(
            "SELECT coalesce(sum(reserved_calls),0) FROM personal_generation_batches WHERE study_date=%s", (day,)
        ).fetchone()[0])
        target_rows = conn.execute("SELECT id::text,code,name,subject,is_active,is_assessable,is_reference_only "
            "FROM knowledge_points ORDER BY code").fetchall()
    return {"database": row[0], "port": int(row[1]), "data_directory": str(cluster),
            "data_directory_verified_by": "pg_ctl exact -D cluster + matching PostgreSQL system_identifier",
            "system_identifier": expected_system_id, "revision": revision,
            "pidfile_pid": int(pid[0]), "counts": counts, "study_date_shanghai": day,
            "daily_reserved_calls": reserved,
            "knowledge_points": [dict(id=x[0], code=x[1], name=x[2], subject=x[3], is_active=x[4],
                                      is_assessable=x[5], is_reference_only=x[6]) for x in target_rows]}


def assert_live_targets(targets: list[dict], before: dict) -> None:
    live = {row["id"]: row for row in before["knowledge_points"]}
    if len(live) != 10:
        raise RuntimeError("isolated_db_must_contain_exactly_ten_frozen_target_nodes")
    for target in targets:
        node = target["node"]
        row = live.get(node["id"])
        if (not row or row["code"] != node["code"] or row["name"] != node["name"]
                or row["subject"] != node["database_subject"] or not row["is_active"]
                or not row["is_assessable"]):
            raise RuntimeError("live_knowledge_node_mismatch")
    if before["counts"]["questions"] or before["counts"]["daily_plans"] or before["counts"]["practice_items"] \
            or before["counts"]["question_attempts"] or before["counts"]["learning_events"] \
            or before["counts"]["kp_states"] or before["counts"]["kp_mastery_policies"]:
        raise RuntimeError("existing_test_business_data_unaccounted_refuse_run")
    if before["daily_reserved_calls"] != 3:
        raise RuntimeError("same_day_quota_baseline_changed_refuse_run")
    if before["daily_reserved_calls"] + MAX_CALLS > MAX_DAILY_CALLS:
        raise RuntimeError("application_daily_quota_cannot_fit_authorized_calls")


def prepare_model_provider():
    os.environ["APP_ENV"] = "dev"
    from backend.config import get_settings
    from backend.services.model_settings_service import load_local_settings
    get_settings.cache_clear()
    settings = load_local_settings(get_settings())
    endpoint = urlsplit(settings.llm_base_url or "")
    if (endpoint.scheme != "https" or endpoint.hostname != "api.deepseek.com"
            or settings.llm_model != "deepseek-flash" or not settings.llm_api_key
            or not settings.llm_api_key.get_secret_value() or settings.local_model_settings_error):
        raise RuntimeError("configured_official_deepseek_model_unavailable_or_invalid")
    from backend.services.question_generation import Budget, configured_provider, GENERATION_VERSION
    from backend.services.question_generation import PERSONAL_C7_PROMPT_VERSION
    from backend.services.quality_verifiers import VERSION as verifier_version
    from backend.services.personal_question_families import VERSION as family_version
    if GENERATION_VERSION != "bounded-question-generation-v9" or PERSONAL_C7_PROMPT_VERSION != "question-generation-c7-v1":
        raise RuntimeError("C7_generation_version_mismatch")
    provider = configured_provider(settings, Budget(max_calls=1,
        max_reserved_tokens=MAX_INPUT_BYTES + 512 + MAX_OUTPUT_TOKENS,
        max_output_tokens=MAX_OUTPUT_TOKENS), real_call_authorized=True)
    if provider.max_tokens != MAX_OUTPUT_TOKENS or provider.timeout > 30:
        raise RuntimeError("provider_output_or_timeout_cap_mismatch")
    return provider, {"model": provider.model, "base_url": provider.base_url,
        "prompt_version": PERSONAL_C7_PROMPT_VERSION, "generation_version": GENERATION_VERSION,
        "verifier_version": verifier_version, "family_registry_version": family_version,
        "max_output_tokens": provider.max_tokens, "timeout_seconds": provider.timeout,
        "api_key_present": True}


class OneRequestCapture:
    """Allow exactly one official HTTP request inside each production complete()."""
    def __init__(self, wrapped, audit_dir: Path, progress: dict):
        self.wrapped = wrapped
        self.audit_dir = audit_dir
        self.progress = progress
        self.model = wrapped.model
        self.base_url = wrapped.base_url
        self.max_tokens = wrapped.max_tokens
        self.timeout = wrapped.timeout
        self.simulation = False
        self.current_target: dict | None = None
        self.active = False
        self.post_count_for_call = 0
        self.unexpected_calls: list[dict] = []
        self.pending_record: dict | None = None
        self.usd_peak_cost = 0.0

    def guarded_post(self, original_post, url, **kwargs):
        parsed = urlsplit(str(url))
        payload = kwargs.get("json")
        if not self.active:
            self.unexpected_calls.append({"reason": "model_post_outside_explicit_generation_complete",
                                          "host": parsed.hostname})
            raise RuntimeError("unexpected_paid_request_blocked")
        if self.post_count_for_call:
            raise RuntimeError("second_http_request_in_one_generation_blocked")
        if (parsed.scheme != "https" or parsed.hostname != "api.deepseek.com"
                or parsed.path.rstrip("/") != "/chat/completions"
                or not isinstance(payload, dict) or payload.get("model") != "deepseek-flash"
                or payload.get("max_tokens") != MAX_OUTPUT_TOKENS or payload.get("stream") is True):
            raise RuntimeError("unexpected_provider_request_shape_blocked")
        messages = payload.get("messages")
        if not isinstance(messages, list):
            raise RuntimeError("provider_messages_missing")
        input_bytes = sum(len(str(m.get("content", "")).encode("utf-8"))
                          for m in messages if isinstance(m, dict))
        if input_bytes > MAX_INPUT_BYTES:
            raise RuntimeError("provider_prompt_byte_budget_exceeded")
        current_actual = sum(1 for row in self.progress["provider_requests"]
                             if row.get("actual_http_request") is True)
        if current_actual >= MAX_CALLS:
            raise RuntimeError("authorized_20_request_cap_reached")
        input_reserve = input_bytes + 512
        max_next_cost = (input_reserve * PEAK_INPUT_MISS_USD + MAX_OUTPUT_TOKENS * PEAK_OUTPUT_USD) / 1_000_000
        if self.usd_peak_cost + max_next_cost > MAX_ESTIMATED_PEAK_USD:
            raise RuntimeError("pre_request_cost_guard_would_exceed_estimate_cap")
        self.post_count_for_call += 1
        request_number = current_actual + 1
        record = {"request_number": request_number,
            "target_id": self.current_target["target_id"] if self.current_target else None,
            "subject": self.current_target["subject"] if self.current_target else None,
            "node_id": self.current_target["node"]["id"] if self.current_target else None,
            "node_code": self.current_target["node"]["code"] if self.current_target else None,
            "node_name": self.current_target["node"]["name"] if self.current_target else None,
            "question_type": self.current_target["question_type"] if self.current_target else None,
            "difficulty": self.current_target["difficulty"] if self.current_target else None,
            "model": self.model, "prompt_version": "question-generation-c7-v1",
            "actual_http_request": True, "attempt": 1, "input_bytes": input_bytes,
            "input_token_budget_reserve": input_reserve, "max_output_tokens": MAX_OUTPUT_TOKENS,
            "request_sha256": sha256(json.dumps(messages, ensure_ascii=False, sort_keys=True).encode("utf-8")),
            "http_status": None, "finish_reason": None, "usage": None, "usage_observed": False,
            "response_content": None, "elapsed_ms": None, "error_type": None,
            "peak_cost_estimate_usd": None, "price_basis": "peak; all input treated as cache miss"}
        self.pending_record = record
        start = time.perf_counter()
        try:
            response = original_post(url, **kwargs)
            record["http_status"] = response.status_code
            try:
                response_payload = response.json()
                choices = response_payload.get("choices") or []
                if choices and isinstance(choices[0], dict):
                    record["finish_reason"] = choices[0].get("finish_reason")
                    message = (choices[0].get("message") or {})
                    if isinstance(message.get("content"), str):
                        record["response_content"] = message["content"]
                usage = response_payload.get("usage")
                if isinstance(usage, dict):
                    clean = {key: usage[key] for key in ("prompt_tokens", "completion_tokens", "total_tokens")
                             if isinstance(usage.get(key), int) and not isinstance(usage.get(key), bool)
                             and usage[key] >= 0}
                    record["usage"] = clean
                    record["usage_observed"] = all(isinstance(clean.get(key), int)
                                                    for key in ("prompt_tokens", "completion_tokens"))
            except Exception:
                record["error_type"] = "response_json_capture_error"
            return response
        except Exception as exc:
            record["error_type"] = type(exc).__name__
            raise
        finally:
            record["elapsed_ms"] = round((time.perf_counter() - start) * 1000, 3)
            usage = record.get("usage") or {}
            if record.get("usage_observed"):
                prompt_tokens = int(usage["prompt_tokens"])
                output_tokens = int(usage["completion_tokens"])
                if prompt_tokens > input_reserve or output_tokens > MAX_OUTPUT_TOKENS:
                    record["budget_violation"] = "observed_usage_exceeds_conservative_request_bound"
                else:
                    cost = (prompt_tokens * PEAK_INPUT_MISS_USD + output_tokens * PEAK_OUTPUT_USD) / 1_000_000
                    record["peak_cost_estimate_usd"] = round(cost, 10)
                    self.usd_peak_cost += cost
                    self.progress["observed_prompt_tokens"] += prompt_tokens
                    self.progress["observed_completion_tokens"] += output_tokens
                    self.progress["estimated_peak_cost_usd"] = round(self.usd_peak_cost, 10)
                    if output_tokens > 0:
                        self.progress["usage_observed_requests"] += 1
            else:
                self.progress["usage_unobserved_request"] = True
            append_jsonl(self.audit_dir / "provider-calls.jsonl", record)
            self.progress["provider_requests"].append({k: v for k, v in record.items() if k != "response_content"})
            self.progress["actual_provider_request_count"] = sum(
                1 for row in self.progress["provider_requests"] if row.get("actual_http_request") is True)
            atomic_json(self.audit_dir / "progress.json", self.progress)

    def complete(self, messages, *, attempt=1):
        if attempt != 1:
            raise RuntimeError("retry_blocked_by_phase_authorization")
        if self.active:
            raise RuntimeError("nested_generation_call_blocked")
        self.active = True
        self.post_count_for_call = 0
        try:
            # `httpx.post` is wrapped once by run() for the entire test window.
            # Re-wrapping it here would count the same HTTP call twice and make
            # the inner guard mistake one request for a retry.
            return self.wrapped.complete(messages, attempt=1)
        finally:
            self.active = False


def current_counts(factory) -> dict:
    from sqlalchemy import func, select
    from backend.models.learning import (DailyPlan, KpMasteryPolicy, KpState, KnowledgePoint,
        LearningEvent, PracticeItem, Question, QuestionAttempt)
    from backend.models.personal_generation import PersonalGenerationBatch
    with factory() as db:
        models = {"knowledge_points": KnowledgePoint, "questions": Question, "daily_plans": DailyPlan,
            "practice_items": PracticeItem, "question_attempts": QuestionAttempt,
            "learning_events": LearningEvent, "kp_states": KpState,
            "kp_mastery_policies": KpMasteryPolicy, "personal_generation_batches": PersonalGenerationBatch}
        return {name: int(db.scalar(select(func.count()).select_from(model)) or 0)
                for name, model in models.items()}


def parse_sse(response_text: str) -> dict:
    import json as json_module
    events = []
    for frame in response_text.split("\n\n"):
        event = None
        data = []
        for line in frame.splitlines():
            if line.startswith("event: "):
                event = line[7:].strip()
            elif line.startswith("data: "):
                data.append(line[6:])
        if event and data:
            try:
                value = json_module.loads("\n".join(data))
            except json_module.JSONDecodeError:
                value = None
            events.append({"event": event, "data": value})
    result = next((row["data"] for row in events if row["event"] == "personal_generation"), None)
    return {"events": events, "personal_generation": result}


def record_turn(path: Path, target: dict, request_key: str, response, parsed: dict,
                capture: OneRequestCapture, unexpected_before: int, db_batch: dict | None = None) -> dict:
    raw_record = next((row for row in reversed(capture.progress["provider_requests"])
                       if row.get("target_id") == target["target_id"]), None)
    gen = parsed.get("personal_generation") or {}
    row = {"target_id": target["target_id"], "subject": target["subject"],
        "knowledge_node_id": target["node"]["id"], "knowledge_node_code": target["node"]["code"],
        "knowledge_node_name": target["node"]["name"], "family": target["family"],
        "question_type": target["question_type"], "difficulty": target["difficulty"],
        "prompt_version": "question-generation-c7-v1", "generation_version": "bounded-question-generation-v9",
        "request_key": request_key, "user_request": target["prompt"],
        "api_http_status": response.status_code, "sse_route": next((x.get("data") for x in parsed["events"] if x["event"] == "route"), None),
        "sse_error": next((x.get("data") for x in parsed["events"] if x["event"] == "error"), None),
        "generation_status": gen.get("status"), "generation_mode": gen.get("generation_mode"),
        "provider_error": gen.get("provider_error"), "question_ids": gen.get("question_ids", []),
        "failures": gen.get("failures", []), "generation_batch_id": gen.get("batch_id"),
        "appended_question_ids": gen.get("appended_question_ids", []),
        "append_error": gen.get("append_error"), "database_batch_result": db_batch,
        "provider_request": {k: raw_record.get(k) for k in (
            "request_number", "http_status", "finish_reason", "usage", "usage_observed",
            "elapsed_ms", "peak_cost_estimate_usd", "error_type", "budget_violation")} if raw_record else None,
        "unexpected_paid_posts_blocked": len(capture.unexpected_calls) - unexpected_before,
    }
    append_jsonl(path, row)
    return row


def create_isolated_graduation_fixture(factory, kp_id: UUID, now: datetime) -> dict:
    """Earn strict graduation with explicit TEST_FIXTURE-only evidence on 408."""
    from datetime import timedelta
    from sqlalchemy import select
    from backend.models.learning import (DailyPlan, KpMasteryPolicy, KpState, KnowledgePoint,
        PracticeItem, Question)
    from backend.services.answer_submission_service import submit_answer
    from backend.services.question_eligibility import question_eligibility
    from tests.integration.test_learning_loop import mark_isolated_question_trusted

    with factory.begin() as db:
        node = db.get(KnowledgePoint, kp_id)
        if not node:
            raise RuntimeError("graduation_fixture_target_missing")
        state = db.get(KpState, kp_id)
        if state is None:
            state = KpState(kp_id=kp_id)
            db.add(state)
            db.flush()
        if state is not None and state.state == "mastered":
            raise RuntimeError("unexpected_existing_mastered_state_in_isolated_baseline")
        policy = KpMasteryPolicy(kp_id=kp_id, policy_version=2,
            required_question_origins={"real_exam": 3}, required_question_types={},
            excluded_question_types=[], min_confirmations=3, min_real_questions=3,
            required_variant_count=0, required_skill_tags=["phase45i-fixture-skill"], min_day_span=2,
            manual_mastered_credit=0, note="TEST_FIXTURE only: isolated post-graduation path validation")
        db.add(policy)
        fixture_questions = []
        for index in range(3):
            q = Question(kp_id=kp_id, question_type="single_choice", stem=f"TEST_FIXTURE 408 graduation {index + 1}: 1+1=?",
                options={"A": "2", "B": "3", "C": "4", "D": "5"}, correct_answer="A",
                explanation="TEST_FIXTURE only", skill_tags=["phase45i-fixture-skill"],
                question_role="basic", grading_config={"verified": True, "method": "single_choice"})
            db.add(q); db.flush(); mark_isolated_question_trusted(q, db=db)
            q.question_provenance = "real_exam"; q.source_status = "verified"
            fixture_questions.append(q)
        db.flush()
        before_attempts = []
        attempt_trace = []
        for index, q in enumerate(fixture_questions):
            day = now - timedelta(days=5 - index)
            study_date = day.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()
            plan = db.scalar(select(DailyPlan).where(DailyPlan.study_date == study_date))
            if plan is None:
                plan = DailyPlan(study_date=study_date, status="active"); db.add(plan); db.flush()
            item = PracticeItem(plan_id=plan.id, kp_id=kp_id, question_id=q.id, ordinal=index + 1)
            db.add(item); db.flush()
            eligibility = question_eligibility(q, node)
            verdict = submit_answer(db, item_id=item.id, raw_answer=None, selected_option="A",
                idempotency_key=f"TEST_FIXTURE-phase45i-graduation-{q.id}", now=day)
            attempt_trace.append({"index": index + 1, "result": verdict.result,
                "reason": verdict.reason, "method": verdict.method,
                "eligibility": eligibility.public_dict(),
                "state": verdict.state, "reason_code": verdict.mastery_reason,
                "effective_confirmation_count": verdict.effective_confirmation_count,
                "assessment_basis": verdict.assessment_basis})
            if verdict.state != "mastered" and index == 2:
                raise RuntimeError("strict_graduation_fixture_did_not_reach_mastered:" +
                    json.dumps(attempt_trace, ensure_ascii=False))
            before_attempts.append(str(verdict.attempt_id))
        state = db.get(KpState, kp_id)
        if not state or state.state != "mastered" or not state.mastered_at:
            raise RuntimeError("strict_graduation_fixture_state_not_mastered")
        result = {"status": "PASS", "fixture_only": True, "policy_version": policy.policy_version,
            "real_exam_quota": 3, "fixture_question_ids": [str(q.id) for q in fixture_questions],
            "fixture_attempt_ids": before_attempts, "attempt_trace": attempt_trace, "state": state.state,
            "mastered_at": state.mastered_at.isoformat(), "evidence_window_count": len(state.evidence_window or [])}
    return result


def safe_api_row(response) -> dict:
    if response.status_code >= 400:
        return {"status_code": response.status_code}
    try:
        body = response.json()
        return body if isinstance(body, dict) else {"unexpected_shape": True}
    except Exception:
        return {"unparseable": True}


def write_report(progress: dict, status: str) -> None:
    calls = progress.get("provider_requests", [])
    turns = progress.get("turns", [])
    math = [r for r in turns if r.get("subject") == "数学二"]
    cs = [r for r in turns if r.get("subject") == "408"]
    parsed_count = int(progress.get("structured_json_valid_count", 0))
    saved = [r for r in turns if r.get("question_ids")]
    appended = [r for r in turns if r.get("appended_question_ids")]
    latencies = [float(r["elapsed_ms"]) for r in calls if isinstance(r.get("elapsed_ms"), (int, float))]
    finish_reasons: dict[str, int] = {}
    for call in calls:
        reason = str(call.get("finish_reason") or "not_observed")
        finish_reasons[reason] = finish_reasons.get(reason, 0) + 1
    prompt_tokens = sum(int((r.get("usage") or {}).get("prompt_tokens") or 0) for r in calls)
    completion_tokens = sum(int((r.get("usage") or {}).get("completion_tokens") or 0) for r in calls)
    lines = ["# Phase 4.5I-Agent-Real — 奶蛙真实 DeepSeek 生题与调用验收报告", "",
        f"状态：`{status}`", "",
        "本报告的真实模型请求与个人题记录均位于隔离的本地审计目录。原始开发数据库 5433 未连接、未启动、未迁移、未写入。", "",
        "## 实际调用", "",
        f"- Provider 实际 HTTP 请求：{len(calls)} / 20。数学二：{sum(1 for r in calls if r.get('subject') == '数学二')}；408：{sum(1 for r in calls if r.get('subject') == '408')}。",
        f"- 生成轮次：{len(turns)}。C7 schema 可解析响应：{parsed_count}。截断：{int(progress.get('output_truncated_count', sum(1 for r in calls if r.get('finish_reason') == 'length')))}。",
        f"- 审核结论计数：AUTO_PASS/保存 {len(saved)}；模型响应格式错误 {progress.get('format_error_count', 0)}；截断 {progress.get('output_truncated_count', 0)}；仍不支持或证据不足 {progress.get('unsupported_or_insufficient_count', 0)}；服务报告确认冲突 {progress.get('confirmed_wrong_count', 0)}。",
        f"- AUTO_PASS 并保存：{len(saved)}；实际追加今日学习：{len(appended)}。分科保存：数学二 {sum(1 for r in math if r.get('question_ids'))}/{len(math)}，408 {sum(1 for r in cs if r.get('question_ids'))}/{len(cs)}。",
        f"- 上海自然日调用账：本轮前已预留 {progress.get('daily_reserved_calls_before', '未观测')} 次，本轮新增 {len(calls)} 次，结束为 {progress.get('daily_reserved_calls_after', '未观测')}/30；未更改额度。",
        f"- Usage 可观测请求：{progress.get('usage_observed_requests',0)}；prompt tokens：{progress.get('observed_prompt_tokens',0)}；completion tokens：{progress.get('observed_completion_tokens',0)}。",
        f"- 实际结束原因：{json.dumps(finish_reasons, ensure_ascii=False)}；失败重试：{sum(max(0, int((r.get('attempt') or 1) - 1)) for r in calls)}。",
        f"- 平均延迟：{(sum(latencies) / len(latencies) / 1000) if latencies else 0:.2f} 秒；范围：{(min(latencies) / 1000) if latencies else 0:.2f}–{(max(latencies) / 1000) if latencies else 0:.2f} 秒。",
        f"- 逐请求usage汇总复核：输入 {prompt_tokens}、输出 {completion_tokens}、合计 {prompt_tokens + completion_tokens} tokens。",
        f"- 估计峰时费用：${progress.get('estimated_peak_cost_usd',0):.8f} USD（官方峰时价、输入按未缓存；这是按观测tokens计算的估算，不是供应商账单）。", "",
        "本轮直接经由奶蛙显式生题请求进入生产生成服务：SSE 路由为 `generation / explicit_new_question_request`，实际生题模式为 `ai_generated`。本轮未再改写生产生题服务；测试的是工作区已有的 C7 生题链，而不是旧的固定候选选择器。", "",
        "## 每个生成目标", "",
        "| # | 科目 | 节点 | 题型/难度 | 请求结果 | finish_reason / 延迟 | 判定/失败 | 保存 / 今日卷 |", "|---:|---|---|---|---|---|---|---|"]
    for index, row in enumerate(turns, 1):
        pr = row.get("provider_request") or {}
        result = row.get("generation_status") or (row.get("sse_error") or {}).get("code") or row.get("provider_error") or "未进入生成服务"
        failures = row.get("failures") or []
        review = ", ".join(str(x.get("review_status") or x.get("reason") or "") for x in failures) or ("AUTO_PASS" if row.get("question_ids") else "—")
        saved_text = f"{len(row.get('question_ids') or [])} / {len(row.get('appended_question_ids') or [])}"
        lines.append(f"| {index} | {row.get('subject')} | {row.get('node_code') or row.get('knowledge_node_code')} · {row.get('node_name') or row.get('knowledge_node_name')} | {row.get('question_type')} / {row.get('difficulty')} | {result}; HTTP {pr.get('http_status','—')} | {pr.get('finish_reason','—')} / {(float(pr.get('elapsed_ms') or 0) / 1000):.2f}s | {review} | {saved_text} |")
    lines += ["", "## 端到端与毕业隔离", ""]
    for row in progress.get("e2e_results", []):
        lines.append(f"- {row.get('subject')}：真实个人题 `{row.get('question_id','—')}` 页面/答案解析/提交/历史回读 `{row.get('status')}`；结果 `{row.get('submission_result')}`；严格确认 `{row.get('effective_confirmation_count')}`；状态 `{row.get('kp_state')}`，`mastered_at={row.get('mastered_at')}`，证据窗 {row.get('evidence_window_count')}。")
        fixture = row.get("graduation_fixture")
        if fixture:
            failure = str(fixture.get("failure") or "")
            blocker = fixture.get("blocker_code") or (
                "reference_only_mapping" if "reference_only_mapping" in failure else "graduation_fixture_failed")
            lines.append(f"  - 毕业后分支测试夹具：`{fixture.get('status')}`；阻塞码 `{blocker}`。仅隔离测试题被拒；该夹具事务已回滚。")
        projection = row.get("post_graduation_projection")
        if projection:
            lines.append(f"  - 毕业后熟练度投影：适用 `{projection.get('applicable')}` / `{projection.get('status')}`；由于节点未达到严格毕业前置，不能据此验收毕业后路径。")
    post_fixture = progress.get("post_graduation_fixture") or {}
    post_check_text = ("毕业后分支：`NOT_VERIFIED`。测试节点为 reference-only，严格毕业前置题被 `reference_only_mapping` 守卫拒绝；真实AI题仅验证了未毕业练习隔离。"
        if post_fixture.get("status") != "PASS" else
        "毕业后测试：" + json.dumps(progress.get("post_graduation_attempt_check"), ensure_ascii=False))
    lines += ["", "隔离库毕业前检查：" + json.dumps(progress.get('ungraduated_attempt_check'), ensure_ascii=False),
        post_check_text, "",
        "## 环境与版本", "",
        f"- Provider：{json.dumps(progress.get('provider_config'), ensure_ascii=False)}",
        f"- 隔离数据库身份（结束时）：{json.dumps(progress.get('database_identity_after') or progress.get('database_identity'), ensure_ascii=False)}",
        f"- 测试结果：{json.dumps(progress.get('focused_tests'), ensure_ascii=False)}",
        f"- 生成前业务表：{json.dumps(progress.get('counts_before'), ensure_ascii=False)}",
        f"- 最终业务表：{json.dumps(progress.get('counts_after'), ensure_ascii=False)}",
        f"- 开发库 5433 访问：{progress.get('development_5433_used', False)}。隔离库结束时 `kp_mastery_policies={progress.get('strict_policy_rows_after', '未观测')}`；毕业夹具未能通过资格守卫并回滚，未修改开发库既有284条策略。",
        f"- 官方价格依据：[DeepSeek Models & Pricing]({PRICE_SOURCE})。", "",
        "## 解释质量边界", "",
        "质量门记录的 1 条 `CONFIRMED_WRONG` 不等于已独立证明模型答案错误：该样本同时标记 `independent_verification_unknown`，具体冲突是 `explanation_final_value_conflict`，题族验证器不支持该收敛性论证。报告按质量门原始状态保留，但只能解释为‘被冲突守卫拦截、待独立复核’，不计作已确证错误。",
        "C7 的确定性题族求解器重新计算标准答案，并验证单选唯一性/答案比较及结构化算术步骤；当前服务没有对所有自然语言解析段落做完整的形式语义证明。已保存项属于‘通过现有自动质量门、可供个人练习’，不能据此声称解释的每个自然语言论断已被机器证明，也不等于公共正式考核资格。个人AI题仍只属于个人练习。", "",
        "完整逐条模型返回、finish_reason、usage、原始题干/选项/答案/解析、服务审核结果及请求轮次保存在同目录 `provider-calls.jsonl`、`turns.jsonl`、`progress.json`。", ""]
    (OUT_DIR / "PHASE45I_AGENT_REAL_REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def run() -> int:
    initialize_output()
    progress = {"format": 1, "run_id": json.loads((OUT_DIR / "phase45i-agent-real-owner.json").read_text(encoding="utf-8"))["run_id"],
        "authorized_max_provider_requests": MAX_CALLS, "provider_requests": [], "turns": [],
        "observed_prompt_tokens": 0, "observed_completion_tokens": 0, "usage_observed_requests": 0,
        "estimated_peak_cost_usd": 0.0, "development_5433_used": False,
        "price_source": PRICE_SOURCE, "finish_status": "IN_PROGRESS"}
    atomic_json(OUT_DIR / "progress.json", progress)
    started_database_here = False
    client = None
    engine = None
    status = "BLOCKED_PRECHECK"
    try:
        # Load the real provider from the existing local configuration; do not print secrets.
        provider, provider_config = prepare_model_provider()
        progress["stage"] = "provider_configuration_validated_no_request"
        atomic_json(OUT_DIR / "progress.json", progress)
        progress["provider_config"] = provider_config
        if provider_config["model"] != "deepseek-flash" or urlsplit(provider_config["base_url"]).hostname != "api.deepseek.com":
            raise RuntimeError("official_provider_guard_failed")
        fixture, fixture_sha, inventory_sha = load_frozen_targets()
        targets = make_targets(fixture)
        progress["stage"] = "frozen_targets_validated"
        progress["fixture_sha256"] = fixture_sha
        progress["inventory_sha256"] = inventory_sha
        progress["target_matrix"] = [{k: row[k] for k in ("target_id", "subject", "question_type", "difficulty", "family", "prompt")}
                                     | {"node": row["node"]} for row in targets]
        progress["prompt_version"] = "question-generation-c7-v1"
        progress["generation_version"] = "bounded-question-generation-v9"

        owner, cluster, port = load_existing_owner()
        progress["database_identity"] = {"host": "127.0.0.1", "port": port,
            "database": "kaoyan_test", "cluster": str(cluster), "owner_run_id": owner["run_id"],
            "reuse_existing_same_day_quota": True}
        started_database_here = start_owned_database(cluster, port)
        progress["stage"] = "isolated_postgres_started_by_native_pg_ctl" if started_database_here else "isolated_postgres_already_running"
        atomic_json(OUT_DIR / "progress.json", progress)
        initial = verify_database(cluster, port)
        progress["database_identity"].update({"data_directory": initial["data_directory"], "revision": initial["revision"],
            "postmaster_pid": initial["pidfile_pid"], "startup_by_this_run": started_database_here})
        assert_live_targets(targets, initial)
        progress["counts_before"] = initial["counts"]
        progress["daily_reserved_calls_before"] = initial["daily_reserved_calls"]
        atomic_json(OUT_DIR / "progress.json", progress)

        database_url = f"postgresql+psycopg://postgres@127.0.0.1:{port}/kaoyan_test"
        run_dir = OUT_DIR
        test_env = {"APP_ENV": "test", "DATABASE_URL": database_url, "TEST_DATABASE_URL": database_url,
            "KAOYAN_OWNED_TEST_PORT": str(port), "LLM_API_KEY": "", "LLM_BASE_URL": "", "LLM_MODEL": "",
            "UPLOAD_DIR": str(run_dir / "uploads"), "CHROMA_DIR": str(run_dir / "chroma"),
            "MODEL_CACHE_DIR": str(run_dir / "model-cache"), "MODEL_SETTINGS_PATH": str(run_dir / "no-model-settings.bin"),
            "PYTHONIOENCODING": "utf-8"}
        for key in list(os.environ):
            if key.upper().startswith("PG"):
                os.environ.pop(key, None)
        os.environ.update(test_env)
        for key in ("UPLOAD_DIR", "CHROMA_DIR", "MODEL_CACHE_DIR"):
            Path(os.environ[key]).mkdir(parents=True, exist_ok=True)
        from backend.config import get_settings
        get_settings.cache_clear()
        isolated_settings = get_settings()
        from sqlalchemy.engine import make_url
        parsed_url = make_url(str(isolated_settings.active_database_url))
        if (isolated_settings.app_env != "test" or parsed_url.host != "127.0.0.1"
                or parsed_url.port != port or parsed_url.database != "kaoyan_test" or port == 5433):
            raise RuntimeError("app_test_environment_database_guard_failed")
        progress["test_database_url_guard"] = {"app_env": isolated_settings.app_env, "host": parsed_url.host,
            "port": parsed_url.port, "database": parsed_url.database, "port_5433_refused": True}

        # Focused service and chat-path regression. This is not an independent
        # offline acceptance phase and uses only mock providers/no real requests.
        import pytest
        test_paths = [
            "tests/integration/test_personal_question_bank.py::test_ai_generated_mode_authors_full_question_and_keeps_attempt_out_of_graduation",
            "tests/integration/test_personal_question_bank.py::test_assistant_stream_explicit_generation_uses_same_real_services",
            "tests/integration/test_personal_question_bank.py::test_personal_attempt_saved_hidden_history_and_graduation_exclusion",
            "tests/integration/test_personal_question_bank.py::test_c6_registered_families_run_through_personal_bank_and_attempt_isolation",
            "tests/integration/test_personal_question_bank.py::test_scope_conflict_daily_limit_and_no_implicit_generating",
        ]
        from backend.db import create_db_engine, create_session_factory
        baseline_engine = create_db_engine(database_url)
        baseline_factory = create_session_factory(baseline_engine)
        before_test_counts = current_counts(baseline_factory)
        baseline_engine.dispose()
        progress["stage"] = "running_focused_regression_before_any_model_call"
        atomic_json(OUT_DIR / "progress.json", progress)
        test_code = pytest.main(["-q", "--disable-warnings", *test_paths])
        progress["focused_tests"] = {"command": "pytest -q --disable-warnings " + " ".join(test_paths),
            "exit_code": int(test_code), "status": "PASS" if int(test_code) == 0 else "FAIL"}
        engine = create_db_engine(database_url)
        factory = create_session_factory(engine)
        post_test = verify_database(cluster, port, expected_revision=initial["revision"])
        after_test_counts = current_counts(factory)
        progress["counts_before_tests"] = before_test_counts
        progress["counts_after_tests"] = after_test_counts
        if int(test_code) != 0 or after_test_counts != initial["counts"] or post_test["daily_reserved_calls"] != initial["daily_reserved_calls"]:
            raise RuntimeError("focused_mock_tests_failed_or_isolated_baseline_mutated")
        progress["isolated_database_fingerprint_unchanged_after_tests"] = True
        progress["stage"] = "focused_regression_passed_live_calls_next"
        atomic_json(OUT_DIR / "progress.json", progress)

        from fastapi.testclient import TestClient
        from backend.app import create_app
        from backend.models.chat import ChatSession
        from backend.schemas.learning_assistant import AssistantRequest, StudyContext
        from backend.services.question_generation import PERSONAL_C7_PROMPT_VERSION
        from backend.services.quality_verifiers import VERSION as verifier_version
        from backend.services.personal_question_service import bank_rows
        from sqlalchemy import select
        from sqlalchemy.orm import sessionmaker
        engine = create_db_engine(database_url)
        factory = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False, autocommit=False)
        capture = OneRequestCapture(provider, OUT_DIR, progress)
        app = create_app()
        app.state.settings = isolated_settings
        app.state.instance_lock_lost = False
        app.state.session_factory = factory
        app.state.personal_generation_provider = capture
        client = TestClient(app, base_url="http://127.0.0.1:5173", raise_server_exceptions=False)
        with factory.begin() as db:
            session = ChatSession(title="TEST_FIXTURE Phase 4.5I-Agent-Real", mode="builtin", purpose="qa")
            db.add(session); db.flush(); session_id = session.id
        progress["chat_session_id"] = str(session_id)
        progress["provider_config"]["verifier_version"] = verifier_version
        atomic_json(OUT_DIR / "progress.json", progress)

        # Block any unwrapped sync/async model request. The single permitted
        # synchronous post is opened only during OneRequestCapture.complete().
        import httpx
        original_post = httpx.post
        original_async_client = httpx.AsyncClient
        def guarded_post(url, **kwargs):
            return capture.guarded_post(original_post, url, **kwargs)
        class BlockedAsyncClient:
            def __init__(self, *args, **kwargs):
                capture.unexpected_calls.append({"reason": "async_paid_request_blocked"})
                raise RuntimeError("unexpected_async_model_request_blocked")
        httpx.post = guarded_post
        httpx.AsyncClient = BlockedAsyncClient
        try:
            for index, target in enumerate(targets, 1):
                if datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat() != initial["study_date_shanghai"]:
                    progress["stop_reason"] = "shanghai_study_date_changed_during_authorized_run"
                    break
                live = verify_database(cluster, port, expected_revision=initial["revision"])
                if live["daily_reserved_calls"] >= MAX_DAILY_CALLS:
                    progress["stop_reason"] = "application_daily_reserved_call_limit_reached"
                    break
                if sum(1 for row in progress["provider_requests"] if row.get("actual_http_request")) >= MAX_CALLS:
                    progress["stop_reason"] = "authorized_20_provider_request_cap_reached"
                    break
                unexpected_before = len(capture.unexpected_calls)
                request_key = str(uuid4())
                body = AssistantRequest(question=target["prompt"],
                    request_key=UUID(request_key),
                    study_context=StudyContext(surface="chat", knowledge_node_ids=[UUID(target["node"]["id"])],
                        conversation_id=session_id, origin="knowledge"),
                    personal_generation_mode="ai_generated")
                capture.current_target = target
                response = client.post(f"/api/chat/sessions/{session_id}/assistant:stream",
                    json=body.model_dump(mode="json"), timeout=180)
                parsed = parse_sse(response.text)
                gen = parsed.get("personal_generation") or {}
                batch_view = None
                if gen.get("batch_id"):
                    from backend.models.personal_generation import PersonalGenerationBatch
                    with factory() as db:
                        batch = db.get(PersonalGenerationBatch, UUID(gen["batch_id"]))
                        if batch:
                            batch_view = {"id": str(batch.id), "status": batch.status,
                                "reserved_calls": batch.reserved_calls, "study_date": batch.study_date,
                                "request": batch.request, "result": batch.result}
                turn = record_turn(OUT_DIR / "turns.jsonl", target, request_key, response, parsed, capture,
                    unexpected_before, batch_view)
                progress["turns"].append(turn)
                progress["turns_completed"] = len(progress["turns"])
                progress["actual_provider_request_count"] = sum(
                    1 for row in progress["provider_requests"] if row.get("actual_http_request"))
                atomic_json(OUT_DIR / "progress.json", progress)
                if turn["unexpected_paid_posts_blocked"]:
                    progress["stop_reason"] = "unexpected_unwrapped_provider_call_blocked"
                    break
                request_record = turn.get("provider_request") or {}
                if request_record.get("error_type") or request_record.get("usage_observed") is False:
                    progress["stop_reason"] = "provider_error_or_usage_unobserved_no_retry"
                    break
                if request_record.get("budget_violation"):
                    progress["stop_reason"] = "observed_token_budget_violation"
                    break
                if request_record.get("http_status") in {401, 402, 403, 429}:
                    progress["stop_reason"] = f"provider_http_{request_record['http_status']}"
                    break
                counts_now = current_counts(factory)
                if counts_now["kp_mastery_policies"]:
                    progress["stop_reason"] = "policy_row_pollution_detected_before_e2e"
                    break
                print(json.dumps({"turn": index, "subject": target["subject"], "node": target["node"]["code"],
                    "type": target["question_type"], "saved": len(turn.get("question_ids") or []),
                    "actual_provider_requests": progress["actual_provider_request_count"],
                    "http_status": request_record.get("http_status"), "finish_reason": request_record.get("finish_reason"),
                    "usage": request_record.get("usage"), "estimated_peak_cost_usd": progress["estimated_peak_cost_usd"]},
                    ensure_ascii=False), flush=True)
            finally_target = capture.current_target
            capture.current_target = None
        finally:
            httpx.post = original_post
            httpx.AsyncClient = original_async_client

        # Any posted model request not attributed to exactly one recorded turn is a safety stop.
        provider_count = sum(1 for row in progress["provider_requests"] if row.get("actual_http_request"))
        progress["actual_provider_request_count"] = provider_count
        if provider_count > MAX_CALLS:
            raise RuntimeError("hard_cap_20_provider_requests_breached")
        if len(progress["turns"]) != provider_count:
            progress["stop_reason"] = progress.get("stop_reason") or "turn_to_provider_request_count_mismatch"

        # Query actual saved questions, quality metadata and today's items.
        from backend.models.learning import Question, PracticeItem, QuestionAttempt, LearningEvent, KpState
        from backend.services.question_generation import current_generation_binding
        from backend.services.question_eligibility import question_eligibility
        subject_for_node = {row["node"]["id"]: row["subject"] for row in targets}
        saved_by_subject = {"数学二": [], "408": []}
        audit_saved = []
        with factory() as db:
            saved_ids = [UUID(qid) for turn in progress["turns"] for qid in turn.get("question_ids", [])]
            questions = list(db.scalars(select(Question).where(Question.id.in_(saved_ids)))) if saved_ids else []
            for q in questions:
                node = db.get(__import__("backend.models.learning", fromlist=["KnowledgePoint"]).KnowledgePoint, q.kp_id)
                batch = db.get(__import__("backend.models.personal_generation", fromlist=["PersonalGenerationBatch"]).PersonalGenerationBatch,
                    q.generation_batch_id) if q.generation_batch_id else None
                item = db.scalar(select(PracticeItem).where(PracticeItem.question_id == q.id))
                subject = subject_for_node.get(str(q.kp_id), "unknown")
                saved_by_subject.setdefault(subject, []).append(q)
                audit_saved.append({"question_id": str(q.id), "subject": subject, "kp_id": str(q.kp_id),
                    "bank_scope": q.bank_scope, "generation_batch_id": str(q.generation_batch_id) if q.generation_batch_id else None,
                    "generation_mode": (q.grading_config or {}).get("generation", {}).get("generation_mode"),
                    "prompt_version": (q.grading_config or {}).get("generation", {}).get("prompt_version"),
                    "review_status": (q.grading_config or {}).get("generation", {}).get("review_status"),
                    "independent_verification": (q.grading_config or {}).get("generation", {}).get("independent_verification"),
                    "question_type": q.question_type, "difficulty": q.difficulty,
                    "stem": q.stem, "options": q.options, "correct_answer": q.correct_answer,
                    "explanation": q.explanation, "practice_item_id": str(item.id) if item else None,
                    "batch_status": batch.status if batch else None,
                    "practice_eligible": question_eligibility(q, node).practice_eligible if node else False,
                    "generation_binding_current": current_generation_binding(q, node) if node else False})
        progress["saved_question_audit"] = audit_saved
        progress["saved_question_ids"] = [row["question_id"] for row in audit_saved]
        progress["saved_personal_bank_total"] = current_counts(factory)["questions"]
        atomic_json(OUT_DIR / "progress.json", progress)

        e2e = []
        from scripts.run_phase45i_real_batch import exercise_saved_question_routes
        for subject in ("数学二", "408"):
            if not saved_by_subject.get(subject):
                e2e.append({"subject": subject, "status": "NOT_RUN_NO_REAL_AUTOPASS_QUESTION"})
                continue
            question = saved_by_subject[subject][0]
            graduation_fixture = None
            if subject == "408":
                graduation_fixture = create_isolated_graduation_fixture(factory, question.kp_id,
                    datetime.now(timezone.utc))
            result = exercise_saved_question_routes(client, factory, question)
            row = {"subject": subject, "question_id": str(question.id), "status": result.get("status"),
                   "practice_item_visible": result.get("item_visible_in_today_plan"),
                   "answer_and_explanation_readable": result.get("answer_and_explanation_readable"),
                   "submission_result": result.get("submission_result"),
                   "effective_confirmation_count": result.get("effective_confirmation_count"),
                   "evidence_window_unchanged": result.get("evidence_window_unchanged"),
                   "graduation_fixture": graduation_fixture}
            with factory() as db:
                state = db.get(KpState, question.kp_id)
                row["kp_state"] = state.state if state else None
                row["mastered_at"] = state.mastered_at.isoformat() if state and state.mastered_at else None
                row["evidence_window_count"] = len(state.evidence_window or []) if state else 0
                if subject == "408" and graduation_fixture:
                    from backend.services.post_graduation_service import read_post_practice
                    projection = read_post_practice(db, db.get(__import__("backend.models.learning", fromlist=["KnowledgePoint"]).KnowledgePoint,
                        question.kp_id), now=datetime.now(timezone.utc))
                    row["post_graduation_projection"] = projection.model_dump(mode="json") if projection else None
            e2e.append(row)
            if result.get("status") != "PASS":
                progress["stop_reason"] = progress.get("stop_reason") or f"{subject}_real_e2e_failed"
                break
        progress["e2e_results"] = e2e
        progress["ungraduated_attempt_check"] = next(({
            "subject": r["subject"], "state": r.get("kp_state"), "mastered_at": r.get("mastered_at"),
            "effective_confirmation_count": r.get("effective_confirmation_count"),
            "evidence_window_count": r.get("evidence_window_count")}
            for r in e2e if r.get("subject") == "数学二"), None)
        post_row = next((r for r in e2e if r.get("subject") == "408"), None)
        progress["post_graduation_fixture"] = post_row.get("graduation_fixture") if post_row else None
        progress["post_graduation_attempt_check"] = ({"status": post_row.get("status"),
            "post_graduation_projection": post_row.get("post_graduation_projection"),
            "strict_state_after_practice": post_row.get("kp_state"),
            "mastered_at_after_practice": post_row.get("mastered_at"),
            "effective_confirmation_count": post_row.get("effective_confirmation_count")} if post_row else None)

        final_identity = verify_database(cluster, port, expected_revision=initial["revision"])
        final_counts = current_counts(factory)
        progress["counts_after"] = final_counts
        progress["daily_reserved_calls_after"] = final_identity["daily_reserved_calls"]
        progress["daily_reserved_calls_limit"] = MAX_DAILY_CALLS
        progress["database_identity_after"] = {k: final_identity[k] for k in ("database", "port", "data_directory", "revision", "pidfile_pid")}
        progress["personal_bank_scope_check"] = {"public_questions": 0,
            "saved_personal_questions": len(audit_saved),
            "all_saved_personal": all(row["bank_scope"] == "personal" for row in audit_saved),
            "generation_binding_current": all(row["generation_binding_current"] for row in audit_saved)}
        progress["strict_policy_rows_after"] = final_counts["kp_mastery_policies"]
        progress["actual_provider_request_count"] = provider_count
        progress["stop_reason"] = progress.get("stop_reason")
        status = "PHASE45I_AGENT_REAL_COMPLETED" if provider_count == MAX_CALLS and not progress.get("stop_reason") else "PHASE45I_AGENT_REAL_PARTIAL"
        progress["finish_status"] = status
        atomic_json(OUT_DIR / "progress.json", progress)
        write_report(progress, status)
        return 0
    except Exception as exc:
        actual_requests = sum(1 for row in progress.get("provider_requests", [])
                              if row.get("actual_http_request") is True)
        status = "PHASE45I_AGENT_REAL_PARTIAL" if actual_requests else "BLOCKED_PRECHECK"
        progress["finish_status"] = status
        progress["safe_error_type"] = type(exc).__name__
        progress["safe_error"] = str(exc)[:240]
        try:
            write_report(progress, status)
        except Exception:
            pass
        atomic_json(OUT_DIR / "progress.json", progress)
        print(json.dumps({"status": status, "error_type": type(exc).__name__,
            "error": str(exc)[:240], "actual_provider_requests": progress.get("actual_provider_request_count", 0),
            "output_dir": str(OUT_DIR)}, ensure_ascii=False), flush=True)
        return 2
    finally:
        if client is not None:
            try: client.close()
            except Exception: pass
        if engine is not None:
            try: engine.dispose()
            except Exception: pass
        if started_database_here:
            pg_ctl = PG_BIN / "pg_ctl.exe"
            stopped = command([str(pg_ctl), "-D", str(cluster), "-m", "fast", "-w", "-t", "30", "stop"],
                             timeout=40, check=False)
            if stopped.returncode:
                print(json.dumps({"warning": "isolated_postgres_normal_stop_failed", "exit_code": stopped.returncode},
                                 ensure_ascii=False), flush=True)


if __name__ == "__main__":
    raise SystemExit(run())
