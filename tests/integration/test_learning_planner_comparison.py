"""离线对照复用现有选择器；不以协议模型验证真实模型优越性。"""
from scripts.compare_learning_planners import compare
from scripts.run_learning_agent_eval import isolated_factory
from tests.conftest import TEST_DATABASE_URL


def test_comparison_uses_same_fixture_and_never_writes_learning_business():
    with isolated_factory(TEST_DATABASE_URL) as factory:
        rows = compare(factory)
        assert len(rows) == 6 and all(r["both_constraint_pass"] for r in rows)
        assert all(s["rules"]["model_calls"] == 0 for r in rows for s in r["stages"])
        assert all(s["rules"]["no_business_write"] for r in rows for s in r["stages"])
        multi = next(r for r in rows if r["case"] == "multi_modify")
        assert len(multi["stages"]) == 3
        short = next(r for r in rows if r["case"] == "short_fill")["stages"][0]
        assert short["rules"]["draft"]["total_minutes"] <= 5
        assert short["rules"]["draft"]["questions"][0]["question_type"] == "fill_blank"
        insufficient = next(r for r in rows if r["case"] == "insufficient_count")["stages"][0]
        assert insufficient["agent"]["status"] == insufficient["rules"]["status"] == "needs_info"
