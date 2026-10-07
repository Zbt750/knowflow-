from pathlib import Path
import pytest
from scripts.run_ragas_chat_eval import load_cases, validate_fixture_scope, EvalError


def test_baseline_budget_and_coverage():
    cases = load_cases(Path("eval/dataset/chat_baseline_v3.jsonl"))
    assert len(cases) == 16
    assert sum(1 + len(c.setup_questions) for c in cases) == 18
    assert {"数学条件", "数学推导", "408概念", "408机制", "408易混", "文件定位", "多轮指代", "跨文件", "资料不足", "模式隔离"} <= {c.category for c in cases}
    assert len({c.case_id for c in cases}) == 16


@pytest.mark.parametrize("polluted", [False, True])
def test_baseline_white_list_does_not_allow_other_materials(monkeypatch, polluted):
    def api_call(base, method, path):
        titles = ["合成数学条件讲义", "合成408机制讲义"] if "builtin" in path else ["合成项目阶段说明", "合成部署边界补充"]
        if polluted: titles.append("用户私人资料")
        return {"total": len(titles), "items": [{"title": title} for title in titles]}
    monkeypatch.setattr("scripts.run_ragas_chat_eval.api_call", api_call)
    if polluted:
        with pytest.raises(EvalError, match="安全停止"):
            validate_fixture_scope("http://127.0.0.1:8001/api", baseline_v3=True)
    else:
        validate_fixture_scope("http://127.0.0.1:8001/api", baseline_v3=True)
