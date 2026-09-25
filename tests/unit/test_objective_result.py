"""客观判分的纯函数测试。

产品规则：`objective_result` 只是复盘参考，绝不覆盖或代替 `self_grade`。
因此这里只验证「什么时候能判、判成什么」，并锁住「不能判时必须保持 unknown」。
"""

from __future__ import annotations

import pytest

from backend.services.attempt_service import objective_result_for


@pytest.mark.parametrize(
    ("selected", "correct", "expected"),
    [
        ("C", "C", "right"),
        # 选项大小写与空格不该影响判定。
        ("c", "C", "right"),
        (" B ", "B", "right"),
        ("C", "B", "wrong"),
        # 未作答：无法判定。
        (None, "C", "unknown"),
        # 题目没有标准答案（填空、纸笔、主观题）：明确保存 unknown。
        ("C", None, "unknown"),
        ("", "C", "unknown"),
        ("C", "", "unknown"),
        ("   ", "C", "unknown"),
    ],
)
def test_objective_result_only_judges_when_both_sides_exist(
    selected: str | None, correct: str | None, expected: str
) -> None:
    assert objective_result_for(selected_option=selected, correct_answer=correct) == expected