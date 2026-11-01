"""Disposable, offline, writable student-journey station for 2026-10-24.

Uses a new owned PostgreSQL cluster and the ordinary Vue/FastAPI routes.
All UI writes are confined to synthetic fixtures in this run's _test database.
The model is the project's explicitly labelled fixed offline provider; outbound
DNS/HTTP from the backend is fail-closed.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
STATION_ID = os.environ.get("NAIWA_UI_TEST_STATION_ID", "r1")
if not re.fullmatch(r"[a-z0-9]{1,20}", STATION_ID):
    raise RuntimeError("invalid_isolated_station_id")
DATA_HOME = ROOT / f"storage/manual-experience/naiwa-student-ui-acceptance-20261024-{STATION_ID}"
DB_NAME = ("naiwa_student_ui_20261024_test" if STATION_ID == "r1"
           else f"naiwa_student_ui_20261024_{STATION_ID}_test")
FIXTURE_PROFILE = os.environ.get("NAIWA_UI_TEST_FIXTURE_PROFILE", "basic")
if FIXTURE_PROFILE not in {"basic", "answer_handoff_v1"} or (FIXTURE_PROFILE != "basic" and STATION_ID == "r1"):
    raise RuntimeError("invalid_isolated_fixture_profile")


def _port_from_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    try:
        port = default if raw is None else int(raw)
    except ValueError as exc:
        raise RuntimeError(f"invalid_isolated_port:{name}") from exc
    if not 18000 <= port <= 65535:
        raise RuntimeError(f"isolated_port_out_of_range:{name}")
    return port


PG_PORT = _port_from_env("NAIWA_UI_TEST_PG_PORT", 64744)
API_PORT = _port_from_env("NAIWA_UI_TEST_API_PORT", 63045)
WEB_PORT = _port_from_env("NAIWA_UI_TEST_WEB_PORT", 63046)
AUDIT_NAME = os.environ.get("NAIWA_UI_TEST_AUDIT_NAME", "naiwa-student-ui-acceptance-20261024-resume5-r1")
STOP_NAME = os.environ.get("NAIWA_UI_TEST_STOP_NAME", "stop-resume4.request")
if not re.fullmatch(r"naiwa-student-ui-acceptance-20261024-[a-z0-9-]+", AUDIT_NAME):
    raise RuntimeError("invalid_isolated_audit_name")
if not re.fullmatch(r"stop-[a-z0-9-]+\.request", STOP_NAME):
    raise RuntimeError("invalid_isolated_stop_name")
AUDIT = ROOT / "storage/quality-audits" / AUDIT_NAME
PG_BIN = Path("C:/Program Files/PostgreSQL/18/bin")
NODE = Path(r"D:\应用安装包\node.exe")
STOP = DATA_HOME / STOP_NAME


def _write_new(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, default=str)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _assert_new_and_free() -> dict:
    selected_ports = (PG_PORT, API_PORT, WEB_PORT)
    if len(set(selected_ports)) != len(selected_ports):
        raise RuntimeError("isolated_ports_must_be_distinct")
    if {5433, 8000, 5173}.intersection(selected_ports):
        raise RuntimeError("daily_service_port_forbidden_in_isolated_station")
    if AUDIT.exists():
        raise RuntimeError("student_ui_acceptance_audit_path_already_exists_stop_without_overwrite")
    resume = DATA_HOME.exists()
    if resume and FIXTURE_PROFILE == "answer_handoff_v1":
        # The handoff is a clean epoch. Never reset prior UI attempts to make a
        # used station look fresh; choose a new station ID for a clean rerun.
        raise RuntimeError("handoff_station_already_exists_use_new_epoch_preserve_data")
    if resume:
        cluster = DATA_HOME / "owned-pg/KaoyanStudy/postgres/cluster"
        marker = DATA_HOME / "owned-pg/KaoyanStudy/config/postgres-owner.json"
        version = cluster / "PG_VERSION"
        runtime_path = DATA_HOME / "runtime.json"
        if not runtime_path.is_file():
            raise RuntimeError("resume_candidate_missing_prior_runtime_record")
        prior_runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
        identity = prior_runtime.get("database_identity") or {}
        if (not marker.is_file() or not version.is_file() or version.read_text(encoding="ascii").strip() != "18"
                or (cluster / "postmaster.pid").exists() or prior_runtime.get("status") != "stopped"
                or prior_runtime.get("paid_enabled") is not False
                or prior_runtime.get("provider_mode") != "FIXED-OFFLINE-NO-PAID-MODEL"
                or identity.get("database") != DB_NAME
                or identity.get("port") != prior_runtime.get("ports", {}).get("postgres")
                or identity.get("port") in {5433, 8000, 5173}):
            raise RuntimeError("resume_candidate_is_not_stopped_owned_postgres_cluster")
        owner = json.loads(marker.read_text(encoding="utf-8"))
        expected_hash = hashlib.sha256(str(cluster.resolve()).encode("utf-8")).hexdigest()
        if (owner.get("major") != 18 or owner.get("root_hash") != expected_hash or not owner.get("cluster_id")
                or owner.get("cluster_id") != identity.get("cluster_id")):
            raise RuntimeError("resume_candidate_owner_identity_mismatch")
        uploads = DATA_HOME / "uploads"
        if not uploads.is_dir() or any(uploads.iterdir()):
            raise RuntimeError("resume_candidate_upload_directory_not_empty")
        chroma = DATA_HOME / "chroma"
        chroma_db = chroma / "chroma.sqlite3"
        if not chroma.is_dir() or {p.name for p in chroma.iterdir()} != {"chroma.sqlite3"} or not chroma_db.is_file():
            raise RuntimeError("resume_candidate_chroma_directory_unexpected_contents")
        import sqlite3
        connection = sqlite3.connect("file:" + chroma_db.as_posix() + "?mode=ro", uri=True)
        try:
            expected_empty_tables = ("embeddings", "embeddings_queue", "embedding_metadata",
                                     "embedding_fulltext_search")
            counts = {table: int(connection.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0])
                      for table in expected_empty_tables}
            collections = int(connection.execute("SELECT count(*) FROM collections").fetchone()[0])
        finally:
            connection.close()
        if any(counts.values()) or collections != 1:
            raise RuntimeError("resume_candidate_chroma_contains_document_data:" + json.dumps(counts, sort_keys=True))
    elif DATA_HOME.exists():
        raise RuntimeError("student_ui_acceptance_paths_already_exist_stop_without_overwrite")
    for path in (PG_BIN / "postgres.exe", PG_BIN / "initdb.exe", PG_BIN / "pg_ctl.exe",
                 NODE, ROOT / "frontend/node_modules/vite/bin/vite.js"):
        if not path.is_file():
            raise RuntimeError(f"required_runtime_file_missing:{path.name}")
    ports = {}
    for port in (PG_PORT, API_PORT, WEB_PORT):
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
                ports[str(port)] = "bindable"
            except OSError as exc:
                raise RuntimeError(f"selected_loopback_port_unavailable:{port}:{type(exc).__name__}") from None
    old_error = ROOT / "storage/quality-audits/naiwa-student-ui-acceptance-20261024/startup-error.json"
    prior_attempt = None
    if old_error.is_file():
        prior_attempt = {"path": str(old_error.relative_to(ROOT)), "sha256": _sha(old_error),
                         "classification": "pytest_fixture_guard_imported_by_station_seed"}
    return {"ports": ports, "database": DB_NAME, "data_home": str(DATA_HOME),
            "new_audit_dir": str(AUDIT), "not_daily_ports": True,
            "not_retained_readonly_station": True, "resuming_owned_test_cluster": resume,
            "prior_runtime_status": prior_runtime.get("status") if resume else None,
            "prior_database_identity": prior_runtime.get("database_identity") if resume else None,
            "prior_r1_startup_attempt": prior_attempt}


def _runtime_env(database_url: str) -> dict[str, str]:
    upload_dir, chroma_dir = DATA_HOME / "uploads", DATA_HOME / "chroma"
    return {
        **os.environ,
        "APP_ENV": "test",
        "APP_RUNTIME_PROFILE": "web",
        "DATABASE_URL": database_url,
        "TEST_DATABASE_URL": database_url,
        "ALLOWED_WEB_ORIGINS": json.dumps([f"http://127.0.0.1:{WEB_PORT}"]),
        "UPLOAD_DIR": str(upload_dir),
        "CHROMA_DIR": str(chroma_dir),
        "MODEL_CACHE_DIR": str(ROOT / "storage/models"),
        "MODEL_SETTINGS_PATH": str(DATA_HOME / "model-settings.bin"),
        # These are inert placeholders. The application factory is pinned to
        # FixedProvider, and the backend socket guard allows only owned PG.
        "LLM_API_KEY": "OFFLINE_FIXED_PROVIDER_NO_SECRET",
        "LLM_BASE_URL": "http://127.0.0.1:9",
        "LLM_MODEL": "FIXED-OFFLINE-NO-PAID-MODEL",
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "ANONYMIZED_TELEMETRY": "False",
        "DO_NOT_TRACK": "1",
        "OTEL_SDK_DISABLED": "true",
        "HTTP_PROXY": "",
        "HTTPS_PROXY": "",
        "ALL_PROXY": "",
        "http_proxy": "",
        "https_proxy": "",
        "all_proxy": "",
        "VITE_API_PROXY_TARGET": f"http://127.0.0.1:{API_PORT}",
        "PYTHONIOENCODING": "utf-8",
        "NAIWA_UI_TEST_DATA_HOME": str(DATA_HOME),
        "NAIWA_UI_TEST_DB": DB_NAME,
        "NAIWA_UI_TEST_PG_PORT": str(PG_PORT),
        "NAIWA_UI_TEST_API_PORT": str(API_PORT),
        "NAIWA_UI_TEST_WEB_PORT": str(WEB_PORT),
    }


def _read_table_counts(engine) -> dict[str, int]:
    from sqlalchemy import inspect, text
    names = inspect(engine).get_table_names(schema="public")
    quote = engine.dialect.identifier_preparer.quote
    with engine.connect() as connection:
        return {name: int(connection.scalar(text(f"SELECT count(*) FROM public.{quote(name)}")))
                for name in sorted(names)}


def _database_snapshot(engine) -> dict:
    """Canonical full-public-schema snapshot for this disposable station only."""
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    names = sorted(inspector.get_table_names(schema="public"))
    quote = engine.dialect.identifier_preparer.quote
    tables = {}
    with engine.connect() as connection:
        for name in names:
            primary_key = inspector.get_pk_constraint(name, schema="public").get("constrained_columns") or []
            raw_rows = connection.execute(text(
                f"SELECT to_jsonb(t)::text FROM public.{quote(name)} AS t")).scalars().all()
            rows = [json.loads(row) if isinstance(row, str) else row for row in raw_rows]
            canonical_rows = sorted(json.dumps(row, ensure_ascii=False, sort_keys=True,
                separators=(",", ":"), default=str) for row in rows)
            keys = [tuple(str(row.get(column)) for column in primary_key)
                    for row in rows] if primary_key else []
            tables[name] = {
                "row_count": len(rows),
                "primary_key_columns": primary_key,
                "primary_keys": sorted(keys),
                "sha256": hashlib.sha256("\n".join(canonical_rows).encode("utf-8")).hexdigest(),
            }
    return {"captured_at": datetime.now(timezone.utc).isoformat(),
        "database": DB_NAME, "port": PG_PORT, "schema": "public",
        "isolation": "runner-owned disposable PostgreSQL; read-only SELECT after fixture transaction",
        "tables": tables}


def _database_diff(before: dict, after: dict) -> dict:
    names = sorted(set(before.get("tables", {})) | set(after.get("tables", {})))
    changed = {}
    for name in names:
        old, new = before.get("tables", {}).get(name), after.get("tables", {}).get(name)
        if old != new:
            changed[name] = {"before": old, "after": new}
    return {"database": DB_NAME, "changed_table_count": len(changed), "changed_tables": changed}


def _verify_only_synthetic_fixture(factory, table_counts: dict[str, int]) -> dict:
    """Accept resume only when the existing DB contains this runner's fixture and nothing else."""
    from sqlalchemy import select
    from backend.models.learning import (
        KnowledgePoint, Question, QuestionAnswerVerificationEvent, QuestionVersion,
    )

    expected_counts = {
        "alembic_version": 1,
        "knowledge_points": 5,
        "questions": 5,
        "question_versions": 15,
        "question_answer_verification_events": 5,
    }
    observed_nonzero = {name: count for name, count in table_counts.items() if count}
    if observed_nonzero != expected_counts:
        raise RuntimeError("resume_database_not_exact_known_synthetic_fixture:" +
                           json.dumps(observed_nonzero, sort_keys=True))
    with factory() as db:
        nodes = db.scalars(select(KnowledgePoint)).all()
        questions = db.scalars(select(Question)).all()
        versions = db.scalars(select(QuestionVersion)).all()
        events = db.scalars(select(QuestionAnswerVerificationEvent)).all()
        expected_codes = {
            "fixture.math2", "fixture.math2.lhopital", "fixture.math2.geometric-series",
            "fixture.408", "fixture.408.linear-lists",
        }
        if {node.code for node in nodes} != expected_codes or any("SYNTHETIC" not in node.name for node in nodes):
            raise RuntimeError("resume_database_synthetic_knowledge_nodes_mismatch")
        versions_by_question = {}
        for version in versions:
            versions_by_question.setdefault(version.question_id, []).append(version)
        if (len(questions) != 5 or len(versions) != 15 or len(events) != 5
                or any(not q.stem.startswith("【SYNTHETIC 隔离练习】") for q in questions)
                or any(q.question_provenance != "trusted_practice" or q.content_trust != "verified"
                       or q.source_status != "not_applicable"
                       or q.content_reviewed_by != "isolated-synthetic-test-fixture"
                       or q.answer_reviewed_by != "isolated-synthetic-test-fixture"
                       or q.current_version_id is None for q in questions)
                or set(versions_by_question) != {q.id for q in questions}
                or any(sorted(v.version_number for v in versions_by_question.get(q.id, [])) != [1, 2, 3]
                       for q in questions)
                or any(v.question_id not in {q.id for q in questions}
                       or not v.stem.startswith("【SYNTHETIC 隔离练习】")
                       or v.review_status != "snapshot_only" for v in versions)
                or any(max(versions_by_question[q.id], key=lambda v: v.version_number).id != q.current_version_id
                       for q in questions)
                or any(e.verifier != "isolated-synthetic-test-fixture"
                       or e.note != "Synthetic test-only answer stamp, not a real review."
                       for e in events)):
            raise RuntimeError("resume_database_question_fixture_provenance_mismatch")
        if {event.question_id for event in events} != {question.id for question in questions}:
            raise RuntimeError("resume_database_fixture_verification_events_mismatch")
        return {
            "fixture_label": "SYNTHETIC_ONLY_NOT_REAL_EXAM",
            "reused_existing_synthetic_fixture": True,
            "knowledge_nodes": {node.code: str(node.id) for node in nodes},
            "questions": [{"question_id": str(q.id), "question_version_id": str(q.current_version_id),
                "kp_id": str(q.kp_id), "stem": q.stem, "type": q.question_type,
                "source_marker": "SYNTHETIC; never represented as real exam"} for q in questions],
            "fixture_count": len(questions),
            "learning_attempts_seeded": 0,
        }


def _seed_synthetic_data(factory) -> dict:
    from sqlalchemy import select
    from backend.models.learning import KnowledgePoint, Question
    from backend.models.learning import QuestionAnswerVerificationEvent
    from backend.services.answer_verification import answer_version_sha256

    def mark_synthetic_question_trusted(question, db):
        """Attach the normal isolated-fixture trust stamp, explicitly synthetic.

        Kept local so this disposable station does not import pytest's global
        database guard or depend on the integration runner's port variables.
        This is test-fixture metadata, not evidence of a real human review.
        """
        question.question_provenance = "trusted_practice"
        question.content_trust = "verified"
        question.source_status = "not_applicable"
        question.answer_provenance = "human_verified"
        question.answer_reliability = "verified"
        question.content_reviewed_by = "isolated-synthetic-test-fixture"
        question.content_reviewed_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        question.answer_reviewed_by = "isolated-synthetic-test-fixture"
        question.answer_reviewed_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        if question.id is None:
            question.id = uuid4()
        db.add(question)
        db.flush()
        answer_sha = answer_version_sha256(question)
        fixture_key = f"test-fixture:{question.id}:{answer_sha}"
        event = db.scalar(select(QuestionAnswerVerificationEvent).where(
            QuestionAnswerVerificationEvent.idempotency_key == fixture_key
        ))
        if event is None:
            event = QuestionAnswerVerificationEvent(
                id=uuid4(), question_id=question.id,
                event_type="verified", verification_type="human_verified",
                answer_sha256=answer_sha,
                verification_method="isolated synthetic test fixture",
                verifier="isolated-synthetic-test-fixture",
                source_metadata={"kind": "human_review"},
                note="Synthetic test-only answer stamp, not a real review.",
                idempotency_key=fixture_key,
                created_at=question.answer_reviewed_at,
            )
        db.add(event)
        db.flush()
        question.current_answer_verification = event
        question.answer_verification_event_id = event.id
        db.flush()

    root_math, lhopital, geometric = uuid4(), uuid4(), uuid4()
    root_cs, lists = uuid4(), uuid4()
    first_answer, v3_node = uuid4(), uuid4()
    with factory.begin() as db:
        db.add_all([
            KnowledgePoint(id=root_math, code="fixture.math2", name="数学二（SYNTHETIC）",
                subject="考研数学", ordinal=990, is_assessable=False, is_active=True,
                summary="仅用于隔离用户旅程验收的合成知识点。"),
            KnowledgePoint(id=lhopital, code="fixture.math2.lhopital", name="洛必达法则（SYNTHETIC）",
                subject="考研数学", parent_id=root_math, ordinal=1, is_assessable=True, is_active=True,
                summary="隔离合成节点，不代表正式课程或真题数据。"),
            KnowledgePoint(id=geometric, code="fixture.math2.geometric-series", name="等比级数（SYNTHETIC）",
                subject="考研数学", parent_id=root_math, ordinal=2, is_assessable=True, is_active=True,
                summary="隔离合成节点，不代表正式课程或真题数据。"),
            KnowledgePoint(id=root_cs, code="fixture.408", name="408（SYNTHETIC）",
                subject="408", ordinal=990, is_assessable=False, is_active=True,
                summary="仅用于隔离用户旅程验收的合成知识点。"),
            KnowledgePoint(id=lists, code="fixture.408.linear-lists", name="线性表（SYNTHETIC）",
                subject="408", parent_id=root_cs, ordinal=1, is_assessable=True, is_active=True,
                summary="隔离合成节点，不代表正式课程或真题数据。"),
        ])
        if FIXTURE_PROFILE == "answer_handoff_v1":
            db.add_all([
                KnowledgePoint(id=first_answer, code="fixture.math2.first-answer", name="首次作答·无专门策略（SYNTHETIC）",
                    subject="考研数学", parent_id=root_math, ordinal=3, is_assessable=True, is_active=True,
                    summary="本轮专用合成节点：初始没有KpState和KpMasteryPolicy；作答必须由页面提交。"),
                KnowledgePoint(id=v3_node, code="fixture.math2.v3-guard", name="v3冻结题集校验（SYNTHETIC）",
                    subject="考研数学", parent_id=root_math, ordinal=4, is_assessable=True, is_active=True,
                    summary="本轮专用合成正式题集，用于核对原有绑定和毕业约束；不是实际学生的掌握证据。"),
            ])
        db.flush()
        rows = [
            Question(kp_id=lhopital, question_type="single_choice", question_role="basic",
                grading_mode="auto", grading_config={"verified": True, "method": "single_choice", "version": "SYNTHETIC_UI_FIXTURE"},
                difficulty="basic", estimated_minutes=3, is_variant=False, skill_tags=["SYNTHETIC_TEST", "0/0 型"],
                stem="【SYNTHETIC 隔离练习】求极限 lim(x→0) (e^x−1)/x。",
                options={"A": "0", "B": "1", "C": "e", "D": "不存在"}, correct_answer="B",
                explanation="【合成题解析】分子分母趋于 0，且在去心邻域可导；求导后得 lim e^x=1。此题不是历年真题。"),
            Question(kp_id=lhopital, question_type="single_choice", question_role="typical",
                grading_mode="auto", grading_config={"verified": True, "method": "single_choice", "version": "SYNTHETIC_UI_FIXTURE"},
                difficulty="intermediate", estimated_minutes=5, is_variant=True, variant_group="synthetic-lhopital-ui",
                skill_tags=["SYNTHETIC_TEST", "无穷比无穷"],
                stem="【SYNTHETIC 隔离练习】求极限 lim(x→∞) ln(x)/x。",
                options={"A": "0", "B": "1", "C": "∞", "D": "不存在"}, correct_answer="A",
                explanation="【合成题解析】为 ∞/∞ 型，分子分母在充分大处可导，导数之比为 1/x，极限为 0。此题不是历年真题。"),
            Question(kp_id=lhopital, question_type="fill_blank", question_role="basic",
                grading_mode="self_assessed", grading_config={"verified": True, "method": "numeric_final", "version": "SYNTHETIC_UI_FIXTURE"},
                difficulty="basic", estimated_minutes=4, is_variant=False,
                skill_tags=["SYNTHETIC_TEST", "洛必达"],
                stem="【SYNTHETIC 隔离练习】求 lim(x→0) (sin x)/x。",
                options=None, correct_answer="1",
                explanation="【合成题解析】这是 0/0 型；洛必达后为 cos x，极限为 1。此题不是历年真题。"),
            Question(kp_id=geometric, question_type="calculation", question_role="basic",
                grading_mode="self_assessed", grading_config={"verified": True, "method": "numeric_final", "version": "SYNTHETIC_UI_FIXTURE"},
                difficulty="basic", estimated_minutes=5, is_variant=False,
                skill_tags=["SYNTHETIC_TEST", "收敛区间"],
                stem="【SYNTHETIC 隔离练习】当 |x|<1 时，求 Σ(n=0…∞) x^n 的和函数。",
                options=None, correct_answer="1/(1-x)",
                explanation="【合成题解析】有限和为 (1−x^(N+1))/(1−x)；当 |x|<1 时 x^(N+1)→0，因此和为 1/(1−x)。端点需另行检查。此题不是历年真题。"),
            Question(kp_id=lists, question_type="single_choice", question_role="basic",
                grading_mode="auto", grading_config={"verified": True, "method": "single_choice", "version": "SYNTHETIC_UI_FIXTURE"},
                difficulty="basic", estimated_minutes=4, is_variant=False,
                skill_tags=["SYNTHETIC_TEST", "顺序表"],
                stem="【SYNTHETIC 隔离练习】顺序表已知下标 i，要读取 A[i]，时间复杂度通常为哪一项？",
                options={"A": "O(n)", "B": "O(1)", "C": "O(log n)", "D": "O(n log n)"}, correct_answer="B",
                explanation="【合成题解析】顺序存储可通过基地址与下标直接计算元素地址，因此随机访问为 O(1)。此题不是历年真题。"),
        ]
        v3_questions = []
        if FIXTURE_PROFILE == "answer_handoff_v1":
            specs = [
                (r"求 $\lim_{x\to\infty}\frac{\ln x}{x}$。", {"A":"0","B":"1","C":r"$\infty$","D":"不存在"}, "A", "导数之比为1/x，极限为0。"),
                (r"求 $\lim_{x\to0}\frac{e^x-1}{x}$。", {"A":"0","B":"1","C":"e","D":"不存在"}, "B", "导数之比为e^x，极限为1。"),
                (r"求 $\lim_{x\to0}\frac{1-\cos x}{x^2}$。", {"A":"0","B":"1","C":r"$\frac12$","D":"不存在"}, "C", "两次求导得到cos(x)/2，极限为1/2。"),
            ]
            for target in (first_answer, v3_node):
                for index, (stem, options, answer, explanation) in enumerate(specs):
                    q = Question(kp_id=target, question_type="single_choice", question_role="basic",
                        grading_mode="auto", grading_config={"verified":True,"method":"single_choice","version":"SYNTHETIC_UI_HANDOFF"},
                        difficulty="basic", estimated_minutes=5, is_variant=index == 1, skill_tags=["SYNTHETIC_TEST"],
                        stem=f"【SYNTHETIC {'无策略' if target == first_answer else 'v3冻结'} H{index+1}】" + stem,
                        options=options, correct_answer=answer, explanation="【合成解析】" + explanation + "不是历年真题。")
                    rows.append(q)
                    if target == v3_node:
                        v3_questions.append(q)
        db.add_all(rows)
        db.flush()
        for question in rows:
            mark_synthetic_question_trusted(question, db)
        db.flush()
        if v3_questions:
            from backend.services.graduation_question_set import freeze_graduation_question_set
            freeze_graduation_question_set(db, kp_id=v3_node, question_ids=[q.id for q in v3_questions],
                reason="SYNTHETIC UI handoff: unchanged v3 graduation safeguards")
            db.flush()
        if any(not q.current_version_id for q in rows):
            raise RuntimeError("synthetic_question_version_not_created")
        return {"fixture_label": "SYNTHETIC_ONLY_NOT_REAL_EXAM",
                "knowledge_nodes": {"math_root": str(root_math), "lhopital": str(lhopital),
                    "geometric_series": str(geometric), "408_root": str(root_cs), "linear_lists": str(lists)},
                "handoff_nodes": ({"first_answer_without_state_or_policy": str(first_answer),
                    "v3_frozen_set": str(v3_node)} if FIXTURE_PROFILE == "answer_handoff_v1" else {}),
                "questions": [{"question_id": str(q.id), "question_version_id": str(q.current_version_id),
                    "kp_id": str(q.kp_id), "stem": q.stem, "type": q.question_type,
                    "options": q.options, "expected_answer_for_tester": q.correct_answer,
                    "source_marker": "SYNTHETIC; never represented as real exam"} for q in rows],
                "fixture_count": len(rows), "learning_attempts_seeded": 0}


def _install_backend_socket_guard() -> None:
    log_path = DATA_HOME / "blocked-network.jsonl"
    def guard(event, args):
        if event == "socket.getaddrinfo" and args and args[0] not in {None, "127.0.0.1", "localhost", "::1"}:
            with log_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"event": "blocked_external_dns", "host_class": "non_loopback"}) + "\n")
            raise RuntimeError("student_ui_test_external_dns_blocked")
        if event == "socket.connect" and len(args) >= 2:
            address = args[1]
            allowed = isinstance(address, tuple) and len(address) >= 2 and address[0] in {"127.0.0.1", "::1"} and address[1] == PG_PORT
            if not allowed:
                with log_path.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps({"event": "blocked_external_socket", "loopback": bool(isinstance(address, tuple) and address and address[0] in {"127.0.0.1", "::1"})}) + "\n")
                raise RuntimeError("student_ui_test_external_http_blocked")
    sys.addaudithook(guard)


def _active_isolated_get_fault(*, method: str, path: str, marker_dir: Path,
                               station_id: str, now: float | None = None) -> dict | None:
    """Read one runner-owned, short-lived GET fault marker; never accepts browser input."""
    if method != "GET":
        return None
    if path == "/api/chat/sessions":
        route, session_id, marker_name = "sessions", None, "fault-chat-sessions-500.json"
    else:
        match = re.fullmatch(r"/api/chat/sessions/([0-9a-fA-F-]{36})/messages", path)
        if not match:
            return None
        try:
            session_id = str(UUID(match.group(1)))
        except ValueError:
            return None
        if session_id != match.group(1).lower():
            return None
        route, marker_name = "messages", "fault-chat-messages-500.json"
    marker = marker_dir / marker_name
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    current = time.time() if now is None else now
    expires_at = payload.get("expires_at") if isinstance(payload, dict) else None
    if (not isinstance(payload, dict) or payload.get("station_id") != station_id
            or payload.get("route") != route or type(expires_at) not in (int, float)
            or expires_at <= current or expires_at > current + 3600):
        return None
    if route == "messages" and payload.get("session_id") != session_id:
        return None
    return {"route": route, "session_id": session_id}


def app_factory():
    if os.environ.get("APP_ENV") != "test" or os.environ.get("NAIWA_UI_TEST_DB") != DB_NAME:
        raise RuntimeError("student_ui_app_factory_test_identity_mismatch")
    _install_backend_socket_guard()
    from scripts import manual_naiwa_experience as fixed
    fixed.HOME = DATA_HOME / "fixed-provider-state"
    fixed.HOME.mkdir(parents=True, exist_ok=True)
    from backend.chat import service
    provider_type = fixed.FixedProvider
    if FIXTURE_PROFILE == "answer_handoff_v1":
        from scripts.naiwa_answer_handoff_provider import HandoffEvidenceProvider
        provider_type = HandoffEvidenceProvider
    service.Provider = provider_type
    from backend.api.routes import chat as chat_routes
    chat_routes.provider_from_settings = service.provider_from_settings
    from backend.app import create_app
    app = create_app()
    # Runner-owned, GET-only fault injection for independent UI acceptance.
    # Never enabled by production factories or by arbitrary browser input.
    if FIXTURE_PROFILE == 'answer_handoff_v1' and os.environ.get('NAIWA_UI_TEST_FAULTS') == '1':
        from starlette.responses import JSONResponse
        @app.middleware('http')
        async def isolated_get_faults(request, call_next):
            marker = DATA_HOME / 'fault-builtin-materials-500.flag'
            if (request.method == 'GET' and request.url.path == '/api/materials'
                    and request.query_params.get('source_type') == 'builtin'
                    and marker.is_file() and 0 <= time.time()-marker.stat().st_mtime <= 3600):
                return JSONResponse({'error':{'code':'internal_error','message':'internal error'},
                    'test_simulation':True},status_code=500,headers={'X-Test-Fault':'builtin-materials-500'})
            fault = _active_isolated_get_fault(method=request.method, path=request.url.path,
                marker_dir=DATA_HOME, station_id=STATION_ID)
            if fault:
                fault_name = "chat-sessions-500" if fault["route"] == "sessions" else "chat-messages-500"
                return JSONResponse({'error':{'code':'database_unavailable','message':'database unavailable'},
                    'test_simulation':True},status_code=503,headers={'X-Test-Fault':fault_name})
            return await call_next(request)
    app.state.personal_generation_provider = provider_type(structured_generation=True)
    # Captured once in the backend process, before accepting requests. Never
    # return credentials, environment values or database URLs.
    import marshal
    from backend.mastery.storage import policy_for_node
    from backend.services.answer_submission_service import submit_answer
    from backend.services.learning_evidence_query import learning_evidence_query
    from backend.services.learner_self_report import extract_self_reports
    from backend.services.learning_assistant_service import prepare_planner
    from backend.services.learning_task_service import _missing_plan_message
    from backend.services.study_activity_schedule import build_schedule, validate_schedule
    loaded_paths = ["backend/mastery/storage.py", "backend/services/answer_submission_service.py",
        "backend/api/routes/study.py", "backend/errors.py", "frontend/src/lib/answerSubmissionFailure.ts",
        "backend/schemas/practice.py", "backend/services/answer_grading.py",
        "frontend/src/pages/StudyPage.vue", "frontend/src/components/StudyFocus.vue", __file__,
        "frontend/src/lib/answerFeedback.ts", "scripts/naiwa_answer_handoff_provider.py"]
    loaded_paths += ['frontend/src/pages/ChatPage.vue', 'backend/services/practice_retry_service.py',
        'backend/services/learning_task_service.py', 'backend/services/learning_task_tools.py',
        'backend/models/learning.py', 'migrations/versions/f56b8c9012d4_standalone_practice_retry.py']
    loaded_paths += ['backend/services/learning_assistant_service.py', 'backend/services/assistant_router.py',
        'backend/services/assistant_data_queries.py', 'backend/services/learner_self_report.py',
        'backend/services/learning_evidence_query.py', 'backend/services/personal_generation_intent.py',
        'backend/services/planner_facts.py', 'frontend/src/components/LearningTaskPanel.vue',
        'frontend/src/components/KnowledgeQuestionPickerTree.vue', 'frontend/src/lib/practiceTree.ts',
        'frontend/src/lib/studyRetryContext.ts', 'frontend/src/lib/generationConfirmationReply.ts',
        'frontend/src/router.ts', 'frontend/src/pages/NotFoundPage.vue', 'backend/services/study_activity_schedule.py']
    loaded = {"pid":os.getpid(),"database":DB_NAME,"postgres_port":PG_PORT,
        "provider":"FIXED-OFFLINE-NO-PAID-MODEL","paid_enabled":False,"fixture_profile":FIXTURE_PROFILE,
        "source_sha256":{str(Path(p).resolve().relative_to(ROOT)):_sha(ROOT / p) for p in loaded_paths},
        "function_code_sha256":{f.__name__:hashlib.sha256(marshal.dumps(f.__code__)).hexdigest()
            for f in (policy_for_node,submit_answer,learning_evidence_query,extract_self_reports,prepare_planner,_missing_plan_message,build_schedule,validate_schedule)}}
    _write_new(AUDIT / "backend-loaded-code.json", loaded)
    @app.get("/__test/runtime")
    def isolated_runtime_identity():
        return loaded
    return app


def _identity(manager, database: str) -> dict:
    from sqlalchemy import text
    from scripts.docker_test_postgres import DockerTestPostgres
    if isinstance(manager, DockerTestPostgres):
        return manager.identity(database)
    with manager._connect(user="kaoyan_app", database=database) as connection:
        row = connection.execute("SELECT current_database(), current_user, host(inet_server_addr()), inet_server_port()").fetchone()
    with manager._connect() as admin:
        system_identifier = admin.execute("SELECT system_identifier FROM pg_control_system()").fetchone()[0]
    if (row[0], row[1], row[2], row[3]) != (database, "kaoyan_app", "127.0.0.1", PG_PORT):
        raise RuntimeError("student_ui_database_connection_identity_mismatch")
    expected_dir = (DATA_HOME / "owned-pg/KaoyanStudy/postgres/cluster").resolve()
    if manager.cluster.resolve() != expected_dir or manager._identity() != manager._owned_identity:
        raise RuntimeError("student_ui_database_path_or_process_identity_not_isolated")
    if database in {"kaoyan", "kaoyan_desktop", "naiwa_experience_test"}:
        raise RuntimeError("student_ui_database_path_or_name_not_isolated")
    if PG_PORT == 5433 or not manager.owner or manager.owner.get("cluster_id") is None:
        raise RuntimeError("student_ui_cluster_identity_invalid")
    return {"database": row[0], "role": row[1], "host": row[2], "port": row[3],
            "data_directory": str(expected_dir), "data_directory_proof": "resolved owned cluster plus exact postmaster.pid PID/path/port identity",
            "cluster_id": manager.owner["cluster_id"],
            "postgres_system_identifier": str(system_identifier),
            "cluster_created_for_this_acceptance": True}


def serve() -> None:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text
    from sqlalchemy.engine import make_url
    from backend.config import get_settings
    from backend.db import create_db_engine, create_session_factory
    from desktop.postgres import ADMIN, APP_USER, ManagedPostgres
    from desktop.runtime_paths import RuntimePaths

    preflight = _assert_new_and_free()
    if not preflight["resuming_owned_test_cluster"]:
        DATA_HOME.mkdir(parents=True, exist_ok=False)
    AUDIT.mkdir(parents=True, exist_ok=False)
    if preflight["resuming_owned_test_cluster"]:
        previous_runtime = json.loads((DATA_HOME / "runtime.json").read_text(encoding="utf-8"))
        _write_new(AUDIT / "previous-runtime.json", previous_runtime)
    (DATA_HOME / "uploads").mkdir(exist_ok=preflight["resuming_owned_test_cluster"])
    (DATA_HOME / "chroma").mkdir(exist_ok=preflight["resuming_owned_test_cluster"])
    paths = RuntimePaths.windows(resources=ROOT / "backend", local_app_data=DATA_HOME / "owned-pg")
    if os.environ.get("NAIWA_UI_TEST_POSTGRES_MODE", "native") == "docker":
        from scripts.docker_test_postgres import DockerTestPostgres
        manager = DockerTestPostgres(station=STATION_ID, port=PG_PORT, audit=AUDIT)
    elif os.environ.get("NAIWA_UI_TEST_POSTGRES_MODE", "native") == "native":
        manager = ManagedPostgres(paths, PG_BIN, port=PG_PORT)
    else:
        raise RuntimeError("unknown_postgres_test_mode")
    children: list[subprocess.Popen] = []
    handles = []
    runtime = {"status": "preparing", "pid_supervisor": os.getpid(), "ports": {"postgres": PG_PORT, "api": API_PORT, "web": WEB_PORT},
        "database": DB_NAME, "data_home": str(DATA_HOME), "audit_dir": str(AUDIT),
        "provider_mode": "FIXED-OFFLINE-NO-PAID-MODEL", "paid_enabled": False, "real_model_requests": 0,
        "write_scope": "user-authorized local UI flows only; fresh synthetic _test database; exact same-origin loopback; no production data",
        "daily_services_touched": False, "read_only_station_reused": False}
    try:
        manager.start()
        from psycopg import sql
        with manager._connect() as admin:
            existing_owner = admin.execute("SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname=%s", (DB_NAME,)).fetchone()
            if existing_owner is None:
                admin.execute(sql.SQL("CREATE DATABASE {} OWNER {} TEMPLATE template0 ENCODING 'UTF8'").format(
                    sql.Identifier(DB_NAME), sql.Identifier(APP_USER)))
            elif not preflight["resuming_owned_test_cluster"] or existing_owner[0] != APP_USER:
                raise RuntimeError("target_database_exists_or_has_unexpected_owner_stop_without_overwrite")
        started_identity = _identity(manager, DB_NAME)
        previous_identity = preflight.get("prior_database_identity")
        if previous_identity and any(
                started_identity.get(key) != previous_identity.get(key)
                for key in ("database", "role", "data_directory", "cluster_id", "postgres_system_identifier")):
            raise RuntimeError("resumed_isolated_postgres_identity_changed")
        db_url = make_url(manager.database_url).set(database=DB_NAME).render_as_string(hide_password=False)
        env = _runtime_env(db_url)
        # Keep the connection URL in this supervisor's environment only; never
        # serialize it to runtime manifests, logs, or command-line arguments.
        os.environ.update(env)
        get_settings.cache_clear()
        settings = get_settings()
        if settings.app_env != "test" or str(settings.active_database_url).split("/")[-1] != DB_NAME:
            raise RuntimeError("settings_resolved_to_non_target_database")
        engine = create_db_engine(db_url)
        try:
            if preflight["resuming_owned_test_cluster"]:
                user_tables = ("knowledge_points", "questions", "question_versions", "daily_plans",
                    "practice_items", "question_attempts", "learning_events", "chat_sessions",
                    "chat_messages", "materials", "practice_requests", "learning_tasks",
                    "personal_question_generation_batches")
                with engine.connect() as connection:
                    existing_counts = {}
                    for table in user_tables:
                        exists = connection.scalar(text("SELECT to_regclass(:name)"), {"name": f"public.{table}"})
                        if exists is not None:
                            count = int(connection.scalar(text(f"SELECT count(*) FROM public.{table}")))
                            existing_counts[table] = count
            config = Config(str(ROOT / "alembic.ini"))
            config.set_main_option("script_location", str(ROOT / "migrations"))
            command.upgrade(config, "head")
            factory = create_session_factory(engine)
            if preflight["resuming_owned_test_cluster"] and any(existing_counts.values()):
                table_counts = _read_table_counts(engine)
                fixture = _verify_only_synthetic_fixture(factory, table_counts)
                fixture["reused_existing_synthetic_fixture"] = True
            else:
                fixture = _seed_synthetic_data(factory)
                fixture["reused_existing_synthetic_fixture"] = False
            with engine.connect() as connection:
                table_counts = _read_table_counts(engine)
            database_before = _database_snapshot(engine)
            _write_new(AUDIT / "database-before.json", database_before)
        finally:
            engine.dispose()
        runtime["status"] = "database_identity_check"
        identity = _identity(manager, DB_NAME)
        source_files = ["backend/app.py", "backend/config.py", "backend/api/routes/chat.py",
            "backend/api/routes/study.py", "backend/api/routes/materials.py", "backend/chat/service.py",
            "backend/services/learning_assistant_service.py", "backend/services/answer_submission_service.py",
            "backend/services/answer_grading.py", "backend/schemas/practice.py",
            "backend/services/learning_task_service.py", "scripts/naiwa_answer_handoff_provider.py",
            "frontend/src/pages/StudyPage.vue", "frontend/src/pages/ChatPage.vue",
            "frontend/src/pages/MaterialsPage.vue", "frontend/src/components/StudyFocus.vue",
            "frontend/src/lib/answerFeedback.ts", "frontend/vite.config.ts",
            "scripts/manual_naiwa_experience.py",
            "scripts/naiwa_student_ui_acceptance_20261024.py"]
        source_files += ['backend/services/assistant_router.py', 'backend/services/assistant_data_queries.py',
            'backend/services/learner_self_report.py', 'backend/services/learning_evidence_query.py',
            'backend/services/personal_generation_intent.py', 'backend/services/planner_facts.py',
            'frontend/src/components/LearningTaskPanel.vue', 'frontend/src/components/KnowledgeQuestionPickerTree.vue',
            'frontend/src/lib/practiceTree.ts', 'frontend/src/lib/studyRetryContext.ts',
            'frontend/src/lib/generationConfirmationReply.ts', 'frontend/src/router.ts',
            'frontend/src/pages/NotFoundPage.vue', 'frontend/src/App.vue','backend/services/study_activity_schedule.py']
        runtime.update({"status": "starting_services", "database_identity": identity,
            "preflight": preflight, "fixture": fixture, "initial_table_counts": table_counts,
            "source_sha256": {name: _sha(ROOT / name) for name in source_files},
            "network_policy": "backend DNS and non-PostgreSQL sockets are blocked; local fixed Provider",
            "initialized_at": time.time()})
        _write_new(AUDIT / "station-preparation.json", runtime)
        # runtime.json is this owned station's mutable liveness record. On a
        # verified resume, its previous bytes were preserved above in the new
        # immutable audit directory before this operational record is updated.
        if preflight["resuming_owned_test_cluster"]:
            (DATA_HOME / "runtime.json").write_text(
                json.dumps(runtime, ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            _write_new(DATA_HOME / "runtime.json", runtime)
        commands = [
            [sys.executable, "-m", "uvicorn", "scripts.naiwa_student_ui_acceptance_20261024:app_factory",
             "--factory", "--host", "127.0.0.1", "--port", str(API_PORT)],
            [str(NODE), "node_modules/vite/bin/vite.js", "--host", "127.0.0.1", "--port", str(WEB_PORT), "--strictPort"],
        ]
        for name, argv, cwd in zip(("backend", "frontend"), commands, (ROOT, ROOT / "frontend")):
            handle = (AUDIT / f"{name}.log").open("x", encoding="utf-8")
            handles.append(handle)
            children.append(subprocess.Popen(argv, cwd=cwd, env=env, stdout=handle, stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)))
        runtime.update({"backend_pid": children[0].pid, "frontend_pid": children[1].pid,
            "commands": [[Path(a[0]).name, *a[1:]] for a in commands],
            "urls": {"chat": f"http://127.0.0.1:{WEB_PORT}/chat", "today": f"http://127.0.0.1:{WEB_PORT}/study",
                     "materials": f"http://127.0.0.1:{WEB_PORT}/materials", "knowledge": f"http://127.0.0.1:{WEB_PORT}/knowledge"}})
        from urllib.error import URLError
        import urllib.request
        for _ in range(90):
            if any(child.poll() is not None for child in children):
                raise RuntimeError("isolated_service_child_exited_check_logs")
            try:
                request = urllib.request.Request(f"http://127.0.0.1:{API_PORT}/api/health")
                with urllib.request.urlopen(request, timeout=3) as response:
                    body = json.loads(response.read().decode("utf-8"))
                if body.get("database") == "connected":
                    runtime["health"] = body
                    break
            except (URLError, TimeoutError, OSError):
                time.sleep(1)
        else:
            raise RuntimeError("isolated_backend_health_timeout")
        runtime["status"] = "running"
        runtime["started_at"] = time.time()
        snapshot_engine = create_db_engine(db_url)
        try:
            database_after = _database_snapshot(snapshot_engine)
        finally:
            snapshot_engine.dispose()
        _write_new(AUDIT / "database-after-startup.json", database_after)
        _write_new(AUDIT / "database-diff-startup.json", _database_diff(database_before, database_after))
        _write_new(AUDIT / "startup-verification.json", {
            "status": "RUNNING_FIXED_PROVIDER", "url": runtime["urls"]["chat"],
            "database_identity": identity, "table_counts": table_counts,
            "health": runtime["health"], "provider": runtime["provider_mode"],
            "paid_enabled": False, "real_model_requests": 0, "external_dns_http_allowed": False,
            "same_origin_write_policy": "APP_ENV=test plus exact loopback Vue Origin; ordinary app handlers only"})
        (DATA_HOME / "runtime.json").write_text(json.dumps(runtime, ensure_ascii=False, indent=2), encoding="utf-8")
        while not STOP.exists():
            if any(child.poll() is not None for child in children):
                raise RuntimeError("isolated_service_child_exited_during_runtime")
            time.sleep(1)
    except BaseException as exc:
        if not (AUDIT / "startup-error.json").exists():
            error_record = {"type": type(exc).__name__, "reason": str(exc)[:500],
                "stage": runtime.get("status"), "real_model_requests": 0, "paid_enabled": False}
            diagnostic = getattr(exc, "diagnostic", None)
            if diagnostic is not None:
                error_record["diagnostic"] = diagnostic
            _write_new(AUDIT / "startup-error.json", error_record)
        raise
    finally:
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=5)
        for handle in handles:
            handle.close()
        if manager._owned_identity is not None:
            manager.stop()
        if (DATA_HOME / "runtime.json").is_file():
            latest = json.loads((DATA_HOME / "runtime.json").read_text(encoding="utf-8"))
            latest["status"] = "stopped"
            latest["stopped_at"] = time.time()
            (DATA_HOME / "runtime.json").write_text(json.dumps(latest, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("serve", "stop", "status"))
    action = parser.parse_args().action
    if action == "stop":
        if not DATA_HOME.exists():
            raise SystemExit("station_not_created")
        STOP.touch(exist_ok=True)
        print("Stop requested for this newly owned station; database files are retained.")
        return 0
    if action == "status":
        path = DATA_HOME / "runtime.json"
        print(path.read_text(encoding="utf-8") if path.is_file() else "not_started")
        return 0
    serve()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
