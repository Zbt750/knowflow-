"""Bounded Phase 4.5D verifier fixtures; all data here is synthetic."""
from types import SimpleNamespace

import pytest

from backend.services.quality_verifiers import verify_problem


def question(stem, answer, *, kind="single_choice", options=None):
    return SimpleNamespace(stem=stem, correct_answer=answer, question_type=kind,
                           options=options or {})


def test_2026_doubly_linked_list_pointer_loop_is_bounded_and_checks_all_choices():
    stem = ("设有一个双向链表 L，结构为 [p2,d,p1]，头结点为 head，初始时 head=cu。"
            "现要将每个结点的 p2 指向 p1 指向结点的直接后继，应该进行的操作是（ ）。")
    options = {
        "A": "while(cu!=NULL){cu->p2=cu->p1->p1;cu=cu->p1;}",
        "B": "while(cu!=NULL&&cu->p2!=NULL){cu->p2=cu->p1->p1;cu=cu->p1;}",
        "C": "while(cu!=NULL){if(cu->p1!=NULL){cu->p2=cu->p1->p1;cu=cu->p1;}}",
        "D": "while(cu!=NULL){if(cu->p1!=NULL)cu->p2=cu->p1->p1;cu=cu->p1;}"
    }
    result = verify_problem(question(stem, "D", options=options))
    assert result["status"] == "PASS"
    assert result["adapter"] == "hs_doubly_list_two_step_pointer_v1"
    assert result["proof"]["option_forms"] == {"A": "A", "B": "B", "C": "C", "D": "D"}
    assert verify_problem(question(stem, "A", options=options))["reason"] == "non_unique_or_conflicting_pointer_loop"

    # Equivalent option ordering remains supported; the derived option label follows the code, not a fixed letter.
    swapped = {"A": options["A"], "B": options["D"], "C": options["C"], "D": options["B"]}
    assert verify_problem(question(stem, "B", options=swapped))["status"] == "PASS"

    # Two copies of the valid implementation are not a unique-answer item.
    duplicate = {**options, "A": options["D"]}
    assert verify_problem(question(stem, "D", options=duplicate))["status"] == "FAIL"

    # Unknown code and altered premises fail closed instead of inferring a result.
    unknown = {**options, "A": "while(cu){safe_but_unrecognized();}"}
    assert verify_problem(question(stem, "D", options=unknown))["status"] == "UNKNOWN"
    assert verify_problem(question(stem.replace("直接后继", "直接前驱"), "D", options=options))["status"] == "NOT_APPLICABLE"


def four(correct, values=None):
    values = values or [str(correct), str(int(correct)+1), str(int(correct)-1), str(int(correct)+2)]
    return {chr(65+i): value for i, value in enumerate(values)}


def test_determinant_is_derived_and_duplicate_correct_option_is_rejected():
    stem = "计算二阶行列式D=|ab;cd|，其中a=1，b=2，c=3，d=4。"
    q = question(stem, "A", options={"A":"-2", "B":"2", "C":"10", "D":"-10"})
    assert verify_problem(q)["status"] == "PASS"
    q.options["B"] = "-2"
    result = verify_problem(q)
    assert result["status"] == "FAIL" and result["reason"] == "non_unique_correct_option"


def test_linear_system_uses_exact_cramers_rule_and_detects_wrong_key():
    stem = "解方程组：2x+1y=7；1x+3y=11。求(x,y)。"
    opts = {"A":"(2,3)", "B":"(3,2)", "C":"(1,5)", "D":"(4,1)"}
    assert verify_problem(question(stem, "A", options=opts))["status"] == "PASS"
    assert verify_problem(question(stem, "B", options=opts))["reason"] == "derived_key_conflict"
    singular = "解方程组：1x+2y=3；2x+4y=6。求(x,y)。"
    assert verify_problem(question(singular, "A", options=opts))["reason"] == "singular_system"


def test_linear_system_numeric_x_variant_is_derived_exactly():
    stem = "解方程组：2x+3y=8；2x+4y=10。求x的值。"
    result = verify_problem(question(stem, "1", kind="fill_blank"))
    assert result["status"] == "PASS"
    assert result["proof"]["solution"] == ["1", "2"]
    assert verify_problem(question(stem, "2", kind="fill_blank"))["status"] == "FAIL"
    assert verify_problem(question(stem, "1", kind="single_choice", options={"A":"1","B":"2","C":"3","D":"4"}))["status"] == "NOT_APPLICABLE"


def test_binary_search_has_explicit_midpoint_and_closed_interval():
    stem = "在升序数组[1,3,5,7,9,11,13]中，按1起始下标执行二分查找：初始low=1、high=n，mid=floor((low+high)/2)，使用闭区间，目标值为9且保证存在；求成功前的关键字比较次数？"
    opts = {"A":"2", "B":"3", "C":"4", "D":"5"}
    result = verify_problem(question(stem, "B", options=opts))
    assert result["status"] == "PASS" and len(result["proof"]["compared"]) == 3
    unsupported = verify_problem(question(stem.replace("使用闭区间", "使用开区间"), "B", options=opts))
    assert unsupported["status"] == "NOT_APPLICABLE"


def test_binary_search_numeric_variant_uses_stated_comparison_count():
    stem = "在升序数组[1,3,5,7,9,11,13]中，按1起始下标执行二分查找：初始low=1、high=n，mid=floor((low+high)/2)，使用闭区间，目标值为9且保证存在；求成功前的关键字比较次数？"
    result = verify_problem(question(stem, "3", kind="fill_blank"))
    assert result["status"] == "PASS" and len(result["proof"]["compared"]) == 3
    assert verify_problem(question(stem, "2", kind="fill_blank"))["status"] == "FAIL"


@pytest.mark.parametrize(("algorithm", "answer"), [("FIFO", "6"), ("LRU", "5")])
def test_fifo_and_lru_are_distinct_and_exact(algorithm, answer):
    stem = f"采用{algorithm}页面置换算法，内存有3个页框且初始为空，访问序列为1,2,3,1,4,1,5，求缺页次数？"
    opts = {"A":"4", "B":"5", "C":"6", "D":"7"}
    key = {"4":"A", "5":"B", "6":"C", "7":"D"}[answer]
    assert verify_problem(question(stem, key, options=opts))["status"] == "PASS"


@pytest.mark.parametrize(("algorithm", "answer"), [("FIFO", "6"), ("LRU", "5")])
def test_page_replacement_numeric_variant_is_exact(algorithm, answer):
    stem = f"采用{algorithm}页面置换算法，内存有3个页框且初始为空，访问序列为1,2,3,1,4,1,5，求缺页次数？"
    result = verify_problem(question(stem, answer, kind="fill_blank"))
    assert result["status"] == "PASS" and result["proof"]["fault_count"] == int(answer)
    wrong = "5" if answer == "6" else "6"
    assert verify_problem(question(stem, wrong, kind="fill_blank"))["status"] == "FAIL"


def test_ipv4_conventional_usable_hosts_spells_out_exclusions():
    stem = "某IPv4子网前缀长度为/29，按排除网络地址和广播地址的普通子网规则，可分配主机地址数是多少？"
    assert verify_problem(question(stem, "B", options={"A":"4", "B":"6", "C":"8", "D":"14"}))["status"] == "PASS"
    boundary = stem.replace("/29", "/31")
    assert verify_problem(question(boundary, "A", options={"A":"0", "B":"2", "C":"1", "D":"4"}))["status"] == "NOT_APPLICABLE"


def test_ipv4_numeric_variant_and_out_of_scope_prefix():
    stem = "某IPv4子网前缀长度为/29，按排除网络地址和广播地址的普通子网规则，可分配主机地址数是多少？"
    assert verify_problem(question(stem, "6", kind="fill_blank"))["status"] == "PASS"
    assert verify_problem(question(stem, "8", kind="fill_blank"))["status"] == "FAIL"
    assert verify_problem(question(stem.replace("/29", "/31"), "0", kind="fill_blank"))["status"] == "NOT_APPLICABLE"


def test_signed_twos_complement_numeric_subtraction_wraps_exactly():
    stem = ("假设8位字长计算机中，带符号整数x、y的补码分别为"
        "`[x]补=A3H`、`[y]补=75H`，计算x-y并按8位补码解释，所得带符号整数为多少？")
    result = verify_problem(question(stem, "46", kind="fill_blank"))
    assert result["status"] == "PASS"
    assert result["proof"]["exact_difference"] == -210
    assert result["proof"]["wrapped_signed"] == 46
    assert result["proof"]["overflow"] is True
    assert verify_problem(question(stem, "-210", kind="fill_blank"))["status"] == "FAIL"
    invalid_width = stem.replace("8位字长", "4位字长")
    assert verify_problem(question(invalid_width, "46", kind="fill_blank"))["status"] == "UNKNOWN"


def test_fcfs_average_wait_is_exact_fraction_and_unknown_formats_are_withheld():
    stem = "所有进程到达时间均为0，按给定顺序采用FCFS调度，运行时间依次为3,2,4，平均等待时间是多少？"
    result = verify_problem(question(stem, "8/3", kind="fill_blank"))
    assert result["status"] == "PASS" and result["proof"]["waiting_times"] == [0,3,5]
    assert verify_problem(question(stem, "0.333", kind="fill_blank"))["status"] == "FAIL"


def test_improper_integral_parameter_requires_domain_and_solves_from_statement():
    stem = "设积分∫_1^∞a/[x(2x+a)]dx=ln(3)，且a>-2，求a。"
    result = verify_problem(question(stem, "4", kind="fill_blank"))
    assert result["status"] == "PASS" and result["proof"]["integral"] == "ln(1+a/2)"
    assert verify_problem(question(stem, "2", kind="fill_blank"))["status"] == "FAIL"
    assert verify_problem(question(stem.replace("且a>-2，", ""), "4", kind="fill_blank"))["status"] == "NOT_APPLICABLE"


def test_full_binary_tree_identity_and_unrelated_claim_not_applicable():
    stem = "非空完全二叉树所有叶在同层，且每个非叶结点有2个孩子；若叶数为k，求总结点数。"
    options = {"A":"2k-1", "B":"2k", "C":"k^2", "D":"2^k-1"}
    result = verify_problem(question(stem, "A", options=options))
    assert result["status"] == "PASS" and result["adapter"] == "full_binary_tree_edges_v1"
    assert verify_problem(question(stem.replace("每个非叶结点有2个孩子", "每个非叶结点至多有2个孩子"), "A", options=options))["status"] == "NOT_APPLICABLE"


def test_complete_tree_numeric_leaf_count_and_twos_complement_endpoints():
    tree = "一棵有9个结点的完全二叉树，其叶结点数为多少？"
    result = verify_problem(question(tree, "5", kind="fill_blank"))
    assert result["status"] == "PASS" and result["adapter"] == "complete_tree_index_v1"
    assert verify_problem(question(tree, "4", kind="fill_blank"))["status"] == "FAIL"

    low = "8位补码所能表示的最小整数是多少？"
    high = "8位补码所能表示的最大整数是多少？"
    assert verify_problem(question(low, "-128", kind="fill_blank"))["status"] == "PASS"
    assert verify_problem(question(high, "127", kind="fill_blank"))["status"] == "PASS"
    assert verify_problem(question(high, "128", kind="fill_blank"))["status"] == "FAIL"
    assert verify_problem(question("65位补码所能表示的最大整数是多少？", "0", kind="fill_blank"))["status"] == "NOT_APPLICABLE"


def test_complete_tree_sequential_storage_index_rules_are_explicit():
    parent = "在按1开始下标顺序存储、共有31个结点的完全二叉树中，结点i=19的双亲下标是多少？"
    left = "在按1开始下标顺序存储、共有31个结点的完全二叉树中，结点i=5的左孩子下标是多少？"
    right = "在按1开始下标顺序存储、共有31个结点的完全二叉树中，结点i=6的右孩子下标是多少？"
    assert verify_problem(question(parent, "9", kind="fill_blank"))["status"] == "PASS"
    assert verify_problem(question(left, "10", kind="fill_blank"))["status"] == "PASS"
    assert verify_problem(question(right, "13", kind="fill_blank"))["status"] == "PASS"
    no_child = right.replace("共有31个结点", "共有12个结点")
    assert verify_problem(question(no_child, "13", kind="fill_blank"))["status"] == "NOT_APPLICABLE"
    root_parent = parent.replace("结点i=19", "结点i=1")
    assert verify_problem(question(root_parent, "0", kind="fill_blank"))["reason"] == "root_has_no_parent"


def test_sign_magnitude_ones_complement_and_biased_decoding_use_explicit_conventions():
    rows = [
        ("按原码解释（最高位为符号位、其余位表示绝对值），字长为8位，编码10000101表示的十进制整数是多少？", "-5"),
        ("按反码解释（正数编码同原码、负数由正数码逐位取反），字长为8位，编码11111101表示的十进制整数是多少？", "-2"),
        ("按移码解释（真值=无符号编码值-2^(n-1)），字长为8位，编码10000010表示的十进制整数是多少？", "2"),
    ]
    for stem, answer in rows:
        result=verify_problem(question(stem, answer, kind="fill_blank"))
        assert result["status"] == "PASS" and result["adapter"] == "phase45d_fixed_point_decode_v1"
        assert verify_problem(question(stem, "99", kind="fill_blank"))["status"] == "FAIL"
    invalid = rows[0][0].replace("10000101", "1000101")
    assert verify_problem(question(invalid, "-5", kind="fill_blank"))["status"] == "NOT_APPLICABLE"
