"""Local AI-assisted derivation worksheet, NEVER human approval or DB import.

Bounded checks test the stated/transcribed mathematical assumptions, not the
authenticity, completeness, permission or mapping of an original exam paper.
"""
import argparse
import ast
from functools import lru_cache
import hashlib
import json
import math
import re
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.services.golden_learning_slice import digest
from scripts.prepare_real_slice_review import identity


@lru_cache(None)
def shapes(n):
    if n == 0:
        return (None,)
    return tuple((left, right) for k in range(n)
                 for left in shapes(k) for right in shapes(n - 1 - k))


def label_preorder(shape, labels):
    it = iter(labels)
    def visit(s):
        if s is None:
            return None
        value = next(it)
        return (value, visit(s[0]), visit(s[1]))
    tree = visit(shape)
    if next(it, None) is not None:
        raise ValueError("Too many labels")
    return tree


def traversal(tree, order):
    if tree is None:
        return ()
    v, left, right = tree
    a, b = traversal(left, order), traversal(right, order)
    if order == "pre":
        return (v,) + a + b
    if order == "in":
        return a + (v,) + b
    if order == "post":
        return a + b + (v,)
    raise ValueError("Unknown traversal")


def orphan_indices(values):
    return [i for i, value in enumerate(values) if i > 0 and value != -1
            and values[(i - 1) // 2] == -1]


def parse_option_array(text):
    # C-style R[] = {...} and JSON-style [...] both occur in source text.
    # Only signed decimal integer lists are permitted; never evaluate code.
    body = r"\s*-?\d+(?:\s*,\s*-?\d+)*\s*"
    match = re.search(r"(?:\[" + body + r"\]|\{" + body + r"\})", text)
    return ast.literal_eval("[" + match.group()[1:-1] + "]") if match else None


def propose_count_choices(text):
    """Draft only: extract four explicit one-line count options, never approve."""
    found = re.findall(r"^([ABCD])\.\s*([0-9]+)\s*$", text, re.MULTILINE)
    if len(found) != 4 or {label for label, _ in found} != set("ABCD"):
        return None
    return {"proposed_question_type": "single_choice", "proposed_options": dict(found),
        "status": "UNVERIFIED", "can_import": False,
        "boundary": "Only explicit count options extracted; original stem punctuation/conditions/source remain unverified."}


def simpson(f, a, b, n=4096):
    if n <= 0 or n % 2:
        raise ValueError("Positive even panel count required")
    h = (b - a) / n
    return h / 3 * (f(a) + f(b) + sum(
        (4 if k % 2 else 2) * f(a + k * h) for k in range(1, n)))


def run_probes():
    """Finite enumeration/numerical sanity checks; no universal proof claim."""
    rows = {}
    def add(key, passed, detail):
        rows[key] = {"passed": bool(passed), "detail": detail,
                     "certifies_source_or_human_review": False}
    count = sum(i * 2 > 768 for i in range(1, 769))
    add("complete_tree_768", count == 384, {"leaf_count": count})
    trees = [label_preorder(s, (1, 2, 3, 4)) for s in shapes(4)]
    matching = [t for t in trees if traversal(t, "post") == (4, 3, 2, 1)]
    inorders = sorted(set(traversal(t, "in") for t in matching))
    add("chain_traversals", len(matching) == 8 and (3, 2, 4, 1) not in inorders
        and all(x in inorders for x in [(1, 2, 3, 4), (2, 3, 4, 1), (4, 3, 2, 1)]),
        {"possible_inorders": inorders, "shape_count": len(matching)})
    matching = [label_preorder(s, "aebdc") for s in shapes(5)]
    matching = [t for t in matching if traversal(t, "post") == tuple("bcdea")]
    children = sorted(set(int(t[1] is not None) + int(t[2] is not None) for t in matching))
    add("root_single_child", children == [1], {"matching_shapes": len(matching), "root_child_counts": children})
    checked, violations = 0, 0
    for n in range(1, 8):
        for s in shapes(n):
            t = label_preorder(s, range(n))
            if traversal(t, "pre") == traversal(t, "in"):
                checked += 1
                stack = [t]
                while stack:
                    v, left, right = stack.pop()
                    violations += int(left is not None)
                    if right is not None:
                        stack.append(right)
    add("equal_pre_in", checked == 7 and violations == 0,
        {"max_nodes": 7, "unique_labels": True, "matching_shapes": checked, "violations": violations})
    # For every two-child node, its immediate inorder neighbors are the
    # rightmost/leftmost nodes of the left/right subtrees respectively.
    checked, violations = 0, 0
    for s in shapes(7):
        t = label_preorder(s, range(7))
        inorder = traversal(t, "in")
        nodes, stack = {}, [t]
        while stack:
            node = stack.pop()
            nodes[node[0]] = node
            stack.extend(child for child in node[1:] if child is not None)
        for v, left, right in nodes.values():
            if left is not None and right is not None:
                checked += 1
                i = inorder.index(v)
                violations += int(nodes[inorder[i - 1]][2] is not None)
                violations += int(nodes[inorder[i + 1]][1] is not None)
    add("inorder_neighbors", checked > 0 and violations == 0,
        {"nodes_per_tree": 7, "checked_two_child_nodes": checked, "violations": violations})
    # Synthetic arrays, not copyrighted source options committed to Git.
    arrays = [[1, 2, 3, -1, -1, 4], [1, 2, 3, 4, 5, -1, -1],
              [1, 2, 3, -1, -1, -1, 4], [1, 2, 3, -1, 4, 5, -1, -1, 6, 7]]
    orphans = [orphan_indices(a) for a in arrays]
    add("sequential_orphan", orphans == [[], [], [], [8]], {"zero_based_orphans_by_option": orphans})
    extents = []
    for s in shapes(10):
        stack, height, largest = [(s, 0, 1)], 0, 0
        while stack:
            node, index, depth = stack.pop()
            if node is None:
                continue
            height, largest = max(height, depth), max(largest, index)
            stack.extend([(node[0], index * 2 + 1, depth + 1), (node[1], index * 2 + 2, depth + 1)])
        if height == 5:
            extents.append(largest + 1)
    add("height5_storage", min(extents) == 16 and max(extents) == 31,
        {"nodes": 10, "height": 5, "min_units": min(extents), "worst_case_units": max(extents),
         "interpretation": "reserve for ANY shape, not minimize over shapes"})
    numerical = simpson(lambda x: 1 / ((x + 1) * (x * x - 2 * x + 2)), 0, 1)
    expected = (3 * math.log(2) + math.pi) / 10
    add("rational_integral", abs(numerical - expected) < 1e-10,
        {"numerical": numerical, "proposed_answer": expected, "absolute_error": abs(numerical - expected)})
    # Substitution u=1/x converts the improper integral to a smooth [0,1] integral.
    numerical = simpson(lambda u: 3 / (2 + 6 * u), 0, 1)
    add("improper_parameter6", abs(numerical - math.log(2)) < 1e-10,
        {"parameter": 6, "numerical": numerical, "target": math.log(2),
         "uniqueness_argument": "integrand strictly decreases in a on a > -2"})
    numerical = simpson(lambda u: 2 / (2 + 2 * u), 0, 1)
    add("improper_parameter2", abs(numerical - math.log(2)) < 1e-10,
        {"parameter": 2, "numerical": numerical, "target": math.log(2),
         "boundary": "Only the parameter-a numerator transcription; not source certification"})
    t = math.log(2)
    volume = math.pi * simpson(lambda x: x * math.exp(-2 * x), t, 2 * t)
    expected = math.pi * (4 * t + 3) / 64
    add("rotation_volume", abs(volume - expected) < 1e-10,
        {"maximizer_t": t, "numerical_volume": volume, "proposed_max_volume": expected,
         "derivative_sign": "sign(4-exp(2t)) for t>0"})
    work = simpson(lambda x: x / (1 + x * x) ** 1.5, 0, 1)
    add("gravity_work", abs(work - (1 - 1 / math.sqrt(2))) < 1e-10,
        {"work_divided_by_G": work, "proposed": 1 - 1 / math.sqrt(2)})
    sums = [sum((k / n) * math.log(k / n) for k in range(1, n)) / n for n in (1000, 10000)]
    add("riemann_limit", abs(sums[-1] + .25) < abs(sums[0] + .25) and abs(sums[-1] + .25) < 1e-7,
        {"sample_sizes": [1000, 10000], "sample_values": sums, "proposed_limit": -.25})
    return rows


# Original derivations, not copied third-party explanations. These are drafts.
DRAFTS = {
    "408-2011-q004": ("binary_tree", "C", "完全二叉树按1起始编号，i>floor(n/2)才是叶结点；768-floor(768/2)=384。", "complete_tree_768", "single_choice", "核对原卷数字、选项与完全二叉树条件。"),
    "408-2011-q005": ("binary_tree", "C", "前序与后序逆序迫使每个非叶结点只有一个孩子。枚举三条边的左右方向，C不在8种中序序列中。", "chain_traversals", "single_choice", "核对四个序列；结点标识必须互异。"),
    "408-2012-q003": ("binary_tree", "A", "前序第二个结点e为首个孩子；后序倒数第二个也是e，表明全部其余结点位于e子树内。根只有一个孩子，但不能确定左右。", "root_single_child", "single_choice", "核对遍历序列与互异结点条件。"),
    "408-2017-q004": ("binary_tree", "B", "互异标识下，前序根在首位，中序根也在首位说明左子树为空；对子树递归，所有非叶结点只存在右孩子。", "equal_pre_in", "single_choice", "互异结点是推论的必要前提；不能外推至全部标识相同的情况。"),
    "408-2018-q004": ("binary_tree", "A", "每个非叶结点度数为2，由边数n-1=2n2得叶数n0=n2+1，总数2k-1。叶结点同层不是这个等式的必要条件。", None, "single_choice", "纯文本把2k-1与2^k-1混淆；须保留并核对HTML上标/原卷，不能直接导入。"),
    "408-2020-q003": ("binary_tree", "A", "高度5的任意形状用顺序存储，最坏可到第31个单元；特定形状可只需16个。题意是保证任意形状，不是最小化某一种形状。", "height5_storage", "single_choice", "原卷任意与至少的量词需人工确认；不同量词对应不同答案。"),
    "408-2024-q003": ("binary_tree", "A", "v有两个孩子，直接前驱p是左子树最右结点，不能有右孩子；直接后继q是右子树最左结点，不能有左孩子。", "inorder_neighbors", "single_choice", "必须是紧邻的中序前驱/后继，不是任意排在前后的位置。"),
    "408-2025-q003": ("binary_tree", "D", "0起始下标i的父结点为floor((i-1)/2)。D的下标8为19，父下标3为空，形成孤儿，其他数组无此问题。", "sequential_orphan", "single_choice", "核对全部数组及-1语义；不得覆盖已有不同文字版本的题。"),
    "math2-2024-q007": ("integral", "B", "三项仅第二项成立（极限存在按有限实数理解）。第一项反例f=1/(1+x)；第三项用尾部1/(x log^2 x)的连续非负延拓作反例，积分收敛却不满足任何p>1的多项式衰减。第二项由有限极限和p级数比较成立。", None, "single_choice", "核对原卷不等式、连续非负条件及极限存在的约定；无独立标准答案。"),
    "math2-2024-q019": ("integral", "π(4ln2+3)/64，t=ln2", "V(t)=π∫[t,2t] x exp(-2x)dx；V'=πt exp(-4t)(4-exp(2t))，先正后负，在ln2唯一取最大。", "rotation_volume", None, "这是最大体积及参数的草稿；现有grader适用性未证明，不能作为机器确认。"),
}

ONLINE_INTEGRAL_DRAFTS = {
    "math2-2026-q011": ("0<p<2", "零端等价x^(1-p)，无穷端等价(π/2)x^(-p-1)，同时要求p<2且p>0，端点发散。", None, None),
    "math2-2025-q006": ("B；W=G(1-1/√2)", "沿x位移克服引力的水平分量为Gx/(1+x²)^(3/2)，积分0到1。", "gravity_work", "single_choice"),
    "math2-2025-q013": ("-1/4", "将和式写为(1/n)Σ(k/n)ln(k/n)，t ln t在0处连续延拓；极限为积分0到1，等于-1/4。", "riemann_limit", "numeric_final"),
    "math2-2025-q017": ("(3ln2+π)/10", "部分分式分解为1/[5(x+1)]-(x-3)/[5(x²-2x+2)]；分别积分对数和反正切。", "rational_integral", None),
    "math2-2025-q011": ("6", "可收敛域a>-2。a≠0时积分为(3/a)ln(1+a/2)，a=0时为3/2；关于a严格递减，a=6为唯一解。", "improper_parameter6", "numeric_final"),
}


def build_online_integral_review(rows):
    result, seen = [], set()
    for record in rows:
        source = (record.get("grading_config") or {}).get("provenance", {}).get("source", {})
        key = f"math2-{source.get('year')}-q{source.get('question_number', 0):03d}"
        if key not in ONLINE_INTEGRAL_DRAFTS:
            continue
        if key in seen:
            raise ValueError("Duplicate online source identity")
        seen.add(key)
        answer, note, probe, method = ONLINE_INTEGRAL_DRAFTS[key]
        if key == "math2-2025-q011":
            # Identity alone cannot distinguish the known incorrect transcription
            # from its correction. Unknown content must not inherit either draft.
            stem = record.get("stem")
            if stem == "设 $\\int_1^{+\\infty}\\frac{a}{x(2x+a)}\\,dx=\\ln2$，则 $a=$____。":
                answer, note, probe = ("2", "收敛域a>-2，积分为ln(1+a/2)；等于ln2得a=2。a=0积分为0；a≤-2存在极点。", "improper_parameter2")
            elif stem != "设 $\\int_1^{+\\infty}\\frac{3}{x(2x+a)}dx=\\ln2$，则 $a=$____。":
                answer, note, probe, method = (None, "题干与已对照的两种转录都不匹配，须重新检查，不能按题号复用答案。", None, None)
        result.append({"candidate_id": key, "record_sha256": digest(record), "record": record,
            "ai_proposed_answer": answer, "ai_derivation": note, "probe_id": probe,
            "potential_grading_method_after_review": method, "status": "UNVERIFIED",
            "can_import": False, "can_enable_grading": False,
            "human_review_confirmed": False,
            "boundaries": ["Compare full original stem/options before accepting derived answer.",
                           "No equivalence, reviewer or VERIFIED status inferred from prior AI source notes.",
                           "Final-answer evidence does not certify calculation steps."]})
        if key == "math2-2025-q011":
            result[-1]["boundaries"].append("Prior numerator-3 transcription conflicts with source page; identity is not content verification.")
    return {"questions": result, "missing_expected_identities": sorted(set(ONLINE_INTEGRAL_DRAFTS) - seen),
            "database_written": False, "release_ready": False}


def read_online_integral():
    from sqlalchemy import select, text
    from backend.config import get_settings
    from backend.db import create_db_engine, create_session_factory
    from backend.models.learning import KnowledgePoint, Question
    from scripts.audit_real_learning_slices import SLICE_SCOPES
    scope = SLICE_SCOPES["integral"]
    engine = create_db_engine(str(get_settings().active_database_url))
    try:
        with create_session_factory(engine)() as db:
            if engine.dialect.name == "postgresql":
                db.execute(text("SET TRANSACTION READ ONLY"))
            rows = db.execute(select(Question, KnowledgePoint).join(KnowledgePoint, Question.kp_id == KnowledgePoint.id)
                .where(KnowledgePoint.code.in_([scope["primary"], *scope["related"]]), Question.is_active.is_(True))).all()
            return build_online_integral_review([{"id": str(q.id), "kp_code": kp.code,
                "question_type": q.question_type,
                "stem": q.stem, "options": q.options, "correct_answer": q.correct_answer,
                "explanation": q.explanation, "grading_config": q.grading_config} for q, kp in rows])
    finally:
        engine.dispose()


def build_worksheet(batch):
    if batch.get("version") != "structured-real-slice-intake-v1":
        raise ValueError("Unsupported intake version")
    indexed = {}
    for q in batch["questions"]:
        key = identity(q)
        if key in indexed:
            raise ValueError("Duplicate candidate identity")
        indexed[key] = q
    missing = sorted(set(DRAFTS) - set(indexed))
    if missing:
        raise ValueError(f"Missing required candidates: {missing}")
    probes = run_probes()
    rows = []
    for key, (scope, answer, explanation, probe, method, boundary) in DRAFTS.items():
        q = indexed[key]
        printed = q.get("printed_reference_answer")
        rows.append({"candidate_id": key, "candidate_sha256": digest(q), "candidate": q,
            "slice": scope, "proposed_answer": answer, "ai_derivation": explanation,
            "probe_id": probe, "printed_answer_matches_proposal": (printed == answer if printed else None),
            "potential_grading_method_after_review": method, "remaining_boundary": boundary,
            "review_status": "UNVERIFIED", "reviewer_kind": "AI_ASSISTED_DRAFT",
            "human_review_confirmed": False, "can_import": False,
            "original_issues": list(q["issues"]),
            "unresolved_gates": ["original_source_comparison", "rights_basis", "six_exact_hash_human_reviews"]})
        if key == "math2-2024-q007":
            rows[-1]["structural_proposal"] = propose_count_choices(q.get("raw_text", ""))
        if key == "408-2025-q003":
            parsed = {}
            for option in q.get("options", []):
                values = parse_option_array(option.get("text", ""))
                if values is not None:
                    parsed[option["label"]] = orphan_indices(values)
            bad = sorted(label for label, indices in parsed.items() if indices)
            rows[-1]["actual_option_check"] = {"parsed_labels": sorted(parsed), "orphan_indices": parsed,
                "matches_proposal": set(parsed) == {"A", "B", "C", "D"} and bad == ["D"],
                "source_authenticity_certified": False}
    return {"version": "real-slice-derivation-worksheet-v1", "batch_sha256": digest(batch),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "database_written": False, "human_review_confirmed": False, "release_ready": False,
        "questions": rows, "probes": probes,
        "not_selected": [{"candidate_id": key, "candidate_sha256": digest(q),
            "reason": "not in bounded text-only foundations/traversal + integral selection; preserve for separate scope/source/diagram review",
            "original_issues": q["issues"]} for key, q in indexed.items() if key not in DRAFTS],
        "limits": ["Checks assume stated transcription; cannot certify original paper or permission.",
                   "Finite enumeration and numerical checks are not universal symbolic graders.",
                   "Existing online questions and learning evidence remain unchanged."]}


def markdown(result):
    lines = ["# 两个真实学习切片：AI 辅助核验工作单", "",
        "所有条目仍为 UNVERIFIED。程序检查不证明原卷、授权、真人审核或判题适用性。",
        "私人题干仅保存在本地工作单；本工作单不能直接导入数据库。", "",
        f"候选批次 SHA256：{result['batch_sha256']}", "", "## 离线检查", ""]
    for key, probe in result["probes"].items():
        lines.append(f"- {key}: {'PASS' if probe['passed'] else 'FAIL'} — {json.dumps(probe['detail'], ensure_ascii=False)}")
    rows = [(q, q["candidate"], "raw_text", "proposed_answer") for q in result["questions"]]
    rows += [(q, q["record"], "stem", "ai_proposed_answer")
             for q in result.get("online_integral_review", {}).get("questions", [])]
    for row, original, stem_field, answer_field in rows:
        lines.extend(["", f"## {row['candidate_id']}（待核验）", "",
            f"原始记录 SHA256：{row.get('candidate_sha256', row.get('record_sha256'))}", "",
            "### 当前转录题干", "", original.get(stem_field, "缺失"), ""])
        if original.get("options"):
            lines.extend(["当前转录选项：", "", "```json", json.dumps(original["options"], ensure_ascii=False, indent=2), "```", ""])
        lines.extend(["### AI 独立推导草稿", "", str(row[answer_field]), "", row["ai_derivation"], "",
            f"关联检查：{row['probe_id'] or '无程序检查，仅推导草稿'}", "",
            f"核验后潜在判题方式：{row['potential_grading_method_after_review'] or '现有方式未证明适用'}", ""])
        if row.get("remaining_boundary"):
            lines.extend(["核验边界：" + row["remaining_boundary"], ""])
        if row.get("actual_option_check"):
            lines.extend(["当前选项解析检查：" + json.dumps(row["actual_option_check"], ensure_ascii=False), ""])
        if row.get("structural_proposal"):
            lines.extend(["结构补全建议（未应用、待核验）：", "", "```json",
                json.dumps(row["structural_proposal"], ensure_ascii=False, indent=2), "```", ""])
        lines.extend(["仍待处理：" + "; ".join(row.get("original_issues", row.get("boundaries", []))), "",
            "真人核验记录：未填写。来源与许可、题干、答案、解析、映射、判题配置需分别核验。"])
    lines.extend(["", "## 未纳入本次有界选择的候选", ""])
    lines += [f"- {q['candidate_id']}：{q['reason']}" for q in result["not_selected"]]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("batch", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--include-online-integral", action="store_true", help="Read-only snapshot of existing integral questions")
    args = parser.parse_args()
    output = args.output.resolve()
    if not any(output.is_relative_to(ROOT / folder) for folder in ("storage/question-intake", "eval/reports")):
        parser.error("Private source content must stay in ignored intake/reports")
    if output.exists() or output.with_suffix(".md").exists():
        parser.error("Refuse to overwrite prior worksheet")
    if args.batch.stat().st_size > 12 * 1024 * 1024:
        parser.error("Bounded input exceeded")
    result = build_worksheet(json.loads(args.batch.read_text(encoding="utf-8")))
    if args.include_online_integral:
        result["online_integral_review"] = read_online_integral()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    output.with_suffix(".md").write_text(markdown(result), encoding="utf-8")
    passed = sum(p["passed"] for p in result["probes"].values())
    print(f"UNVERIFIED worksheet: {len(result['questions'])} candidates, {passed}/{len(result['probes'])} probes passed; DB untouched")
    return 0 if passed == len(result["probes"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
