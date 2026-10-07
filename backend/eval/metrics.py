"""检索指标：纯函数，不依赖数据库或模型，因此可以单独测试。

指标口径：
- `hit@k`：前 k 条里是否至少命中一个相关主题；
- `recall@k`：前 k 条覆盖了该用例多少个相关主题（多主题用例才有意义）；
- `mrr`：第一个相关结果名次的倒数，衡量「排得够不够前」；
- 越界用例（知识库里根本没答案）单独统计**强信号率**，并记录最高相似度分数。

越界用例的口径必须说清楚：检索层只按相似度排序，对「库里没有的问题」
返回最像的几块是**预期行为**，不是错误；必须拒绝回答的是问答层。
所以这里度量的是「上层需要把阈值设多严」，而不是「检索层犯了多少错」。
"""

from __future__ import annotations

from dataclasses import dataclass, field

# 越界用例的相似度阈值：超过它说明检索层给出了强误导信号，上层判断要更谨慎。
OUT_OF_SCOPE_SCORE_THRESHOLD = 0.7


@dataclass
class CaseResult:
    """一条用例的评估结果。"""

    case_id: str
    query: str
    difficulty: str
    expected: tuple[str, ...]
    # 实际返回结果对应的主题标签（按名次排列）。
    actual_headings: list[tuple[str, ...]]
    out_of_scope: bool = False
    # 越界用例的最高相似度分数（余弦，越大越相似）；用于校准上层的阈值。
    top_score: float | None = None

    @property
    def hit_rank(self) -> int | None:
        """第一个相关结果的名次（从 1 开始）；没有命中返回 None。"""
        if self.out_of_scope:
            return None
        for position, headings in enumerate(self.actual_headings, start=1):
            if _matches(headings, self.expected):
                return position
        return None

    @property
    def returned_results(self) -> bool:
        """是否返回了结果。这是事实记录，不代表越界用例「出错了」。"""
        return bool(self.actual_headings)

    def recall_at(self, k: int) -> float:
        if self.out_of_scope or not self.expected:
            return 0.0
        covered = 0
        for want in self.expected:
            for headings in self.actual_headings[:k]:
                if _contains(headings, want):
                    covered += 1
                    break
        return covered / len(self.expected)


@dataclass
class EvalReport:
    """总体报告。"""

    k: int
    results: list[CaseResult] = field(default_factory=list)
    out_of_scope_score_threshold: float = OUT_OF_SCOPE_SCORE_THRESHOLD

    @property
    def scored(self) -> list[CaseResult]:
        return [item for item in self.results if not item.out_of_scope]

    @property
    def out_of_scope(self) -> list[CaseResult]:
        return [item for item in self.results if item.out_of_scope]

    def hit_rate(self) -> float:
        scored = self.scored
        if not scored:
            return 0.0
        return sum(1 for item in scored if item.hit_rank is not None) / len(scored)

    def recall(self) -> float:
        scored = self.scored
        if not scored:
            return 0.0
        return sum(item.recall_at(self.k) for item in scored) / len(scored)

    def mrr(self) -> float:
        scored = self.scored
        if not scored:
            return 0.0
        total = 0.0
        for item in scored:
            rank = item.hit_rank
            if rank is not None and rank <= self.k:
                total += 1.0 / rank
        return total / len(scored)

    def strong_signal_rate(self) -> float:
        """越界用例中「相似度高于阈值」的比例（阈值校准用，不是错误率）。"""
        cases = self.out_of_scope
        if not cases:
            return 0.0
        strong = sum(
            1
            for item in cases
            if item.top_score is not None and item.top_score >= self.out_of_scope_score_threshold
        )
        return strong / len(cases)

    def max_out_of_scope_score(self) -> float | None:
        """越界用例里最高的相似度分数；问答层阈值必须高于它才不会乱答。"""
        scores = [item.top_score for item in self.out_of_scope if item.top_score is not None]
        return max(scores) if scores else None


def _contains(headings: tuple[str, ...], want: str) -> bool:
    """标题路径里是否包含某个标题片段。"""
    return any(want in heading for heading in headings)


def _matches(headings: tuple[str, ...], expected: tuple[str, ...]) -> bool:
    """标题路径是否命中任意一个预期主题。"""
    return any(_contains(headings, want) for want in expected)


def format_report(report: EvalReport) -> str:
    """生成人类可读的报告文本。"""
    lines: list[str] = []
    lines.append(f"评估用例：{len(report.results)} 条（其中越界用例 {len(report.out_of_scope)} 条）")
    lines.append(f"Hit@{report.k}：{report.hit_rate():.3f}")
    lines.append(f"Recall@{report.k}：{report.recall():.3f}")
    lines.append(f"MRR@{report.k}：{report.mrr():.3f}")
    if report.out_of_scope:
        max_score = report.max_out_of_scope_score()
        lines.append(
            f"越界用例最高相似度：{max_score:.3f}"
            if max_score is not None
            else "越界用例最高相似度：无数据"
        )
        lines.append(
            f"越界强信号率（相似度 >= {report.out_of_scope_score_threshold}）："
            f"{report.strong_signal_rate():.3f}"
            "  ← 这是上层阈值校准依据，不是错误率"
        )
    lines.append("")
    lines.append("逐条结果：")
    for item in report.results:
        if item.out_of_scope:
            score = f"{item.top_score:.3f}" if item.top_score is not None else "—"
            lines.append(
                f"  [{item.case_id}] 越界用例  返回 {len(item.actual_headings)} 条"
                f"（最高相似度 {score}）  {item.query}"
            )
            continue
        rank = item.hit_rank
        if rank is None:
            lines.append(
                f"  [{item.case_id}] 未命中  {item.query}  期望：{'、'.join(item.expected)}"
            )
            continue
        lines.append(
            f"  [{item.case_id}] 名次 {rank}  {item.query}  "
            f"命中：{' / '.join(item.actual_headings[rank - 1])}"
        )
    return "\n".join(lines)
