"""Run one bounded, real-DeepSeek Phase 4.5I window through the personal-question API.

This is deliberately opt-in, writes only to an owned temporary PostgreSQL cluster,
and uses the project's current personal-question API/service/verifier path.
It never connects to the development database or copies the question bank.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time
from urllib.parse import urlsplit
from uuid import uuid4
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FIXTURE = ROOT / "tests/fixtures/phase45i_generation_targets.json"
SNAPSHOT_SHA256 = "4570be69ca973536a66c690f698d7b05b35f071bd92e242f82dbe9244e1cb317"
PRICE_VERIFIED_ON = "2026-10-09"
NEXT_PRICE_VERIFIED_ON = "2026-10-10"
PEAK_INPUT_CNY_PER_M = 2.0
PEAK_OUTPUT_CNY_PER_M = 8.0
MAX_AUTHORIZED_CALLS = 50
MAX_OUTPUT_TOKENS = 3000
MAX_TOTAL_OUTPUT_TOKENS = 24000
MAX_CONSERVATIVE_TOKENS = 100000
MAX_INPUT_BYTES = 8000
MAX_DAILY_RESERVED = 30
MAX_BATCH_CALLS = 5
RUNS_ROOT = ROOT / "storage/quality-audits/phase45i-real-20261009"
NEXT_RUNS_ROOT = ROOT / "storage/quality-audits/phase45i-next"
RETEST_MAX_CALLS = 30
RETEST_MAX_OUTPUT_TOKENS = RETEST_MAX_CALLS * MAX_OUTPUT_TOKENS
RETEST_MAX_CONSERVATIVE_TOKENS = RETEST_MAX_CALLS * (MAX_INPUT_BYTES + 512 + MAX_OUTPUT_TOKENS)
RETEST_COST_BUDGET_CNY = 2.0
NEXT_MAX_CALLS = 20
NEXT_MAX_OUTPUT_TOKENS = 1800
NEXT_TOTAL_OUTPUT_TOKENS = NEXT_MAX_CALLS * NEXT_MAX_OUTPUT_TOKENS
NEXT_MAX_CONSERVATIVE_TOKENS = NEXT_MAX_CALLS * (MAX_INPUT_BYTES + 512 + NEXT_MAX_OUTPUT_TOKENS)
NEXT_COST_BUDGET_CNY = 2.0
PG_BIN = Path("C:/Program Files/PostgreSQL/18/bin")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def atomic_json(path: Path, payload: object) -> None:
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def command(args: list[str], *, timeout: int = 90, log_path: Path | None = None,
            check: bool = True) -> subprocess.CompletedProcess:
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith("PG")}
    if log_path:
        try:
            with log_path.open("wb") as log:
                result = subprocess.run(args, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                                        stdout=log, stderr=subprocess.STDOUT, timeout=timeout,
                                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        except subprocess.TimeoutExpired:
            with log_path.open("ab") as log:
                log.write(b"\nphase45i_command_timeout\n")
            raise
        result.stdout = b""
        result.stderr = b""
    else:
        result = subprocess.run(args, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                                capture_output=True, timeout=timeout,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    if check and result.returncode:
        raise RuntimeError(f"command_failed:{Path(args[0]).name}:{result.returncode}")
    return result


def free_loopback_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    if port == 5433 or port < 18000:
        return free_loopback_port()
    return port


def load_targets() -> tuple[dict, dict, str, str]:
    fixture_bytes = FIXTURE.read_bytes()
    fixture = json.loads(fixture_bytes)
    source = ROOT / fixture["source_inventory"]
    source_bytes = source.read_bytes()
    source_sha = sha256_bytes(source_bytes)
    if source_sha != fixture["source_inventory_sha256"] or source_sha != SNAPSHOT_SHA256:
        raise ValueError("frozen_target_inventory_hash_mismatch")
    inventory = json.loads(source_bytes)
    by_id = {str(row["id"]): row for row in inventory["knowledge_points"]}
    nodes = fixture["nodes"]
    if len(nodes) != 10 or len({row["id"] for row in nodes}) != 10:
        raise ValueError("target_node_count_or_uniqueness_invalid")
    for target in nodes:
        source_node = by_id.get(target["id"])
        if not source_node:
            raise ValueError("target_node_missing_from_frozen_inventory")
        for field in ("code", "name"):
            if source_node[field] != target[field]:
                raise ValueError(f"target_node_{field}_mismatch")
        expected_source_subject = "408" if target["subject"] == "408" else "考研数学"
        if source_node["subject"] != expected_source_subject:
            raise ValueError("target_node_subject_mismatch")
        if not source_node["is_active"] or not source_node["is_assessable"]:
            raise ValueError("target_node_not_active_assessable")
        target.update({
            "is_active": bool(source_node["is_active"]),
            "is_assessable": bool(source_node["is_assessable"]),
            "is_reference_only": bool(source_node["is_reference_only"]),
            "database_subject": source_node["subject"],
        })
    profiles = fixture["profiles_per_node"]
    if len(profiles) != 5:
        raise ValueError("profile_matrix_mismatch")
    if any(row.get("question_type") not in {"single_choice", "fill_blank"}
           or row.get("difficulty") not in {"basic", "improved", "comprehensive"}
           for row in profiles):
        raise ValueError("profile_type_or_difficulty_unsupported")
    return fixture, inventory, source_sha, sha256_bytes(fixture_bytes)


def make_window_targets(fixture: dict, window: int) -> list[dict]:
    profiles = fixture["profiles_per_node"]
    if not 0 <= window < 5:
        raise ValueError("window_must_be_0_to_4")
    selected = []
    for subject in ("数学二", "408"):
        rows = [row for row in fixture["nodes"] if row["subject"] == subject]
        if len(rows) != 5:
            raise ValueError(f"{subject}_node_count_mismatch")
        for node_index, node in enumerate(rows):
            profile_index = (node_index + window) % 5
            profile = profiles[profile_index]
            target_id = f"{subject}:{node['code']}:{profile['profile']}"
            selected.append({
                "target_id": target_id,
                "subject": subject,
                "node": node,
                "profile": profile,
            })
    if len(selected) != 10:
        raise ValueError("window_must_contain_ten_targets")
    return selected


def make_retest_batch_targets(fixture: dict, batch: int) -> list[dict]:
    """Return one bounded five-request subject batch, excluding original window 0."""
    if not 0 <= batch < 6:
        raise ValueError("retest_batch_must_be_0_to_5")
    window = batch // 2 + 1
    subject = "数学二" if batch % 2 == 0 else "408"
    selected = [row for row in make_window_targets(fixture, window) if row["subject"] == subject]
    original_ids = {row["target_id"] for row in make_window_targets(fixture, 0)}
    if len(selected) != 5 or any(row["target_id"] in original_ids for row in selected):
        raise ValueError("retest_batch_size_or_overlap_invalid")
    for row in selected:
        row["retest_batch"] = batch
        row["retest_window"] = window
    return selected


def make_next_batch_targets(fixture: dict, batch: int) -> list[dict]:
    """Return one subject's five exact registered families, two profiles each."""
    if not 0 <= batch < 4:
        raise ValueError("next_batch_must_be_0_to_3")
    subject = "数学二" if batch in {0, 2} else "408"
    profile_slot = 0 if batch in {0, 1} else 1
    rows = [row for row in fixture["nodes"] if row["subject"] == subject]
    if len(rows) != 5:
        raise ValueError(f"{subject}_node_count_mismatch")
    from backend.services.personal_question_families import resolve_family

    selected = []
    for node in rows:
        family = resolve_family(node["code"])
        if not family or family.family_id != node["expected_family"]:
            raise ValueError("next_target_family_registry_mismatch")
        preferred = (("single_choice", "basic", "choice_basic") if profile_slot == 0 else
                     ("fill_blank", "improved", "fill_improved"))
        question_type, difficulty, profile = preferred
        if question_type not in family.question_types:
            # The improper-integral family intentionally supports only its
            # fixed single-choice threshold question, not generic fill blanks.
            question_type, difficulty, profile = "single_choice", "improved", "choice_improved"
        selected.append({
            "target_id": f"next:{subject}:{node['code']}:{profile}",
            "subject": subject,
            "node": node,
            "profile": {"profile": profile, "question_type": question_type,
                        "difficulty": difficulty,
                        "evaluation_focus": ["registered_family_contract", "independent_solver",
                                             "answer_and_explanation_alignment"]},
            "family_id": family.family_id,
            "next_batch": batch,
        })
    if len(selected) != 5 or len({row["node"]["code"] for row in selected}) != 5:
        raise ValueError("next_batch_must_contain_five_distinct_nodes")
    return selected


def create_or_check_owner(run_dir: Path, *, expected_root: Path | None = None) -> dict:
    expected_root = (expected_root or RUNS_ROOT).resolve()
    resolved = run_dir.resolve()
    if not resolved.is_relative_to(expected_root) or resolved == expected_root:
        raise ValueError("run_directory_must_be_new_child_of_phase45i_root")
    marker = run_dir / "phase45i-owner.json"
    if marker.exists():
        owner = json.loads(marker.read_text(encoding="utf-8"))
        if owner.get("format") != 1 or owner.get("resolved_path") != str(resolved):
            raise ValueError("phase45i_run_owner_mismatch")
        return owner
    if run_dir.exists() and any(run_dir.iterdir()):
        raise ValueError("refusing_to_adopt_nonempty_run_directory")
    run_dir.mkdir(parents=True, exist_ok=True)
    owner = {"format": 1, "run_id": uuid4().hex, "resolved_path": str(resolved),
             "created_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()}
    atomic_json(marker, owner)
    return owner


class OwnedPg:
    def __init__(self, run_dir: Path, metadata: dict):
        self.run_dir = run_dir
        self.cluster = run_dir / "postgres-cluster"
        self.log_path = run_dir / "postgres.log"
        self.meta_path = run_dir / "postgres.json"
        self.metadata = metadata
        self.port: int
        self.started_here = False
        self.postmaster = None
        self.postmaster_log_handle = None

    def prepare(self) -> None:
        for name in ("postgres.exe", "initdb.exe", "pg_ctl.exe", "createdb.exe"):
            path = PG_BIN / name
            if not path.is_file():
                raise RuntimeError("postgresql18_binary_missing")
        if self.meta_path.exists():
            meta = json.loads(self.meta_path.read_text(encoding="utf-8"))
            if meta.get("run_id") != self.metadata["run_id"] or meta.get("cluster") != str(self.cluster.resolve()):
                raise ValueError("temporary_postgres_owner_mismatch")
            if not (self.cluster / "PG_VERSION").is_file() or (self.cluster / "PG_VERSION").read_text().strip() != "18":
                raise ValueError("temporary_postgres_cluster_version_mismatch")
            self.port = int(meta["port"])
        else:
            if self.cluster.exists():
                if any(self.cluster.iterdir()):
                    raise ValueError("refusing_to_adopt_nonempty_postgres_directory")
            else:
                self.cluster.mkdir(parents=True)
            self.port = free_loopback_port()
            result = command([str(PG_BIN / "initdb.exe"), "-D", str(self.cluster), "-U", "postgres",
                              "--encoding=UTF8", "--no-locale", "--auth-local=trust", "--auth-host=trust",
                              "--set=shared_buffers=128MB", "--set=max_connections=20"],
                             timeout=300, log_path=self.run_dir / "initdb.log", check=False)
            if result.returncode or not (self.cluster / "PG_VERSION").is_file():
                raise RuntimeError("temporary_postgres_initdb_failed")
            atomic_json(self.meta_path, {"run_id": self.metadata["run_id"],
                                         "cluster": str(self.cluster.resolve()), "port": self.port,
                                         "database": "kaoyan_test", "host": "127.0.0.1"})

    def start(self) -> None:
        pid_file = self.cluster / "postmaster.pid"
        if pid_file.exists():
            status = command([str(PG_BIN / "pg_ctl.exe"), "-D", str(self.cluster), "status"], check=False)
            if status.returncode == 0:
                raise RuntimeError("owned_test_postgres_already_running_refuse_duplicate")
            raise RuntimeError("temporary_postgres_pid_file_present_status_uncertain")
        with socket.socket() as probe:
            probe.settimeout(0.2)
            if probe.connect_ex(("127.0.0.1", self.port)) == 0:
                raise RuntimeError("temporary_postgres_port_in_use")
        env = {key: value for key, value in os.environ.items() if not key.upper().startswith("PG")}
        start_epoch = int(time.time())
        self.postmaster_log_handle = self.log_path.open("ab")
        self.postmaster = subprocess.Popen(
            [str(PG_BIN / "postgres.exe"), "-D", str(self.cluster), "-p", str(self.port),
             "-h", "127.0.0.1", "-c", "listen_addresses=127.0.0.1", "-c", "log_statement=none",
             "-c", "log_min_error_statement=panic"], cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
            stdout=self.postmaster_log_handle, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        self.started_here = True
        deadline = time.monotonic() + 120
        ready = False
        while time.monotonic() < deadline:
            if self.postmaster.poll() is not None:
                raise RuntimeError("temporary_postgres_exited_during_start")
            probe = command([str(PG_BIN / "pg_isready.exe"), "-h", "127.0.0.1", "-p", str(self.port), "-t", "2"],
                            timeout=5, check=False)
            if probe.returncode == 0:
                ready = True
                break
            time.sleep(0.5)
        if not ready or not pid_file.is_file():
            raise RuntimeError("temporary_postgres_start_timeout")
        # PostgreSQL on Windows may serialize a non-ASCII data-directory path
        # in the active ANSI code page. Read only the documented ASCII identity
        # fields; the pid-file's location is already the exact cluster launched
        # by this process, and the live server PID/port/start-time are checked.
        lines = pid_file.read_bytes().splitlines()
        if (len(lines) < 4 or int(lines[0]) != self.postmaster.pid
                or int(lines[2]) < start_epoch - 1 or int(lines[3]) != self.port):
            raise RuntimeError("temporary_postgres_identity_mismatch")
        self.started_here = True

    def stop(self) -> bool:
        if not (self.cluster / "postmaster.pid").exists():
            return True
        if not self.started_here or self.postmaster is None or self.postmaster.poll() is not None:
            return False
        try:
            lines = (self.cluster / "postmaster.pid").read_bytes().splitlines()
            if len(lines) < 4 or int(lines[0]) != self.postmaster.pid or int(lines[3]) != self.port:
                return False
            result = command([str(PG_BIN / "pg_ctl.exe"), "-D", str(self.cluster), "-m", "fast",
                              "-w", "-t", "25", "stop"], timeout=35, check=False)
            self.postmaster.wait(timeout=30)
            if result.returncode == 0 and not (self.cluster / "postmaster.pid").exists():
                self.started_here = False
                if self.postmaster_log_handle:
                    self.postmaster_log_handle.close()
                    self.postmaster_log_handle = None
                return True
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return False
        return False

    def database_url(self) -> str:
        return f"postgresql+psycopg://postgres@127.0.0.1:{self.port}/kaoyan_test"


def counts(factory) -> dict:
    from sqlalchemy import func, select
    from backend.models.learning import (DailyPlan, KpState, LearningEvent, PracticeItem,
                                         Question, QuestionAttempt, KnowledgePoint)
    with factory() as db:
        models = {"knowledge_points": KnowledgePoint, "questions": Question,
                  "daily_plans": DailyPlan, "practice_items": PracticeItem,
                  "question_attempts": QuestionAttempt, "learning_events": LearningEvent,
                  "kp_states": KpState}
        return {name: int(db.scalar(select(func.count()).select_from(model)) or 0)
                for name, model in models.items()}


def seed_nodes(factory, fixture: dict) -> None:
    from uuid import UUID
    from backend.models.learning import KnowledgePoint
    with factory.begin() as db:
        for target in fixture["nodes"]:
            row = db.get(KnowledgePoint, UUID(target["id"]))
            if row:
                if row.code != target["code"] or row.name != target["name"]:
                    raise ValueError("isolated_seed_node_conflict")
                continue
            db.add(KnowledgePoint(
                id=UUID(target["id"]), code=target["code"], name=target["name"],
                subject=target["database_subject"], parent_id=None, ordinal=0,
                is_assessable=True, is_reference_only=target["is_reference_only"],
                is_active=True,
            ))


class CapturingProvider:
    """Observe only returned response content/usage; never log keys or reasoning fields."""
    def __init__(self, wrapped, calls_path: Path, progress: dict, *,
                 max_authorized_calls: int = MAX_AUTHORIZED_CALLS,
                 total_output_tokens: int = MAX_TOTAL_OUTPUT_TOKENS,
                 conservative_tokens: int = MAX_CONSERVATIVE_TOKENS,
                 cost_budget_cny: float = 3.0,
                 prompt_version: str = "question-generation-c2-v2"):
        self.wrapped = wrapped
        self.calls_path = calls_path
        self.progress = progress
        self.model = wrapped.model
        self.base_url = wrapped.base_url
        self.max_tokens = wrapped.max_tokens
        self.configured_max_tokens = wrapped.max_tokens
        self.output_ceiling = (NEXT_MAX_OUTPUT_TOKENS
                               if prompt_version == "question-generation-c4-v1"
                               else MAX_OUTPUT_TOKENS)
        self.simulation = False
        self.target_id: str | None = None
        self.actual_calls = 0
        self.total_cost_cny = sum(float(row.get("peak_price_cost_cny", 0) or 0)
                                  for row in progress.get("model_calls", [])
                                  if row.get("model_http_request_attempted") is True)
        self.usage_unknown = False
        self.stop_reason: str | None = None
        self.max_authorized_calls = max_authorized_calls
        self.total_output_tokens = total_output_tokens
        self.conservative_tokens = conservative_tokens
        self.cost_budget_cny = cost_budget_cny
        self.prompt_version = prompt_version

    @staticmethod
    def max_call_cost() -> float:
        # In-app prompt byte ceiling (8,000) plus 512 protocol reserve; 3,000 output.
        return ((MAX_INPUT_BYTES + 512) * PEAK_INPUT_CNY_PER_M
                + MAX_OUTPUT_TOKENS * PEAK_OUTPUT_CNY_PER_M) / 1_000_000

    def complete(self, messages, *, attempt=1):
        import backend.chat.service as chat_service
        original = chat_service.httpx.post
        host = urlsplit(self.base_url).hostname
        if (host != "api.deepseek.com" or self.model != "deepseek-flash"
                or self.configured_max_tokens != self.output_ceiling):
            self.stop_reason = "provider_configuration_changed"
            raise RuntimeError("provider_configuration_changed_before_request")
        body_bytes = sum(len(str(item.get("content", "")).encode("utf-8")) for item in messages)
        if body_bytes > MAX_INPUT_BYTES:
            self.stop_reason = "generation_prompt_exceeds_byte_budget"
            raise RuntimeError("generation_prompt_exceeds_production_byte_limit")
        if attempt != 1:
            self.stop_reason = "retry_blocked"
            raise RuntimeError("automatic_or_explicit_retry_blocked")
        prior_calls = [call for call in self.progress.get("model_calls", [])
                       if call.get("model_http_request_attempted") is True]
        if len(prior_calls) >= self.max_authorized_calls:
            self.stop_reason = "authorized_request_limit_reached"
            raise RuntimeError("phase45i_call_guard_stop")
        prior_input_reserve = sum(int(call.get("input_bytes", 0)) + 512 for call in prior_calls
                                  if isinstance(call.get("input_bytes"), int))
        prior_usage = [call.get("usage") for call in prior_calls]
        if any(not isinstance(usage, dict) or not isinstance(usage.get("completion_tokens"), int)
               or not isinstance(usage.get("prompt_tokens"), int) for usage in prior_usage):
            self.stop_reason = "prior_usage_not_observed"
            raise RuntimeError("phase45i_usage_guard_stop")
        prior_output = sum(int(usage["completion_tokens"]) for usage in prior_usage)
        conservative_used = prior_input_reserve + prior_output
        input_reserve = body_bytes + 512
        available_output = min(self.output_ceiling, self.total_output_tokens - prior_output,
                               self.conservative_tokens - conservative_used - input_reserve)
        if available_output <= 0:
            self.stop_reason = "authorized_token_budget_exhausted"
            raise RuntimeError("phase45i_token_guard_stop")
        call_max_tokens = int(available_output)
        if call_max_tokens < 512:
            self.stop_reason = "authorized_output_budget_too_small_for_reliable_item"
            raise RuntimeError("phase45i_output_guard_stop")
        before = self.total_cost_cny
        max_this_call_cost = (input_reserve * PEAK_INPUT_CNY_PER_M
                              + call_max_tokens * PEAK_OUTPUT_CNY_PER_M) / 1_000_000
        if before + max_this_call_cost > self.cost_budget_cny:
            self.stop_reason = "pre_call_cost_reserve_near_budget"
            raise RuntimeError("phase45i_cost_guard_stop")
        # The live Provider remains the production Provider; only its per-request
        # ceiling is narrowed so the aggregate authorized output/token budget is
        # enforced upstream rather than estimated after a possibly over-budget reply.
        self.wrapped.max_tokens = call_max_tokens
        self.max_tokens = call_max_tokens
        started = time.perf_counter()
        record = {"call_number": len(prior_calls) + 1, "target_id": self.target_id,
                  "model": self.model, "transport": "official_api_deepseek",
                  "prompt_version": self.prompt_version, "attempt": attempt,
                  "input_bytes": body_bytes, "input_token_conservative_reserve": input_reserve,
                  "max_output_tokens": call_max_tokens,
                  "request_sha256": sha256_bytes(json.dumps(messages, ensure_ascii=False,
                                                              sort_keys=True).encode("utf-8")),
                  "http_status": None, "finish_reason": None, "usage": None,
                  "usage_observed": False, "response_content": None, "error_category": None,
                  "model_http_request_attempted": False}

        def captured_post(url, **kwargs):
            parsed = urlsplit(str(url))
            payload = kwargs.get("json")
            if (parsed.hostname != "api.deepseek.com" or parsed.path.rstrip("/") != "/chat/completions"
                    or not isinstance(payload, dict) or payload.get("model") != "deepseek-flash"
                    or payload.get("max_tokens") != call_max_tokens
                    or int(payload.get("max_tokens", self.output_ceiling + 1)) > self.output_ceiling
                    or payload.get("stream") is True):
                raise RuntimeError("unexpected_paid_request_shape_blocked")
            # Count only the one outbound request that passed the allowlist.
            record["model_http_request_attempted"] = True
            self.actual_calls += 1
            response = original(url, **kwargs)
            record["http_status"] = response.status_code
            try:
                payload = response.json()
                if response.status_code < 400 and isinstance(payload, dict):
                    choices = payload.get("choices") or []
                    if choices and isinstance(choices[0], dict):
                        record["finish_reason"] = choices[0].get("finish_reason")
                        message = choices[0].get("message") or {}
                        if isinstance(message, dict) and isinstance(message.get("content"), str):
                            record["response_content"] = message["content"]
                    usage = payload.get("usage")
                    if isinstance(usage, dict):
                        record["usage"] = {key: usage[key] for key in
                                            ("prompt_tokens", "completion_tokens", "total_tokens")
                                            if isinstance(usage.get(key), int) and not isinstance(usage[key], bool)
                                            and usage[key] >= 0}
                        record["usage_observed"] = isinstance(record["usage"].get("prompt_tokens"), int) and isinstance(
                            record["usage"].get("completion_tokens"), int)
            except Exception:
                # Preserve the original response/error path; never retry for capture failures.
                record["response_capture_error"] = "unparseable_response"
            return response

        chat_service.httpx.post = captured_post
        try:
            raw, usage = self.wrapped.complete(messages, attempt=1)
            if record["response_content"] is None:
                record["response_content"] = raw
            if record["usage"] is None:
                record["usage"] = usage
            record["usage_observed"] = bool(isinstance(record["usage"], dict)
                                             and isinstance(record["usage"].get("prompt_tokens"), int)
                                             and isinstance(record["usage"].get("completion_tokens"), int))
            if record["usage_observed"]:
                prompt = int(record["usage"]["prompt_tokens"])
                completion = int(record["usage"]["completion_tokens"])
                if prompt < 0 or prompt > input_reserve or completion < 0 or completion > call_max_tokens:
                    self.stop_reason = "observed_usage_outside_authorized_bound"
                    self.usage_unknown = True
            else:
                self.usage_unknown = True
                self.stop_reason = "provider_usage_not_observed"
            return raw, usage
        except Exception as exc:
            # Store only safe categories; never persist arbitrary upstream text or headers.
            record["error_category"] = type(exc).__name__
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if isinstance(status, int):
                record["http_status"] = status
                record["error_category"] = f"http_{status}"
            elif getattr(exc, "detail", None):
                from backend.chat.call_trace import safe_failure_reason
                record["error_category"] = safe_failure_reason(exc.detail)
            self.stop_reason = self.stop_reason or "provider_or_format_error"
            raise
        finally:
            chat_service.httpx.post = original
            self.wrapped.max_tokens = self.configured_max_tokens
            self.max_tokens = self.configured_max_tokens
            record["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 3)
            usage = record.get("usage")
            if (isinstance(usage, dict) and isinstance(usage.get("prompt_tokens"), int)
                    and isinstance(usage.get("completion_tokens"), int)):
                prompt = int(usage["prompt_tokens"])
                completion = int(usage["completion_tokens"])
                if prompt < 0 or prompt > input_reserve or completion < 0 or completion > call_max_tokens:
                    self.stop_reason = "observed_usage_outside_authorized_bound"
                    self.usage_unknown = True
                else:
                    call_cost = (prompt * PEAK_INPUT_CNY_PER_M
                                 + completion * PEAK_OUTPUT_CNY_PER_M) / 1_000_000
                    self.total_cost_cny += call_cost
                    record["peak_price_cost_cny"] = round(call_cost, 8)
                    record["cumulative_peak_price_cost_cny"] = round(self.total_cost_cny, 8)
                    self.progress["cumulative_conservative_token_upper_bound"] = (
                        int(self.progress.get("cumulative_conservative_token_upper_bound", 0))
                        + input_reserve + completion)
                    self.progress["cumulative_observed_prompt_tokens"] = (
                        int(self.progress.get("cumulative_observed_prompt_tokens", 0)) + prompt)
                    self.progress["cumulative_observed_completion_tokens"] = (
                        int(self.progress.get("cumulative_observed_completion_tokens", 0)) + completion)
                    if self.progress["cumulative_observed_completion_tokens"] > self.total_output_tokens:
                        self.stop_reason = "observed_total_output_budget_exceeded"
                        self.usage_unknown = True
                    remaining = self.max_authorized_calls - (len(self.progress.get("model_calls", [])) + 1)
                    if self.total_cost_cny + remaining * self.max_call_cost() > self.cost_budget_cny:
                        self.stop_reason = "projected_cost_near_budget"
            else:
                self.usage_unknown = True
                self.stop_reason = self.stop_reason or "provider_usage_not_observed"
            with self.calls_path.open("a", encoding="utf-8") as output:
                output.write(json.dumps(record, ensure_ascii=False) + "\n")
                output.flush()
                os.fsync(output.fileno())
            if record["model_http_request_attempted"]:
                self.progress.setdefault("model_calls", []).append({k: v for k, v in record.items()
                                                                      if k != "response_content"})
            else:
                self.progress.setdefault("blocked_provider_attempts", []).append(
                    {k: v for k, v in record.items() if k != "response_content"})
            atomic_json(self.calls_path.with_name("progress.json"), self.progress)


class NoNetworkDiagnosticProvider:
    """Deliberately invalid offline response for exercising the app route only."""
    model = "offline-diagnostic-stub"
    base_url = "offline://no-network"
    max_tokens = 512
    timeout = 1
    simulation = False

    def __init__(self):
        self.calls = 0

    def complete(self, messages, *, attempt=1):
        self.calls += 1
        return "{ intentionally invalid JSON", {"prompt_tokens": 0, "completion_tokens": 0}


def safe_api_result(response) -> dict:
    if response.status_code >= 400:
        try:
            payload = response.json()
            error = payload.get("error", {}) if isinstance(payload, dict) else {}
            code = error.get("code") if isinstance(error, dict) else None
        except Exception:
            code = None
        return {"http_status": response.status_code, "api_error_code": code or "unclassified"}
    try:
        payload = response.json()
        return payload if isinstance(payload, dict) else {"api_error_code": "unexpected_response_shape"}
    except Exception:
        return {"api_error_code": "unparseable_api_response"}


def classify_candidate_failures(failures: list[dict]) -> str:
    """Do not call an unverified verifier step a confirmed content error."""
    reasons = {str(row.get("reason")) for row in failures}
    issues = {str(issue) for row in failures for issue in (row.get("issues") or [])}
    if "independent_answer_conflict" in issues:
        return "FAIL"
    if "explanation_step_unverified_or_false" in issues and not (issues - {"explanation_step_unverified_or_false"}):
        return "UNCERTAIN"
    if "NEEDS_EVIDENCE" in reasons:
        return "UNCERTAIN"
    if "REJECTED" in reasons:
        return "FAIL"
    return "BLOCKED"


def grade_saved_question(q) -> dict:
    from backend.services.answer_grading import grade_practice_final_answer
    from backend.services.question_eligibility import question_eligibility
    eligibility = question_eligibility(q, q.kp)
    if q.question_type == "single_choice":
        correct = grade_practice_final_answer(question_type=q.question_type, config=q.grading_config,
            answer=None, selected_option=q.correct_answer, expected=q.correct_answer, options=q.options,
            answer_provenance=q.answer_provenance, content_trust=q.content_trust,
            answer_reliability=q.answer_reliability)
        wrong_option = next((key for key in q.options if key != q.correct_answer), None)
        wrong = grade_practice_final_answer(question_type=q.question_type, config=q.grading_config,
            answer=None, selected_option=wrong_option, expected=q.correct_answer, options=q.options,
            answer_provenance=q.answer_provenance, content_trust=q.content_trust,
            answer_reliability=q.answer_reliability) if wrong_option else None
        blank = grade_practice_final_answer(question_type=q.question_type, config=q.grading_config,
            answer=None, selected_option="", expected=q.correct_answer, options=q.options,
            answer_provenance=q.answer_provenance, content_trust=q.content_trust,
            answer_reliability=q.answer_reliability)
    else:
        correct = grade_practice_final_answer(question_type=q.question_type, config=q.grading_config,
            answer=q.correct_answer, selected_option=None, expected=q.correct_answer, options=q.options,
            answer_provenance=q.answer_provenance, content_trust=q.content_trust,
            answer_reliability=q.answer_reliability)
        wrong = grade_practice_final_answer(question_type=q.question_type, config=q.grading_config,
            answer="not-a-valid-answer", selected_option=None, expected=q.correct_answer, options=q.options,
            answer_provenance=q.answer_provenance, content_trust=q.content_trust,
            answer_reliability=q.answer_reliability)
        blank = grade_practice_final_answer(question_type=q.question_type, config=q.grading_config,
            answer="", selected_option=None, expected=q.correct_answer, options=q.options,
            answer_provenance=q.answer_provenance, content_trust=q.content_trust,
            answer_reliability=q.answer_reliability)
    return {"practice_eligible": eligibility.practice_eligible,
            "evidence_capability": eligibility.evidence_capability,
            "grading_capability": eligibility.grading_capability,
            "comparison_method": eligibility.answer_comparison_method,
            "correct_answer_result": correct.result,
            "wrong_answer_result": wrong.result if wrong else None,
            "blank_answer_result": blank.result}


def exercise_saved_question_routes(client, factory, question) -> dict:
    """Exercise the user-facing study/read/submit/history path in the isolated DB.

    The created answer attempt is test-only data. Personal-question eligibility
    must keep it outside strict graduation evidence even when the reference
    answer grades as correct.
    """
    from backend.models.learning import KpState
    from uuid import uuid4

    # The answer-submission service intentionally requires an existing projection.
    # Seed only its neutral unseen state as an explicit test fixture.
    with factory.begin() as db:
        state = db.get(KpState, question.kp_id)
        if state is None:
            state = KpState(kp_id=question.kp_id)
            db.add(state)
            db.flush()
        before_window = list(state.evidence_window or [])
        before_state = state.state

    today = client.get("/api/plans/today")
    if today.status_code != 200:
        return {"status": "BLOCKED", "stage": "today_plan_read", "http_status": today.status_code}
    today_body = today.json()
    item = next((row for row in today_body.get("items", [])
                 if row.get("question_id") == str(question.id)), None)
    if item is None:
        return {"status": "BLOCKED", "stage": "today_plan_item_lookup"}
    expected_options = question.options or None
    if item.get("stem") != question.stem or item.get("options") != expected_options:
        return {"status": "FAIL", "stage": "today_plan_content_display"}

    item_id = item["id"]
    answer_response = client.get(f"/api/practice-items/{item_id}/answer")
    if answer_response.status_code != 200:
        return {"status": "BLOCKED", "stage": "answer_explanation_read",
                "http_status": answer_response.status_code}
    answer_body = answer_response.json()
    if (answer_body.get("correct_answer") != question.correct_answer
            or answer_body.get("explanation") != question.explanation):
        return {"status": "FAIL", "stage": "answer_explanation_content"}

    request_body = {"idempotency_key": f"phase45i-{uuid4().hex}",
                    "confidence": "certain"}
    if question.question_type == "single_choice":
        request_body["selected_option"] = str(question.correct_answer)
    elif question.question_type == "fill_blank":
        request_body["raw_answer"] = str(question.correct_answer)
    else:
        return {"status": "BLOCKED", "stage": "unsupported_fixture_question_type"}
    submission = client.post(
        f"/api/practice-items/{item_id}/answer-submissions", json=request_body)
    if submission.status_code != 200:
        return {"status": "BLOCKED", "stage": "answer_submission",
                "http_status": submission.status_code}
    submission_body = submission.json()
    history = client.get(f"/api/practice-items/{item_id}/answer-submissions")
    if history.status_code != 200:
        return {"status": "BLOCKED", "stage": "submission_history_read",
                "http_status": history.status_code}
    history_items = history.json().get("items", [])
    if not any(row.get("attempt_id") == submission_body.get("attempt_id") for row in history_items):
        return {"status": "FAIL", "stage": "submission_history_persistence"}

    refreshed_today = client.get("/api/plans/today")
    if refreshed_today.status_code != 200:
        return {"status": "BLOCKED", "stage": "today_plan_refresh",
                "http_status": refreshed_today.status_code}
    refreshed_item = next((row for row in refreshed_today.json().get("items", [])
                           if row.get("id") == item_id), None)
    if not refreshed_item or not refreshed_item.get("completed"):
        return {"status": "FAIL", "stage": "today_plan_completion_persistence"}

    with factory() as db:
        state = db.get(KpState, question.kp_id)
        refreshed_window = list(state.evidence_window or []) if state else None
        refreshed_state = state.state if state else None
        from backend.models.learning import QuestionAttempt
        attempt = db.get(QuestionAttempt, __import__("uuid").UUID(submission_body["attempt_id"]))
        evidence = dict(attempt.grading_evidence or {}) if attempt else {}
    if (not attempt or evidence.get("bank_scope") != "personal"
            or evidence.get("evidence_capability") != "personal_practice_only"
            or submission_body.get("effective_confirmation_count") != 0
            or refreshed_window != before_window):
        return {"status": "FAIL", "stage": "strict_graduation_isolation"}
    return {
        "status": "PASS", "item_visible_in_today_plan": True,
        "options_visible": question.question_type != "single_choice" or item.get("options") == question.options,
        "answer_and_explanation_readable": True,
        "submission_http_status": submission.status_code,
        "submission_result": submission_body.get("result"),
        "reference_result": submission_body.get("reference_result"),
        "attempt_persisted_and_readable": True,
        "today_completion_persisted": True,
        "strict_graduation_blocked": True,
        "effective_confirmation_count": submission_body.get("effective_confirmation_count"),
        "kp_state_before": before_state, "kp_state_after": refreshed_state,
        "strict_evidence_window_unchanged": refreshed_window == before_window,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--window", type=int, choices=range(5),
                        help="Original Phase 4.5I batch: 5 math + 5 CS requests.")
    parser.add_argument("--retest-batch", type=int, choices=range(6),
                        help="C3 retest batch: one subject, exactly 5 targets.")
    parser.add_argument("--next-batch", type=int, choices=range(4),
                        help="C4 family-bound pilot: one subject, exactly 5 targets.")
    parser.add_argument("--execute-real-model", action="store_true",
                        help="Explicitly permits this single 10-request window through DeepSeek.")
    parser.add_argument("--preflight-only", action="store_true",
                        help="Build and validate only the isolated DB/API configuration; never call a model.")
    parser.add_argument("--diagnose-api-no-network", action="store_true",
                        help="Exercise the actual generation route once with an offline invalid-response stub.")
    args = parser.parse_args()
    retest_mode = args.retest_batch is not None
    next_mode = args.next_batch is not None
    if sum(value is not None for value in (args.window, args.retest_batch, args.next_batch)) != 1:
        raise SystemExit("Specify exactly one of --window, --retest-batch, or --next-batch")
    if sum((bool(args.execute_real_model), bool(args.preflight_only), bool(args.diagnose_api_no_network))) != 1:
        raise SystemExit("Refusing paid calls without --execute-real-model")
    if args.execute_real_model:
        now_local = datetime.now(ZoneInfo("Asia/Shanghai"))
        expected_price_date = NEXT_PRICE_VERIFIED_ON if next_mode else PRICE_VERIFIED_ON
        if now_local.date().isoformat() != expected_price_date:
            raise SystemExit("Price schedule must be rechecked for the current Shanghai date before continuing")
    allowed_root = NEXT_RUNS_ROOT if next_mode else RUNS_ROOT
    allowed_root.mkdir(parents=True, exist_ok=True)
    run_dir = args.run_dir if args.run_dir.is_absolute() else ROOT / args.run_dir
    owner = create_or_check_owner(run_dir, expected_root=allowed_root)
    lock_path = run_dir / ".run.lock"
    try:
        fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise SystemExit("Another run may be active or a prior run stopped unexpectedly; inspect lock and state")
    os.write(fd, json.dumps({"pid": os.getpid(), "window": args.window}).encode("utf-8"))
    os.close(fd)

    try:
        fixture, inventory, snapshot_sha, fixture_sha = load_targets()
        run_batch = (args.next_batch if next_mode else
                     args.retest_batch if retest_mode else args.window)
        window_targets = (make_next_batch_targets(fixture, args.next_batch) if next_mode else
                          make_retest_batch_targets(fixture, args.retest_batch) if retest_mode else
                          make_window_targets(fixture, args.window))
        selected = list(window_targets)
        progress_path = run_dir / "progress.json"
        if progress_path.exists():
            progress = json.loads(progress_path.read_text(encoding="utf-8"))
        else:
            progress = {"format": 1, "run_id": owner["run_id"], "windows": [],
                        "targets": {}, "model_calls": [], "quality_rows": []}
        if progress.get("run_id") != owner["run_id"]:
            raise ValueError("progress_owner_mismatch")
        batch_key = f"next:{run_batch}" if next_mode else run_batch
        if batch_key in progress.get("windows", []):
            raise ValueError("window_already_attempted_no_retry")
        run_call_limit = NEXT_MAX_CALLS if next_mode else RETEST_MAX_CALLS if retest_mode else MAX_AUTHORIZED_CALLS
        if sum(row.get("model_http_request_attempted") is True for row in progress.get("model_calls", [])) >= run_call_limit:
            raise ValueError("authorized_real_request_limit_reached")
        if progress.get("stop_reason"):
            raise ValueError("prior_run_stop_reason_requires_manual_review")
        # A prior runner crash may have durably recorded a target. Preserve that
        # row and continue only with untouched targets; never regenerate it.
        selected = [row for row in window_targets if row["target_id"] not in progress.get("targets", {})]
        if not selected:
            raise ValueError("window_has_no_unattempted_targets")

        # Load the actual local user configuration securely, before selecting the isolated DB.
        os.environ["APP_ENV"] = "dev"
        from backend.config import get_settings
        from backend.services.model_settings_service import load_local_settings
        get_settings.cache_clear()
        model_settings = load_local_settings(get_settings())
        parsed_endpoint = urlsplit(model_settings.llm_base_url or "")
        if (parsed_endpoint.hostname != "api.deepseek.com" or model_settings.llm_model != "deepseek-flash"
                or not model_settings.llm_api_key or not model_settings.llm_api_key.get_secret_value()
                or model_settings.local_model_settings_error):
            raise RuntimeError("configured_model_not_authorized_endpoint_or_settings_error")
        from backend.services.question_generation import Budget, configured_provider, GENERATION_VERSION
        from backend.services.personal_question_service import PROMPT_VERSION
        from backend.services.quality_verifiers import VERSION as VERIFIER_VERSION
        if next_mode and (PROMPT_VERSION != "question-generation-c4-v1"
                          or GENERATION_VERSION != "bounded-question-generation-v6"
                          or VERIFIER_VERSION != "bounded-problem-verifiers-v9"):
            raise RuntimeError("phase45i_next_version_mismatch")
        if retest_mode and (PROMPT_VERSION != "question-generation-c3-v1"
                            or GENERATION_VERSION != "bounded-question-generation-v5"
                            or VERIFIER_VERSION != "bounded-problem-verifiers-v8"):
            raise RuntimeError("phase45i_retest_version_mismatch")
        output_cap = NEXT_MAX_OUTPUT_TOKENS if next_mode else MAX_OUTPUT_TOKENS
        wrapped_provider = configured_provider(
            model_settings, Budget(max_calls=MAX_BATCH_CALLS,
                                   max_reserved_tokens=MAX_BATCH_CALLS * (MAX_INPUT_BYTES + 512 + output_cap),
                                   max_output_tokens=output_cap),
            real_call_authorized=True)
        if wrapped_provider.max_tokens != output_cap or wrapped_provider.timeout > 30:
            raise RuntimeError("provider_output_or_timeout_budget_mismatch")

        pg_run_dir = run_dir
        pg_owner = owner
        if retest_mode:
            pg_run_dir = RUNS_ROOT / "actual-run"
            if pg_run_dir.resolve() == run_dir.resolve():
                raise RuntimeError("retest_output_and_shared_database_paths_must_differ")
            shared_owner_path = pg_run_dir / "phase45i-owner.json"
            if not shared_owner_path.is_file():
                raise RuntimeError("prior_isolated_database_owner_missing")
            pg_owner = json.loads(shared_owner_path.read_text(encoding="utf-8"))
            if pg_owner.get("format") != 1 or pg_owner.get("resolved_path") != str(pg_run_dir.resolve()):
                raise RuntimeError("prior_isolated_database_owner_mismatch")
        # C4 gets its own database under its new run directory; unlike the C3
        # retest it must never reuse the old actual-run cluster or outputs.
        pg = OwnedPg(pg_run_dir, pg_owner)
        pg.prepare()
        pg.start()
        try:
            import psycopg
            from psycopg import sql
            from sqlalchemy import create_engine, func, select, text
            from sqlalchemy.orm import sessionmaker
            from sqlalchemy.engine import make_url
            url = make_url(pg.database_url())
            if (url.host != "127.0.0.1" or url.port != pg.port or pg.port == 5433
                    or url.database != "kaoyan_test" or not url.database.endswith("_test")):
                raise RuntimeError("isolated_database_url_guard_failed")
            with psycopg.connect(host="127.0.0.1", port=pg.port, user="postgres", dbname="postgres",
                                 sslmode="disable", connect_timeout=5, autocommit=True) as admin:
                if not admin.execute("SELECT 1 FROM pg_database WHERE datname='kaoyan_test'").fetchone():
                    admin.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0 ENCODING 'UTF8'").format(
                        sql.Identifier("kaoyan_test")))
            database_url = pg.database_url()
            os.environ.update({
                "APP_ENV": "test", "DATABASE_URL": database_url, "TEST_DATABASE_URL": database_url,
                "KAOYAN_OWNED_TEST_PORT": str(pg.port),
                "LLM_API_KEY": "", "LLM_BASE_URL": "", "LLM_MODEL": "",
                "UPLOAD_DIR": str(run_dir / "isolated-uploads"),
                "CHROMA_DIR": str(run_dir / "isolated-chroma"),
                "MODEL_CACHE_DIR": str(run_dir / "isolated-model-cache"),
                "MODEL_SETTINGS_PATH": str(run_dir / "no-model-settings.bin"),
                "PYTHONIOENCODING": "utf-8",
            })
            get_settings.cache_clear()
            isolated_settings = get_settings()
            if (isolated_settings.app_env != "test" or str(isolated_settings.active_database_url) != database_url
                    or str(isolated_settings.test_database_url) != database_url):
                raise RuntimeError("test_settings_database_isolation_guard_failed")

            from alembic import command as alembic_command
            from alembic.config import Config
            alembic_config = Config(str(ROOT / "alembic.ini"))
            alembic_config.set_main_option("script_location", str(ROOT / "migrations"))
            alembic_command.upgrade(alembic_config, "head")

            engine = create_engine(database_url, pool_pre_ping=True, connect_args={"connect_timeout": 5})
            factory = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False, autocommit=False)
            with engine.connect() as connection:
                identity = connection.execute(text("SELECT current_database(), inet_server_port(), extract(epoch from pg_postmaster_start_time())::bigint, current_setting('listen_addresses')")).one()
                pid_lines = (pg.cluster / "postmaster.pid").read_bytes().splitlines()
                if identity[0] != "kaoyan_test":
                    raise RuntimeError("isolated_database_name_mismatch")
                if identity[1] != pg.port:
                    raise RuntimeError("isolated_server_port_mismatch")
                if len(pid_lines) < 4 or int(pid_lines[0]) != pg.postmaster.pid:
                    raise RuntimeError("isolated_postmaster_pid_mismatch")
                if int(pid_lines[3]) != pg.port:
                    raise RuntimeError("isolated_pidfile_port_mismatch")
                if abs(int(identity[2]) - int(pid_lines[2])) > 1:
                    raise RuntimeError("isolated_postmaster_start_time_mismatch")
                if str(identity[3]).strip() != "127.0.0.1":
                    raise RuntimeError("isolated_listen_addresses_mismatch")
                revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            seed_nodes(factory, fixture)
            before_counts = counts(factory)
            if retest_mode or next_mode:
                previous_after = (progress.get("database_counts") or {}).get("after")
                if previous_after is not None:
                    if before_counts != previous_after:
                        raise RuntimeError("isolated_retest_database_changed_outside_recorded_batches")
                elif (before_counts["questions"] or before_counts["question_attempts"]
                      or before_counts["learning_events"] or before_counts["kp_states"]):
                    raise RuntimeError("isolated_retest_database_has_unaccounted_learning_data")
            elif (before_counts["questions"] or before_counts["question_attempts"]
                  or before_counts["learning_events"] or before_counts["kp_states"]):
                raise RuntimeError("fresh_isolated_database_not_empty")

            from fastapi.testclient import TestClient
            from backend.app import create_app
            app = create_app()
            app.state.settings = isolated_settings
            app.state.instance_lock_lost = False
            app.state.session_factory = factory
            calls_path = run_dir / "provider-calls.jsonl"
            capture = CapturingProvider(
                wrapped_provider, calls_path, progress,
                max_authorized_calls=NEXT_MAX_CALLS if next_mode else RETEST_MAX_CALLS if retest_mode else MAX_AUTHORIZED_CALLS,
                total_output_tokens=NEXT_TOTAL_OUTPUT_TOKENS if next_mode else RETEST_MAX_OUTPUT_TOKENS if retest_mode else MAX_TOTAL_OUTPUT_TOKENS,
                conservative_tokens=NEXT_MAX_CONSERVATIVE_TOKENS if next_mode else RETEST_MAX_CONSERVATIVE_TOKENS if retest_mode else MAX_CONSERVATIVE_TOKENS,
                cost_budget_cny=NEXT_COST_BUDGET_CNY if next_mode else RETEST_COST_BUDGET_CNY if retest_mode else 3.0,
                prompt_version=PROMPT_VERSION if (next_mode or retest_mode) else "question-generation-c2-v2")
            app.state.personal_generation_provider = capture
            client = TestClient(app, base_url="http://127.0.0.1", raise_server_exceptions=False)
            from backend.models.learning import (DailyPlan, KpState, LearningEvent, PracticeItem,
                                                 Question, QuestionAttempt, KnowledgePoint)
            from backend.services.quality_verifiers import verify_problem
            from backend.services.question_generation import current_generation_binding
            from backend.services.personal_question_service import bank_rows, family_for

            if args.diagnose_api_no_network:
                from fastapi.responses import JSONResponse
                from backend.schemas.personal_questions import PersonalGenerationRequest
                offline_provider = NoNetworkDiagnosticProvider()
                app.state.personal_generation_provider = offline_provider

                async def diagnostic_exception_handler(_request, exc):
                    original_error = getattr(exc, "orig", None)
                    diag = getattr(original_error, "diag", None)
                    safe_diagnostics = {}
                    for name in ("sqlstate", "constraint_name", "table_name", "column_name"):
                        value = getattr(diag, name, None)
                        if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,80}", value):
                            safe_diagnostics[name] = value
                    code = getattr(original_error, "sqlstate", None)
                    if isinstance(code, str) and re.fullmatch(r"[0-9A-Z]{5}", code):
                        safe_diagnostics["sqlstate"] = code
                    return JSONResponse(status_code=500, content={
                        "diagnostic_exception_type": type(exc).__name__,
                        "database_diagnostics": safe_diagnostics})

                app.exception_handlers[Exception] = diagnostic_exception_handler
                target = selected[0]
                body = PersonalGenerationRequest.model_validate({
                    "request_key": str(uuid4()), "surface": "study",
                    "targets": [{"kp_id": target["node"]["id"],
                                 "question_type": target["profile"]["question_type"],
                                 "count": 1, "difficulty": target["profile"]["difficulty"]}],
                })
                response = client.post("/api/personal-questions/generate", json=body.model_dump(mode="json"))
                try:
                    diagnostic_payload = response.json()
                except Exception:
                    diagnostic_payload = {}
                batch_counts = counts(factory)
                print(json.dumps({"diagnostic": "offline_generation_api_route",
                                  "http_status": response.status_code,
                                  "safe_response": safe_api_result(response),
                                  "diagnostic_exception_type": diagnostic_payload.get("diagnostic_exception_type"),
                                  "database_diagnostics": diagnostic_payload.get("database_diagnostics"),
                                  "diagnostic_error_code": ((diagnostic_payload.get("error") or {}).get("code")
                                                             if isinstance(diagnostic_payload.get("error"), dict) else None),
                                  "offline_provider_calls": offline_provider.calls,
                                  "database_revision": revision,
                                  "database_identity": {"host": "127.0.0.1", "port": pg.port,
                                                        "database": "kaoyan_test",
                                                        "data_directory": str(pg.cluster.resolve())},
                                  "counts_after": batch_counts,
                                  "external_model_calls": 0,
                                  "development_port_5433_used": False}, ensure_ascii=False), flush=True)
                client.close()
                engine.dispose()
                return 0

            if args.preflight_only:
                with engine.connect() as connection:
                    live_count = connection.execute(text("SELECT count(*) FROM knowledge_points")).scalar_one()
                from backend.models.personal_generation import PersonalGenerationBatch
                with factory() as db:
                    current_day = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
                    reserved_today = int(db.scalar(select(func.coalesce(func.sum(
                        PersonalGenerationBatch.reserved_calls), 0)).where(
                        PersonalGenerationBatch.study_date == current_day)) or 0)
                    batch_rows_total = int(db.scalar(select(func.count()).select_from(
                        PersonalGenerationBatch)) or 0)
                    batch_rows_today = int(db.scalar(select(func.count()).select_from(
                        PersonalGenerationBatch).where(
                        PersonalGenerationBatch.study_date == current_day)) or 0)
                print(json.dumps({"preflight": "PASS", "real_model_calls": 0,
                                  "database_revision": revision,
                                  "database_identity": {"host": "127.0.0.1", "port": pg.port,
                                                        "database": "kaoyan_test",
                                                        "data_directory": str(pg.cluster.resolve()),
                                                        "identity_basis": "owned_postmaster_pid_port_start_time_and_live_query"},
                                  "seeded_knowledge_points": live_count,
                                  "targets_in_window": len(selected),
                                  "shanghai_study_date": current_day,
                                  "daily_reserved_calls_in_isolated_database": reserved_today,
                                  "daily_reserved_remaining": max(0, MAX_DAILY_RESERVED - reserved_today),
                                  "generation_batch_rows_today": batch_rows_today,
                                  "generation_batch_rows_total": batch_rows_total,
                                  "model": wrapped_provider.model,
                                  "official_host": urlsplit(wrapped_provider.base_url).hostname,
                                  "configured_output_cap": wrapped_provider.max_tokens,
                                  "endpoint_instantiated_without_request": True,
                                  "development_port_5433_used": False}, ensure_ascii=False), flush=True)
                client.close()
                engine.dispose()
                return 0

            output_rows = []
            for target in selected:
                target_id = target["target_id"]
                node = target["node"]
                profile = target["profile"]
                from backend.schemas.personal_questions import PersonalGenerationRequest
                body = PersonalGenerationRequest.model_validate({
                    "request_key": str(uuid4()),
                    "surface": "study",
                    "targets": [{"kp_id": node["id"], "question_type": profile["question_type"],
                                 "count": 1, "difficulty": profile["difficulty"]}],
                })
                target_record = {"target_id": target_id,
                                 ("next_batch" if next_mode else "retest_batch" if retest_mode else "window"): run_batch,
                                 "subject": target["subject"], "node_id": node["id"],
                                 "node_code": node["code"], "node_name": node["name"],
                                 "database_subject": node["database_subject"],
                                 "reference_only": node["is_reference_only"],
                                 "expected_family": node["expected_family"],
                                 "actual_family": family_for(KnowledgePoint(
                                     id=__import__("uuid").UUID(node["id"]), code=node["code"], name=node["name"],
                                     subject=node["database_subject"], is_active=True, is_assessable=True,
                                     is_reference_only=node["is_reference_only"])),
                                 "question_type": profile["question_type"],
                                 "difficulty": profile["difficulty"], "profile": profile["profile"],
                                 "request_key": str(body.request_key), "http_status": None,
                                 "result": None, "quality_status": "BLOCKED"}
                if target_record["actual_family"] != target_record["expected_family"]:
                    raise RuntimeError("expected_family_mapping_changed")
                with factory() as db:
                    from backend.models.personal_generation import PersonalGenerationBatch
                    current_day = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
                    reserved_today = db.scalar(select(func.coalesce(func.sum(PersonalGenerationBatch.reserved_calls), 0)).where(
                        PersonalGenerationBatch.study_date == current_day)) or 0
                if reserved_today + 1 > MAX_DAILY_RESERVED:
                    target_record["quality_status"] = "BLOCKED"
                    target_record["stop_reason"] = "daily_reserved_limit"
                    target_record["model_http_calls"] = 0
                    target_record["not_sent"] = True
                    output_rows.append(target_record)
                    break
                progress.setdefault("targets", {})[target_id] = {"status": "request_started",
                                                                  "request_key": target_record["request_key"],
                                                                  ("next_batch" if next_mode else "retest_batch" if retest_mode else "window"): run_batch,
                                                                  "study_date": current_day,
                                                                  "reserved_calls": 1}
                atomic_json(progress_path, progress)
                capture.target_id = target_id
                before_http_calls = capture.actual_calls
                response = client.post("/api/personal-questions/generate", json=body.model_dump(mode="json"))
                target_record["http_status"] = response.status_code
                target_record["model_http_calls"] = capture.actual_calls - before_http_calls
                result = safe_api_result(response)
                target_record["result"] = result
                raw_call = next((call for call in reversed(progress.get("model_calls", []))
                                 if call.get("target_id") == target_id), None)
                if response.status_code >= 400:
                    target_record["quality_status"] = "BLOCKED"
                    target_record["stop_reason"] = result.get("api_error_code")
                elif result.get("provider_error"):
                    provider_error = str(result.get("provider_error"))
                    target_record["quality_status"] = "BLOCKED" if provider_error == "AppError" else "FAIL"
                    target_record["stop_reason"] = (raw_call or {}).get("error_category") or provider_error
                else:
                    qids = result.get("question_ids", [])
                    failures = result.get("failures", [])
                    if qids:
                        with factory() as db:
                            q = db.get(Question, __import__("uuid").UUID(qids[0]))
                            if not q:
                                raise RuntimeError("reported_question_not_persisted")
                            node_row = db.get(KnowledgePoint, q.kp_id)
                            independent = verify_problem(q)
                            bound = current_generation_binding(q, node_row)
                            eligibility = __import__("backend.services.question_eligibility", fromlist=["question_eligibility"]).question_eligibility(q, node_row)
                            grading = grade_saved_question(q)
                            batch_row = db.get(PersonalGenerationBatch, q.generation_batch_id)
                            in_today_plan = db.scalar(select(func.count()).select_from(PracticeItem).where(
                                PracticeItem.question_id == q.id)) == 1
                            bank_count = bank_rows(db, scope="personal", kp_id=q.kp_id)["total"]
                        persisted = {"question_id": str(q.id), "batch_id": str(q.generation_batch_id),
                                         "bank_scope": q.bank_scope, "batch_status": batch_row.status if batch_row else None,
                                         "question_type": q.question_type, "difficulty": q.difficulty,
                                         "node_id": str(q.kp_id), "independent_verifier": independent,
                                         "generation_binding_current": bound,
                                         "practice_eligible": eligibility.practice_eligible,
                                         "evidence_capability": eligibility.evidence_capability,
                                         "strict_graduation_blocked": eligibility.evidence_capability == "personal_practice_only",
                                         "grading_smoke": grading, "in_personal_bank": True,
                                         "in_today_practice_plan": bool(in_today_plan),
                                         "personal_count_for_node": bank_count,
                                         "answer": q.correct_answer, "explanation": q.explanation,
                                         "stem": q.stem, "options": q.options}
                        persisted["study_flow"] = exercise_saved_question_routes(client, factory, q)
                        target_record["saved_question"] = persisted
                        if (independent.get("status") == "PASS" and bound and eligibility.practice_eligible
                                and eligibility.evidence_capability == "personal_practice_only"
                                and grading["correct_answer_result"] == "right" and in_today_plan
                                and persisted["study_flow"].get("status") == "PASS"):
                            target_record["quality_status"] = "PASS"
                        else:
                            target_record["quality_status"] = "UNCERTAIN"
                            if persisted["study_flow"].get("status") in {"FAIL", "BLOCKED"}:
                                target_record["stop_reason"] = "isolated_study_flow_check_failed"
                    elif failures:
                        reasons = sorted({str(row.get("reason")) for row in failures})
                        target_record["quality_status"] = classify_candidate_failures(failures)
                        target_record["failure_reasons"] = failures
                    else:
                        target_record["quality_status"] = "BLOCKED"
                progress["targets"][target_id]["status"] = target_record["quality_status"]
                progress["targets"][target_id]["batch_id"] = result.get("batch_id")
                progress["targets"][target_id]["question_ids"] = result.get("question_ids", [])
                progress["quality_rows"].append(target_record)
                progress["windows"] = sorted(set(progress.get("windows", []) + [batch_key]), key=str) if all(
                    row["target_id"] in progress["targets"] for row in window_targets) else progress.get("windows", [])
                atomic_json(progress_path, progress)
                output_rows.append(target_record)
                print(json.dumps({"target": target_id, "status": target_record["quality_status"],
                                  "model_calls": target_record["model_http_calls"],
                                  "saved": bool(target_record.get("saved_question")),
                                  "usage": raw_call.get("usage") if raw_call else None,
                                  "stop": capture.stop_reason}, ensure_ascii=False), flush=True)
                if response.status_code >= 500 or target_record.get("stop_reason") in {
                    "http_401", "http_403", "provider_usage_not_observed", "projected_cost_near_budget",
                    "pre_call_cost_reserve_near_budget", "observed_usage_outside_authorized_bound",
                    "authorized_token_budget_exhausted", "observed_total_output_budget_exceeded",
                }:
                    progress["stop_reason"] = target_record.get("stop_reason") or "provider_http_error"
                    atomic_json(progress_path, progress)
                    break
                if capture.stop_reason in {"provider_usage_not_observed", "projected_cost_near_budget",
                                           "pre_call_cost_reserve_near_budget", "observed_usage_outside_authorized_bound",
                                           "authorized_token_budget_exhausted", "authorized_output_budget_too_small_for_reliable_item",
                                           "observed_total_output_budget_exceeded", "provider_configuration_changed",
                                           "generation_prompt_exceeds_byte_budget", "retry_blocked",
                                           "authorized_request_limit_reached"}:
                    progress["stop_reason"] = capture.stop_reason
                    atomic_json(progress_path, progress)
                    break
                if target_record.get("stop_reason") == "provider_or_format_error" and (
                    ((raw_call or {}).get("error_category") or "").startswith(("http_", "network_", "total_timeout"))):
                    progress["stop_reason"] = target_record["stop_reason"]
                    atomic_json(progress_path, progress)
                    break
                if target_record.get("stop_reason") == "isolated_study_flow_check_failed":
                    progress["stop_reason"] = target_record["stop_reason"]
                    atomic_json(progress_path, progress)
                    break
                if ((raw_call or {}).get("error_category") or "").startswith(("http_", "network_", "total_timeout")):
                    progress["stop_reason"] = target_record.get("stop_reason") or "provider_transport_error"
                    atomic_json(progress_path, progress)
                    break

            progress["last_run_at"] = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()
            progress["database_revision"] = revision
            progress["database_identity"] = {"host": "127.0.0.1", "port": pg.port,
                                             "database": "kaoyan_test", "data_directory": str(pg.cluster.resolve())}
            progress["database_counts"] = {"before": before_counts, "after": counts(factory)}
            progress["cumulative_model_http_calls"] = sum(
                row.get("model_http_request_attempted") is True for row in progress.get("model_calls", []))
            progress["cumulative_peak_price_cost_cny"] = round(capture.total_cost_cny, 8)
            progress["run_day_reserved_calls"] = sum(
                int(item.get("reserved_calls", 0)) for item in progress.get("targets", {}).values()
                if item.get("study_date") == datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
            )
            progress["run_total_reserved_calls"] = sum(
                int(item.get("reserved_calls", 0)) for item in progress.get("targets", {}).values()
            )
            progress["original_development_database_connected"] = False
            progress["public_bank_written"] = False
            progress["original_graduation_policy_changed"] = False
            atomic_json(progress_path, progress)
            run_summary = {("next_batch" if next_mode else "retest_batch" if retest_mode else "window"): run_batch,
                           "targets_attempted_this_window": output_rows,
                           "model_http_calls_this_process": capture.actual_calls,
                           "cumulative_model_http_calls": sum(
                               row.get("model_http_request_attempted") is True for row in progress.get("model_calls", [])),
                           "cumulative_peak_price_cost_cny": progress["cumulative_peak_price_cost_cny"],
                           "stop_reason": progress.get("stop_reason"),
                           "database_revision": revision, "database_counts": progress["database_counts"],
                           "database_identity": progress["database_identity"],
                           "source_inventory_sha256": snapshot_sha,
                           "target_fixture_sha256": fixture_sha,
                           "source_inventory_question_rows_not_copied": True,
                           "real_model": "deepseek-flash",
                           "prompt_version": PROMPT_VERSION if (next_mode or retest_mode) else "question-generation-c2-v2",
                           "generation_version": GENERATION_VERSION if next_mode else "bounded-question-generation-v5" if retest_mode else "bounded-question-generation-v4",
                           "verifier_version": VERIFIER_VERSION if next_mode else "bounded-problem-verifiers-v8" if retest_mode else "bounded-problem-verifiers-v7",
                           "pricing_peak_cny_per_million": {"input": PEAK_INPUT_CNY_PER_M,
                                                             "output": PEAK_OUTPUT_CNY_PER_M},
                           "note": "cost is a conservative estimate, not a vendor-side hard cap",
                           "authorization": ({"max_new_calls": NEXT_MAX_CALLS,
                                              "max_per_batch": MAX_BATCH_CALLS,
                                              "max_output_tokens_per_call": NEXT_MAX_OUTPUT_TOKENS,
                                              "max_total_output_tokens": NEXT_TOTAL_OUTPUT_TOKENS,
                                              "max_conservative_tokens": NEXT_MAX_CONSERVATIVE_TOKENS,
                                              "cost_budget_cny": NEXT_COST_BUDGET_CNY}
                                             if next_mode else
                                             {"max_new_calls": RETEST_MAX_CALLS,
                                              "max_per_batch": MAX_BATCH_CALLS,
                                              "max_output_tokens_per_call": MAX_OUTPUT_TOKENS,
                                              "max_total_output_tokens": RETEST_MAX_OUTPUT_TOKENS,
                                              "max_conservative_tokens": RETEST_MAX_CONSERVATIVE_TOKENS,
                                              "cost_budget_cny": RETEST_COST_BUDGET_CNY}
                                             if retest_mode else None)}
            summary_name = (f"next-batch-{run_batch}-summary.json" if next_mode else
                            f"retest-batch-{run_batch}-summary.json" if retest_mode
                            else f"window-{run_batch}-summary.json")
            atomic_json(run_dir / summary_name, run_summary)
            print(json.dumps({"summary_file": str(run_dir / summary_name),
                              "actual_model_http_calls": capture.actual_calls,
                              "cumulative_calls": len(progress.get("model_calls", [])),
                              "cumulative_peak_cost_cny": progress["cumulative_peak_price_cost_cny"],
                              "database_revision": revision, "database_counts": progress["database_counts"],
                              "stop_reason": progress.get("stop_reason")}, ensure_ascii=False), flush=True)
            client.close()
            engine.dispose()
        finally:
            if not pg.stop():
                raise RuntimeError("temporary_postgres_normal_stop_failed; cluster retained")
        return 0
    finally:
        lock_path.unlink(missing_ok=True)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:
        # Do not print exception strings: provider/database errors may include URLs.
        message = str(exc) if isinstance(exc, RuntimeError) else "run stopped; inspect local artifacts"
        if not re.fullmatch(r"[A-Za-z0-9_:-]{1,120}", message or ""):
            message = "unexpected_runtime_error" if isinstance(exc, RuntimeError) else "run stopped; inspect local artifacts"
        if isinstance(exc, ImportError):
            # Import errors can be actionable; keep only safe module/name characters.
            candidate = str(getattr(exc, "name", None) or getattr(exc, "msg", "import_error"))
            candidate = re.sub(r"[^A-Za-z0-9_.:' -]", "?", candidate)[:120]
            message = candidate or "import_error"
        print(json.dumps({"runner_error_type": type(exc).__name__,
                          "safe_reason": message,
                          "message": "run stopped; inspect the local run artifacts and PostgreSQL log"},
                         ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2)
