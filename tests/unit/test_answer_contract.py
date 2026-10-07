import pytest

from backend.chat.answer_contract import audit_answer_contract

BLOCKS = [{"label": "C1", "material_title": "甲"}, {"label": "C2", "material_title": "乙"}]
QUESTION = "比较共同和独有内容"


def test_common_row_requires_each_source_not_just_valid_citation():
    result = audit_answer_contract(QUESTION, "| 持久化 | 共同 | [C1] |", BLOCKS)
    assert result["issues"] == [{"code": "common_fact_missing_source", "line": 1}]
    assert not result["observable_checks_passed"]


def test_two_rows_with_one_source_each_do_not_replace_dual_source_row():
    result = audit_answer_contract(QUESTION, "| 持久化 | 共同 | [C1] |\n| 持久化 | 共同 | [C2] |", BLOCKS)
    assert len(result["issues"]) == 2


def test_dual_sources_pass_only_observable_checks_not_semantic_grading():
    result = audit_answer_contract(QUESTION, "| 持久化 | **共同** | [C1][C2] |", BLOCKS)
    assert result["observable_checks_passed"] and result["semantic_correctness_proven"] is False
    assert result["manual_review_required"] and result["output_modified"] is False


def test_duplicate_common_and_unique_exact_fact_is_reported():
    result = audit_answer_contract(QUESTION, "| 重启保留数据 | 共同 | [C1][C2] |\n| 重启保留数据 | 甲独有 | [C1] |", BLOCKS)
    assert result["issues"] == [{"code": "identical_fact_common_and_unique"}]


def test_unknown_citation_is_not_source_support():
    result = audit_answer_contract(QUESTION, "| 事实 | 共同 | [C1][C99] |", BLOCKS)
    assert {i["code"] for i in result["issues"]} == {"unknown_citation", "common_fact_missing_source"}


@pytest.mark.parametrize("answer", ["普通文字比较", "| 事实 | 归属 | 引用 |", "并不是它否定的是某成立命题。"])
def test_unrecognized_output_is_not_marked_semantic_success(answer):
    result = audit_answer_contract(QUESTION, answer, BLOCKS)
    assert result["status"] == "unobserved" and result["observable_checks_passed"] is None


def test_real_v9_negation_heading_lists_true_theorem_is_flagged():
    answer = "它否定的是这个方向：\n\n- 原命题：可导⇒连续。这个成立 [C1]。\n- 逆命题：连续⇒可导。这个不成立 [C1]。\n\n另述。"
    result = audit_answer_contract("这个反例说明什么？", answer, BLOCKS)
    assert result["issues"] == [{"code": "negation_heading_lists_true_statement"}]


def test_negation_target_separate_from_true_theorem_has_no_pattern_flag():
    answer = "它否定的是这个方向：\n\n- 连续⇒可导不成立。\n\n另外，资料的定理是可导⇒连续成立。"
    assert not audit_answer_contract("这个反例说明什么？", answer, BLOCKS)["issues"]


def test_code_example_table_does_not_count_as_asserted_comparison():
    answer = "```markdown\n| 示例 | 共同 | [C99] |\n```\n| 持久化 | 共同 | [C1][C2] |"
    result = audit_answer_contract(QUESTION, answer, BLOCKS)
    assert result["comparison_rows_checked"] == 1 and not result["issues"]
