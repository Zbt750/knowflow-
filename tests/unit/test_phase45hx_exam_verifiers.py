from types import SimpleNamespace

from backend.services.phase45hx_exam_verifiers import verify_problem


def question(stem, options, answer):
    return SimpleNamespace(question_type="single_choice", stem=stem, options=options, correct_answer=answer)


def test_sparse_matrix_compression_requires_triplet_and_orthogonal_list():
    q = question("适用于压缩存储稀疏矩阵的两种存储结构是（）。", {
        "A": "三元组表和十字链表", "B": "三元组表和邻接矩阵",
        "C": "十字链表和二叉链表", "D": "邻接矩阵和十字链表",
    }, "A")
    assert verify_problem(q)["status"] == "PASS"
    q.correct_answer = "D"
    assert verify_problem(q)["status"] == "FAIL"
    q.options["D"] = "三元组表和十字链表"
    assert verify_problem(q)["reason"] == "non_unique_correct_option"


def test_preorder_equals_inorder_requires_right_only_nonleaves():
    stem = "要使一棵非空二叉树的先序序列与中序序列相同，其所有非叶结点须满足的条件是（）。"
    options = {"A": "只有左子树", "B": "只有右子树", "C": "结点的度均为1", "D": "结点的度均为2"}
    q = question(stem, options, "B")
    assert verify_problem(q)["status"] == "PASS"
    q.correct_answer = "A"
    assert verify_problem(q)["reason"] == "derived_key_conflict"
    q.options["B"] = "右子树且允许有左子树"
    assert verify_problem(q)["status"] == "UNKNOWN"


TREE = ('二叉树结构JSON={"f":["c","g"],"c":[null,"a"],"a":["e",null],'
        '"e":[null,null],"g":["d",null],"d":[null,"b"],"b":[null,null]};'
        '后序序列=e,a,c,b,d,g,f;目标结点=a;与结点a同层的结点是（）。')


def test_postorder_tree_transcription_is_recomputed_and_depths_compared():
    options = {"A": "c", "B": "d", "C": "f", "D": "g"}
    q = question(TREE, options, "B")
    result = verify_problem(q)
    assert result["status"] == "PASS"
    assert result["proof"]["derived_postorder"] == ["e", "a", "c", "b", "d", "g", "f"]
    assert result["proof"]["target_depth_zero_based"] == 2
    q.correct_answer = "A"
    assert verify_problem(q)["reason"] == "derived_key_conflict"
    q.stem = TREE.replace("e,a,c,b,d,g,f", "e,c,a,b,d,g,f")
    assert verify_problem(q)["reason"] == "stated_postorder_conflicts_with_transcribed_tree"


def test_unaligned_double_reads_count_bus_word_spans():
    stem = "某计算机主存按字节编址，主存每次最多读写32位数据。double型变量x的主存地址为804001AH，则读取x需要的存储周期是（）。"
    options = {"A": "1", "B": "2", "C": "3", "D": "4"}
    q = question(stem, options, "C")
    result = verify_problem(q)
    assert result["status"] == "PASS"
    assert result["proof"]["address_mod_transfer_bytes"] == 2
    assert result["proof"]["derived_cycles"] == 3
    q.correct_answer = "B"
    assert verify_problem(q)["reason"] == "derived_key_conflict"
    q.stem = stem.replace("double", "float")
    assert verify_problem(q) is None
