"""Validate frozen Phase 5 plans and optionally inspect the real DB READ ONLY.

This tool never grants permissions, starts PostgreSQL, seeds data, calls a model,
or starts the app lifespan. Its only output writes are local evidence JSON.
"""
from __future__ import annotations

import argparse
from collections import Counter, deque
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DATA = ROOT / "eval/phase5-closeout-v1"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def validate_cases():
    from backend.schemas.learning_assistant import AssistantRequest, StudyContext
    from backend.services.assistant_router import route_message
    from backend.services.personal_generation_intent import explicitly_generate

    data = load(DATA / "cases.json")
    fixtures = load(DATA / "fixtures.json")
    nodes = {r["code"]: r for r in load(ROOT / "tests/fixtures/phase45i_generation_targets.json")["nodes"]}
    cases = data["cases"]
    assert len(cases) == len({r["id"] for r in cases}) == 40
    assert {r["id"] for r in cases} == {f"{p}{i:02}" for p in ("Q", "A") for i in range(1, 21)}
    assert Counter(r["track"] for r in cases) == {"qa": 20, "agent": 20}
    assert Counter(r["category"] for r in cases if r["track"] == "qa") == {
        "math_knowledge": 4, "cs_knowledge": 4, "uploaded_rag": 4,
        "multi_turn": 3, "insufficient_or_scope": 3, "complex": 2}
    assert Counter(r["category"] for r in cases if r["track"] == "agent") == {
        "no_history": 3, "weak_node": 4, "recent_wrong": 3,
        "assisted_correct": 3, "graduated": 3, "time_preference": 2,
        "conflicting_evidence": 2}
    routes = {}
    for case in cases:
        ctx = StudyContext(surface="study" if case["track"] == "agent" else "chat")
        AssistantRequest(question=case["input"], study_context=ctx)
        assert case.get("expected"), case["id"]
        if case.get("node"):
            assert data["node_keys"][case["node"]] in nodes
        if case["track"] == "agent":
            assert case["profile"] in fixtures["profiles"]
            generation_risk = explicitly_generate(case["input"])
            route = route_message(case["input"], ctx)
            # assistant_stream otherwise handles review queries deterministically.
            import re
            direct_review = bool(re.search(r"毕业|近期|最近|为什么|为何", case["input"])) and bool(
                re.search(r"复习|巩固|熟练", case["input"])) and not re.search(r"安排|加入|生成|出题", case["input"])
            routes[case["id"]] = {"capability": route.capability, "intent": route.intent,
                "reason": route.reason, "generation_intent_risk": generation_risk,
                "deterministic_review_route": direct_review,
                "execution_precondition": "BLOCKED_UNEXPECTED_GENERATION_INTENT" if generation_risk else
                    "VERIFY_ACTUAL_ROUTE_AND_TOOL_TRACE"}
        for material in case.get("material_scope", []):
            assert material in {r["key"] for r in fixtures["materials"]}
    return {"case_count": 40, "schema_validation": "PASS", "agent_static_routes": routes}


def reference_checks():
    import sympy as sp
    x, t = sp.symbols("x t", real=True)
    a = sp.symbols("a", positive=True)
    assert sp.limit((sp.log(1+x)-x+x*x/2)/x**3, x, 0) == sp.Rational(1, 3)
    assert sp.integrate(x*sp.log(1+x), (x, 0, 1)) == sp.Rational(1, 4)
    assert sp.integrate(t*sp.exp(-a*t), (t, 0, sp.oo)) == a**-2
    b = sp.Matrix([[1, 1, 1], [1, a, 1], [1, 1, a]])
    assert sp.factor(b.det()) == (a-1)**2 and b.subs(a, 1).rank() == 1
    assert b * sp.Matrix([1, 0, 0]) == sp.ones(3, 1)
    matrix = sp.Matrix([[1, 1], [0, 1]])
    assert (matrix-sp.eye(2))**2 == sp.zeros(2)
    assert (matrix-sp.eye(2)).nullspace() == [sp.Matrix([1, 0])]
    for n in range(1, 9):
        assert matrix**n == sp.Matrix([[1, n], [0, 1]])
    assert sp.simplify((sp.log(x)-a*x).subs(x, 1/a)) == -sp.log(a)-1
    assert struct.unpack(">f", bytes.fromhex("3fc00000"))[0] == 1.5
    assert int("10000000", 2)-256 == -128
    assert 13-5-(5-1) == 4
    assert 5 + sp.Rational(1, 10)*100 + 10 + sp.Rational(1, 5)*100 == 45
    paging = {}
    for policy in ("FIFO", "LRU"):
        frames = deque()
        faults = 0
        trace = []
        for page in [1, 2, 3, 1, 4, 5]:
            miss = page not in frames
            if miss:
                faults += 1
                if len(frames) == 3:
                    frames.popleft()
                frames.append(page)
            elif policy == "LRU":
                frames.remove(page)
                frames.append(page)
            trace.append({"page": page, "miss": miss, "ordered_pages": list(frames)})
        paging[policy] = {"faults": faults, "pages": sorted(frames), "trace": trace}
    assert paging["FIFO"]["faults"] == paging["LRU"]["faults"] == 5
    assert paging["FIFO"]["pages"] == [3, 4, 5] and paging["LRU"]["pages"] == [1, 4, 5]
    return {"status": "PASS", "method": "exact SymPy, integer arithmetic, IEEE754 unpack, algorithm simulation",
            "model_calls": 0, "paging": paging,
            "note": "Checks reference facts only. No real model output or seeded learner scenario has been evaluated."}


def inspect_readonly():
    import psycopg
    from psycopg import sql
    from sqlalchemy.engine import make_url
    from backend.config import get_settings
    from backend.models import import_models
    from backend.models.base import Base
    import_models()
    target = make_url(str(get_settings().active_database_url))
    assert (target.host, target.port, target.database) == ("127.0.0.1", 5433, "kaoyan")
    with psycopg.connect(target.set(drivername="postgresql").render_as_string(hide_password=False),
                        autocommit=True, connect_timeout=5,
                        options="-c default_transaction_read_only=on") as conn:
        with conn.cursor() as c:
            c.execute("BEGIN READ ONLY")
            c.execute("SELECT current_user,session_user,current_database(),inet_server_addr()::text,inet_server_port(),current_setting('transaction_read_only'),current_setting('server_version')")
            identity = dict(zip(["role", "session_role", "database", "address", "port", "read_only", "postgres_version"], c.fetchone()))
            assert identity["role"] == "kaoyan" and identity["read_only"] == "on"
            c.execute("SELECT version_num FROM alembic_version")
            identity["revision"] = c.fetchone()[0]
            assert identity["revision"] == "f54c8a1d7e20"
            c.execute("SELECT n.nspname,c.relname,pg_get_userbyid(c.relowner),has_schema_privilege(current_user,n.oid,'USAGE'),has_table_privilege(current_user,c.oid,'SELECT'),c.relrowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relkind IN ('r','p','v','m') ORDER BY c.relname")
            tables = [dict(zip(["schema", "table", "owner", "schema_usage", "select_granted", "rls"], r)) for r in c.fetchall()]
            counts = {}
            for table in tables:
                if table["select_granted"]:
                    c.execute(sql.SQL("SELECT count(*) FROM public.{}").format(sql.Identifier(table["table"])))
                    counts[table["table"]] = c.fetchone()[0]
            c.execute("SELECT count(*),coalesce(sum(json_array_length(graduation_question_ids)),0) FROM kp_mastery_policies WHERE policy_version=3 AND graduation_set_version>0")
            pointer_sets, pointer_members = c.fetchone()
            codes = load(DATA / "cases.json")["node_keys"]
            nodes = {}
            for key, code in codes.items():
                c.execute("SELECT k.id::text,k.code,k.name,p.graduation_set_version,p.graduation_question_ids FROM knowledge_points k JOIN kp_mastery_policies p ON p.kp_id=k.id WHERE k.code=%s", (code,))
                row = c.fetchone()
                assert row is not None, code
                node = dict(zip(["id", "code", "name", "policy_set_version", "policy_question_ids"], row))
                c.execute("SELECT id::text,current_version_id::text,auto_review_event_id::text,bank_scope FROM questions WHERE id = ANY(%s::uuid[]) ORDER BY id", (node["policy_question_ids"],))
                node["current_question_pointers"] = [dict(zip(["question_id", "current_version_id", "auto_review_event_id", "bank_scope"], r)) for r in c.fetchall()]
                nodes[key] = node
            c.execute("ROLLBACK")
    return {"identity": identity, "table_permissions": tables, "counts_readable": counts,
            "missing_mapped_select": [r["table"] for r in tables if r["table"] in Base.metadata.tables and not r["select_granted"]],
            "policy_pointers_only": {"node_sets": pointer_sets, "members": pointer_members,
                "not_archive_or_qualification_validation": True}, "nodes": nodes,
            "permission_changes_executed": False, "real_api_acceptance": "PENDING_PERMISSION_AUTHORIZATION"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inspect-readonly", action="store_true")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    out = args.output_dir.resolve()
    assert out.is_relative_to((ROOT / "storage/quality-audits").resolve())
    assert not out.exists(), "Use a new output directory; preserve frozen evidence"
    report = {"prepared_at_utc": datetime.now(timezone.utc).isoformat(),
              "status": "PREPARED_AWAITING_PERMISSION_AND_BUDGET_AUTHORIZATION",
              "real_model_requests": 0, "validation": validate_cases(), "reference_checks": reference_checks()}
    if args.inspect_readonly:
        report["readonly_database"] = inspect_readonly()
    from backend.config import get_settings
    from backend.services.model_settings_service import load_local_settings
    s = load_local_settings(get_settings())
    report["model_configuration"] = {"model": s.llm_model, "base_url": s.llm_base_url,
        "key_configured": bool(s.llm_api_key and s.llm_api_key.get_secret_value()),
        "max_output_tokens": s.llm_max_output_tokens, "retry_max_output_tokens": s.llm_retry_max_output_tokens,
        "timeout_seconds": s.llm_timeout_seconds, "stream_include_usage": s.llm_stream_include_usage,
        "local_settings_error": s.local_model_settings_error, "context_screening": s.chat_context_screening}
    files = sorted(p for p in DATA.rglob("*") if p.is_file())
    code = ["backend/chat/service.py", "backend/chat/call_trace.py", "backend/services/learning_task_service.py",
            "backend/services/learning_assistant_service.py", "backend/services/learning_qa_service.py",
            "backend/services/assistant_router.py", "backend/app.py", "backend/config.py",
            "frontend/src/pages/ChatPage.vue", "frontend/src/components/LearningTaskPanel.vue"]
    files.extend(ROOT / name for name in code)
    report["frozen_file_sha256"] = {p.relative_to(ROOT).as_posix(): digest(p) for p in files}
    report["sealed_dump_sha256"] = digest(ROOT / "storage/quality-audits/phase45z-final-20261013/final-sealed.dump")
    assert report["sealed_dump_sha256"] == load(DATA / "fixtures.json")["content_source"]["sha256"]
    out.mkdir(parents=True, exist_ok=False)
    (out / "preparation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": report["status"], "case_count": 40, "reference_checks": "PASS",
                      "real_model_requests": 0, "output": str(out / "preparation.json")}, ensure_ascii=True))


if __name__ == "__main__":
    main()
