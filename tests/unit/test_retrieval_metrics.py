"""检索评估的指标与数据集解析测试。

指标算错比检索不好更危险：它会让「质量是否变差」完全失去判断依据，
所以每种计分口径都要用可手算的例子钉住。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.eval.dataset import EvalCase, load_dataset
from backend.eval.metrics import CaseResult, EvalReport, format_report

DATASET = Path(__file__).resolve().parents[2] / "eval" / "dataset" / "retrieval_v1.jsonl"


def make_case(
    case_id: str,
    headings: list[tuple[str, ...]],
    expected: tuple[str, ...] = ("第一章",),
    *,
    out_of_scope: bool = False,
) -> CaseResult:
    return CaseResult(
        case_id=case_id,
        query=f"query-{case_id}",
        difficulty="literal",
        expected=expected,
        actual_headings=headings,
        out_of_scope=out_of_scope,
    )


# ---------------------------------------------------------------------------
# 数据集解析
# ---------------------------------------------------------------------------


def test_load_dataset_reads_bundled_cases() -> None:
    cases = load_dataset(DATASET)
    assert len(cases) >= 10
    assert all(case.query.strip() for case in cases)
    # id 必须唯一，指标才能对上号。
    assert len({case.case_id for case in cases}) == len(cases)
    # 必须含越界用例：否则测不出「知识库里没有答案时会不会硬凑」。
    assert any(case.is_out_of_scope for case in cases)


def test_dataset_covers_multiple_difficulties() -> None:
    cases = load_dataset(DATASET)
    difficulties = {case.difficulty for case in cases}
    assert {"literal", "semantic"} <= difficulties, "既要有字面题也要有语义题"


def test_load_dataset_rejects_duplicate_id(tmp_path: Path) -> None:
    path = tmp_path / "dup.jsonl"
    path.write_text(
        '{"id":"a","query":"q1","expected_headings":["x"]}\n'
        '{"id":"a","query":"q2","expected_headings":["y"]}\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="id 重复"):
        load_dataset(path)


def test_load_dataset_rejects_bad_json(tmp_path: Path) -> None:
    path = tmp_path / "bad.jsonl"
    path.write_text('{"id":"a", "query": }\n', encoding="utf-8")
    with pytest.raises(ValueError, match="不是合法 JSON"):
        load_dataset(path)


def test_load_dataset_rejects_empty(tmp_path: Path) -> None:
    path = tmp_path / "empty.jsonl"
    path.write_text("\n\n", encoding="utf-8")
    with pytest.raises(ValueError, match="数据集为空"):
        load_dataset(path)


def test_load_dataset_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_dataset(tmp_path / "nope.jsonl")


# ---------------------------------------------------------------------------
# 指标
# ---------------------------------------------------------------------------


def test_hit_rank_uses_first_relevant_position() -> None:
    case = make_case("c1", [("其他",), ("第一章 洛必达法则",), ("第一章 洛必达法则",)])
    assert case.hit_rank == 2


def test_hit_rank_matches_substring_of_heading_path() -> None:
    """预期主题是标题片段，只要路径里包含它就算命中。"""
    case = make_case("c1", [("高等数学", "第一章 洛必达法则", "适用条件")])
    assert case.hit_rank == 1


def test_hit_rank_none_when_nothing_relevant() -> None:
    case = make_case("c1", [("无关章节",), ("另一个章节",)])
    assert case.hit_rank is None


def test_out_of_scope_case_never_counts_as_hit() -> None:
    case = make_case("neg", [], out_of_scope=True)
    assert case.hit_rank is None
    assert case.returned_results is False


def test_out_of_scope_returned_results_is_a_fact_not_an_error() -> None:
    """检索层照相似度返回最像的块是预期行为；拒绝回答是上层的职责。"""
    case = make_case("neg", [("随便什么",)], out_of_scope=True)
    assert case.returned_results is True
    # 但越界用例永远不算命中，不能拉高 Hit 指标。
    assert case.hit_rank is None


def test_recall_counts_covered_topics() -> None:
    case = make_case(
        "c1",
        [("主题甲",), ("主题乙",)],
        expected=("主题甲", "主题乙"),
    )
    assert case.recall_at(2) == 1.0
    assert case.recall_at(1) == 0.5


def test_report_metrics_on_hand_computable_example() -> None:
    """三条用例：第 1 名命中、第 3 名命中、未命中。

    Hit@3 = 2/3；MRR@3 = (1 + 1/3 + 0) / 3 = 4/9；Recall@3 用单主题算同样的值。
    """
    report = EvalReport(k=3)
    report.results = [
        make_case("c1", [("第一章",)]),
        make_case("c2", [("无关",), ("无关",), ("第一章",)]),
        make_case("c3", [("无关",)]),
    ]

    assert report.hit_rate() == pytest.approx(2 / 3)
    assert report.mrr() == pytest.approx((1 + 1 / 3) / 3)
    assert report.recall() == pytest.approx(2 / 3)


def test_report_mrr_ignores_hits_beyond_k() -> None:
    """排在第 k 名之外的命中不计入 MRR@k，但 recall_at 同样只看前 k。"""
    report = EvalReport(k=1)
    report.results = [make_case("c1", [("无关",), ("第一章",)])]

    assert report.mrr() == 0.0
    assert report.recall() == 0.0
    assert report.hit_rate() == 1.0  # 命中率只看「有没有相关结果」，与名次无关


def test_report_strong_signal_rate_uses_score_threshold() -> None:
    """只有相似度超过阈值才算强误导信号，用来校准上层阈值。"""
    report = EvalReport(k=3)
    low = make_case("neg1", [("无关",)], out_of_scope=True)
    low.top_score = 0.4
    high = make_case("neg2", [("无关",)], out_of_scope=True)
    high.top_score = 0.9
    report.results = [low, high]

    assert report.strong_signal_rate() == pytest.approx(0.5)
    assert report.max_out_of_scope_score() == pytest.approx(0.9)


def test_report_strong_signal_rate_without_scores() -> None:
    report = EvalReport(k=3)
    report.results = [make_case("neg", [], out_of_scope=True)]
    assert report.strong_signal_rate() == 0.0
    assert report.max_out_of_scope_score() is None


def test_report_handles_empty_input() -> None:
    report = EvalReport(k=3)
    assert report.hit_rate() == 0.0
    assert report.recall() == 0.0
    assert report.mrr() == 0.0
    assert report.strong_signal_rate() == 0.0


def test_format_report_marks_hits_misses_and_false_positives() -> None:
    report = EvalReport(k=2)
    report.results = [
        make_case("c1", [("第一章",)]),
        make_case("c2", [("无关",)]),
        make_case("neg", [("不该有",)], out_of_scope=True),
    ]
    text = format_report(report)

    assert "Hit@2" in text
    assert "MRR@2" in text
    assert "越界强信号率" in text
    assert "名次 1" in text
    assert "未命中" in text
    assert "越界用例" in text


def test_eval_case_is_out_of_scope_when_no_expectation() -> None:
    assert EvalCase(case_id="a", query="q", expected_headings=()).is_out_of_scope is True
    assert EvalCase(case_id="b", query="q", expected_headings=("x",)).is_out_of_scope is False
