"""加载检索评估数据集（JSONL）。

数据集里的 `expected_headings` 是**标题片段**，只要命中结果的标题路径里
包含它就算相关。这样可以按主题粒度评估，而不是绑定到某个具体 chunk 编号 ——
后者会因为分块参数微调而整批失效。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class EvalCase:
    """一条评估用例。"""

    case_id: str
    query: str
    expected_headings: tuple[str, ...]
    difficulty: str = "literal"
    note: str = ""

    @property
    def is_out_of_scope(self) -> bool:
        """没有预期命中的用例：用来检验系统不会硬凑结果。"""
        return not self.expected_headings


def load_dataset(path: Path) -> list[EvalCase]:
    """读取 JSONL；每行一个用例，空行忽略。"""
    cases: list[EvalCase] = []
    if not path.exists():
        raise FileNotFoundError(f"评估数据集不存在：{path.name}")
    seen: set[str] = set()
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"第 {line_number} 行不是合法 JSON") from error
        case_id = str(payload["id"])
        if case_id in seen:
            # id 必须唯一，否则指标会张冠李戴。
            raise ValueError(f"用例 id 重复：{case_id}")
        seen.add(case_id)
        cases.append(
            EvalCase(
                case_id=case_id,
                query=str(payload["query"]),
                expected_headings=tuple(payload.get("expected_headings") or ()),
                difficulty=str(payload.get("difficulty") or "literal"),
                note=str(payload.get("note") or ""),
            )
        )
    if not cases:
        raise ValueError("评估数据集为空")
    return cases