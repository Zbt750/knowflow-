"""评测脚本的隔离、隐私与报告自检，不调用真实模型。"""
import pytest
from sqlalchemy import text
from tests.conftest import TEST_DATABASE_URL
from scripts.run_learning_agent_eval import isolated_factory, run_suite, ProtocolProvider, CheckedProvider, CASES, EXTENDED_CASES, summarize


def test_eval_refuses_non_test_database():
    with pytest.raises(ValueError, match="_test"):
        with isolated_factory("postgresql+psycopg://unused:unused@127.0.0.1/dev"):
            pass


def test_eval_privacy_guard_blocks_raw_answers():
    provider = CheckedProvider(ProtocolProvider(CASES[0]))
    with pytest.raises(ValueError, match="privacy"):
        provider.tool_turn([{"content": "SYNTHETIC_RAW_ANSWER_DO_NOT_SEND"}], [], timeout=1)


def test_p5_before_after_suite_keeps_public_data_and_source_asset_unchanged():
    import hashlib
    from scripts.run_agent_evidence_journey import run_journeys, EvidencePlanner, ASSET
    from backend.db import create_db_engine
    asset_before = hashlib.sha256(ASSET.read_bytes()).hexdigest()
    engine = create_db_engine(TEST_DATABASE_URL)
    with engine.connect() as db:
        before = db.scalar(text("SELECT count(*) FROM public.knowledge_points"))
    with isolated_factory(TEST_DATABASE_URL) as factory:
        with factory() as db: schema = db.scalar(text("SELECT current_schema()"))
        records = run_journeys(factory, lambda _: EvidencePlanner())
        assert len(records) == 4 and all(r["passed"] for r in records)
        assert sum(len(r["runs"]) for r in records) == 8
        assert records[0]["submission"]["effective_confirmation_count"] == 1
        assert records[2]["submission"]["assisted"] is True
        assert records[3]["submission"]["result"] == "unknown"
        assert all("raw_answer" not in r["submission"] for r in records)
    with engine.connect() as db:
        assert db.scalar(text("SELECT count(*) FROM public.knowledge_points")) == before
        assert db.scalar(text("SELECT count(*) FROM pg_namespace WHERE nspname=:name"), {"name": schema}) == 0
    engine.dispose()
    assert hashlib.sha256(ASSET.read_bytes()).hexdigest() == asset_before


def test_p5_failed_model_runs_are_kept_without_automatic_suite_retry():
    from scripts.run_agent_evidence_journey import run_journeys, CASES
    from backend.errors import AppError
    class BrokenProvider:
        def tool_turn(self, messages, tools, *, timeout):
            raise AppError("generation_failed", status_code=503)
    with isolated_factory(TEST_DATABASE_URL) as factory:
        records = run_journeys(factory, lambda _: BrokenProvider(), CASES[:1])
    assert len(records) == 1 and not records[0]["passed"]
    assert len(records[0]["runs"]) == 1 and records[0]["runs"][0]["status"] == "failed"
    assert "submission" not in records[0]


def test_p5_fixture_refuses_public_schema_before_any_delete():
    from backend.db import create_db_engine, create_session_factory
    from scripts.run_agent_evidence_journey import seed_slice, CASES
    engine = create_db_engine(TEST_DATABASE_URL)
    with engine.connect() as db: before = db.scalar(text("SELECT count(*) FROM public.knowledge_points"))
    with pytest.raises(ValueError, match="marked isolated"):
        seed_slice(create_session_factory(engine), CASES[0])
    with engine.connect() as db: assert db.scalar(text("SELECT count(*) FROM public.knowledge_points")) == before
    engine.dispose()


def test_p5_live_cli_without_explicit_data_approval_stops_before_evaluation():
    import subprocess
    import sys
    result = subprocess.run([sys.executable, "scripts/run_agent_evidence_journey.py", "--live"],
                            capture_output=True, text=True)
    assert result.returncode == 2 and "fresh approval" in result.stderr
    assert "Report:" not in result.stdout


def test_p5_explicit_evidence_facts_do_not_invent_self_report_or_variant():
    from scripts.run_agent_evidence_journey import seed_slice, CASES
    from backend.services.learning_task_tools import TaskTools
    from datetime import datetime, timezone
    with isolated_factory(TEST_DATABASE_URL) as factory:
        topic = seed_slice(factory, CASES[2])
        tools = TaskTools(factory, budget_minutes=5, now=datetime(2026, 1, 1, tzinfo=timezone.utc), goal=topic.name)
        nodes = tools.execute("search_knowledge", {"query": topic.name})["nodes"]
        kp = nodes[0]["kp_id"]
        state = tools.execute("get_learning_state", {"kp_ids": [kp]})["states"][0]
        assert state["basis"] == "legacy_self_reported" and not state["history_available"]
        assert state["self_report"] is None and state["self_report_available"] is False
        found = tools.execute("find_questions", {"kp_ids": [kp]})
        assert found["candidate_list_complete"] is True
        typical = next(q for q in found["questions"] if q["question_type"] == "calculation")
        assert typical["question_role"] == "typical" and not typical["is_variant"]
        assert "application_transfer" not in typical["capability_keys"] and not typical["in_today_plan"]


def test_missing_usage_is_not_reported_as_zero_cost():
    report = summarize([{"metrics": {"calls": [{"status": "error", "attempt": 1, "usage": None},
        {"status": "completed", "attempt": 2, "usage": {"total_tokens": 10}}]}, "initial_run": None}])
    assert report["observed_total_tokens"] == 10
    assert report["calls_without_total_usage"] == 1 and report["total_usage_complete"] is False
    assert report["retry_calls"] == 1 and report["failed_calls"] == 1
    assert summarize([])["observed_total_tokens"] is None


def test_explicit_node_scope_cannot_be_replaced_with_another_subject():
    from scripts.run_learning_agent_eval import seed_fixture
    from backend.services.learning_task_tools import TaskTools
    from datetime import datetime, timezone
    with isolated_factory(TEST_DATABASE_URL) as factory:
        seed_fixture(factory)
        tools = TaskTools(factory, budget_minutes=30, now=datetime.now(timezone.utc), goal="合成原卷节点没有题也不要编造")
        nodes = tools.execute("search_knowledge", {"query": "合成"})["nodes"]
        assert [n["name"] for n in nodes] == ["合成原卷节点"]
        assert tools.execute("search_knowledge", {"query": "合成程序"})["nodes"] == []
        changed = TaskTools(factory, budget_minutes=30, now=datetime.now(timezone.utc), goal="合成原卷节点\n改为合成程序节点")
        assert [n["name"] for n in changed.execute("search_knowledge", {"query": "合成"})["nodes"]] == ["合成程序节点"]
        exact = TaskTools(factory, budget_minutes=30, now=datetime.now(timezone.utc), goal="合成评测范围里的 eval.reference")
        assert [n["name"] for n in exact.execute("search_knowledge", {"query": "合成"})["nodes"]] == ["合成原卷节点"]


def test_protocol_suite_is_isolated_and_cleans_its_schema():
    from backend.db import create_db_engine
    engine = create_db_engine(TEST_DATABASE_URL)
    with engine.connect() as db:
        before = db.scalar(text("SELECT count(*) FROM public.knowledge_points"))
    with isolated_factory(TEST_DATABASE_URL) as factory:
        with factory() as db:
            schema = db.scalar(text("SELECT current_schema()"))
            assert schema.startswith("agent_eval_") and schema != "public"
        records = run_suite(factory, ProtocolProvider)
        assert len(records) == 8 and all(r["passed"] for r in records)
        assert records[-1]["initial_run"]["status"] == "ready"
    with engine.connect() as db:
        assert db.scalar(text("SELECT count(*) FROM public.knowledge_points")) == before
        assert db.scalar(text("SELECT count(*) FROM pg_namespace WHERE nspname=:schema"), {"schema": schema}) == 0
    engine.dispose()


@pytest.mark.parametrize("case_id, expected", [("reference_only", "只有原卷引用"), ("existing_today", "已在今日学习")])
def test_unvalidated_model_claim_is_replaced_with_specific_tool_evidence(case_id, expected):
    class FalseSuccessProvider(ProtocolProvider):
        def final(self, clarify):
            import json
            return {"message": {"content": json.dumps({"message": "已加入全部题目", "needs_clarification": False})}}
    case = next(c for c in CASES if c["id"] == case_id)
    with isolated_factory(TEST_DATABASE_URL) as factory:
        record = run_suite(factory, FalseSuccessProvider, [case])[0]
        assert record["status"] == "needs_info" and expected in record["message"]
        assert "已加入全部" not in record["message"]


def test_extended_suite_preserves_each_modification_and_six_run_budget():
    with isolated_factory(TEST_DATABASE_URL) as factory:
        records = run_suite(factory, ProtocolProvider, EXTENDED_CASES)
        assert len(records) == 4 and all(r["passed"] for r in records)
        multi = records[0]
        assert len(multi["stages"]) == 3 and len(multi["prior_runs"]) == 1
        assert multi["stages"][1]["draft"]["questions"][0]["question_type"] == "fill_blank"
        assert multi["stages"][2]["draft"]["questions"][0]["question_type"] == "single_choice"
        assert summarize(records)["task_runs"] == 6


def test_service_rejects_short_draft_when_exact_question_count_required():
    # 程序可校验一道题的草案，不代表满足用户三道题的要求。
    case = next(c for c in EXTENDED_CASES if c["id"] == "insufficient_count")
    class TooFewProvider(ProtocolProvider):
        def __init__(self, _):
            super().__init__({**case, "required_count": 1})
    with isolated_factory(TEST_DATABASE_URL) as factory:
        record = run_suite(factory, TooFewProvider, [case])[0]
        assert record["status"] == "needs_info" and record["passed"] is True
        assert any("question_count_constraint" in t["result"].get("errors", []) for t in record["trace"])
        assert "同一张卷不能重复" in record["message"]


def test_parent_search_exposes_children_and_excluded_branch_is_not_observable():
    from scripts.run_learning_agent_eval import seed_fixture
    from backend.services.learning_task_tools import TaskTools
    from datetime import datetime, timezone
    with isolated_factory(TEST_DATABASE_URL) as factory:
        seed_fixture(factory)
        tools = TaskTools(factory, budget_minutes=30, now=datetime.now(timezone.utc), goal=EXTENDED_CASES[2]["goal"])
        response = tools.execute("search_knowledge", {"query": "合成评测范围"})
        nodes = response["nodes"]
        assert response["excluded_nodes"] == [{"name": "合成程序节点", "code": "eval.program"}]
        assert {n["code"] for n in nodes} == {"eval.root", "math.calculus.limit.lhopital", "eval.reference"}
        assert tools.execute("search_knowledge", {"query": "合成程序"})["nodes"] == []
        math = next(n for n in nodes if n["code"] == "math.calculus.limit.lhopital")
        assert tools.execute("find_questions", {"kp_ids": [math["kp_id"]]})["questions"]


def test_excluded_scope_summary_uses_verified_facts_not_model_nonexistence_claim():
    case = next(c for c in EXTENDED_CASES if c["id"] == "excluded_scope")
    class FalseExplanationProvider(ProtocolProvider):
        def final(self, clarify):
            import json
            return {"message": {"content": json.dumps({"message": "程序节点不存在，没有题。", "needs_clarification": False})}}
    with isolated_factory(TEST_DATABASE_URL) as factory:
        record = run_suite(factory, FalseExplanationProvider, [case])[0]
        assert record["passed"]
        assert "排除不代表节点不存在" in record["message"]
        assert "程序节点不存在" not in record["message"]
        assert "未据排除条件推断" in record["draft"]["rationale"]
