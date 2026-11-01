"""Bounded independent verifiers for recoverable 2017 408 exam question families.

These adapters operate on the stated problem data and reject unrecognized forms.
They do not identify questions by source ID and do not certify source authenticity.
"""
from __future__ import annotations

import json
import re
from collections import Counter


SOLVERS = frozenset({
    "hx_sparse_matrix_compression_v1",
    "hx_preorder_equals_inorder_v1",
    "hx_binary_tree_postorder_depth_v1",
    "hx_unaligned_memory_transfer_cycles_v1",
})


def _norm(value: object) -> str:
    return re.sub(r"\s+", "", str(value or "")).replace("节点", "结点").replace("−", "-")


def _choice_result(q, adapter: str, expected_keys: list[str], proof: dict) -> dict:
    options = q.options if isinstance(q.options, dict) else {}
    if q.question_type != "single_choice" or len(options) < 2:
        return {"status": "UNKNOWN", "adapter": adapter, "reason": "choice_options_required", "proof": proof}
    actual = str(q.correct_answer or "").strip().upper()
    if len(expected_keys) != 1:
        return {"status": "FAIL", "adapter": adapter, "reason": "non_unique_correct_option",
                "matching_options": expected_keys, "proof": proof}
    expected = expected_keys[0]
    ok = actual == expected and expected in options
    return {"status": "PASS" if ok else "FAIL", "adapter": adapter,
            "reason": "derived_key_matches" if ok else "derived_key_conflict",
            "derived_answer": expected, "matching_options": expected_keys, "proof": proof}


def verify_problem(q):
    if getattr(q, "question_type", None) != "single_choice":
        return None
    stem = _norm(getattr(q, "stem", ""))
    options = q.options if isinstance(q.options, dict) else {}

    if "压缩存储稀疏矩阵" in stem and "存储结构" in stem:
        if len(options) != 4:
            return {"status": "UNKNOWN", "adapter": "hx_sparse_matrix_compression_v1",
                    "reason": "expected_four_options"}
        aliases = {
            "triplet": ("三元组表", "三元组顺序表"),
            "orthogonal": ("十字链表", "十字交叉链表"),
            "adjacency": ("邻接矩阵",),
            "binary": ("二叉链表",),
        }
        canonical = {}
        for key, raw in options.items():
            text = _norm(raw).strip("（()）")
            raw_parts = re.split(r"和|及|、|,", text)
            names = []
            for part in raw_parts:
                found = [name for name, labels in aliases.items() if part in labels]
                if len(found) != 1:
                    names = []
                    break
                names.extend(found)
            if len(names) != 2 or len(set(names)) != 2:
                return {"status": "UNKNOWN", "adapter": "hx_sparse_matrix_compression_v1",
                        "reason": "option_outside_sparse_storage_vocabulary", "option": key}
            canonical[key] = frozenset(names)
        matches = [key for key, pair in canonical.items() if pair == frozenset({"triplet", "orthogonal"})]
        return _choice_result(q, "hx_sparse_matrix_compression_v1", matches,
            {"rule": "sparse matrix storage keeps nonzero values with coordinates; canonical compact structures are triplet table and orthogonal list",
             "options_checked": {key: sorted(pair) for key, pair in canonical.items()}})

    if "非空二叉树" in stem and "先序序列" in stem and "中序序列" in stem and "非叶结点" in stem:
        if len(options) != 4:
            return {"status": "UNKNOWN", "adapter": "hx_preorder_equals_inorder_v1",
                    "reason": "expected_four_options"}
        meanings = {
            "left_only": ("只有左子树", "只有左孩子"),
            "right_only": ("只有右子树", "只有右孩子"),
            "degree_one": ("结点的度均为1", "结点度均为1"),
            "degree_two": ("结点的度均为2", "结点度均为2"),
        }
        canonical = {}
        for key, raw in options.items():
            text = _norm(raw).strip("（()）")
            found = [name for name, labels in meanings.items() if text in labels]
            if len(found) != 1:
                return {"status": "UNKNOWN", "adapter": "hx_preorder_equals_inorder_v1",
                        "reason": "option_outside_binary_tree_vocabulary", "option": key}
            canonical[key] = found[0]
        matches = [key for key, meaning in canonical.items() if meaning == "right_only"]
        return _choice_result(q, "hx_preorder_equals_inorder_v1", matches,
            {"proof": "For preorder and inorder to start with the same root, the root has no left subtree. Applying the same argument recursively to every subtree leaves every non-leaf with only a right child.",
             "options_checked": canonical})

    if "结构JSON=" in stem and "后序序列=" in stem and "同层的结点是" in stem:
        match = re.search(r"结构JSON=(\{.*?\});后序序列=([A-Za-z0-9,]+);目标结点=([A-Za-z0-9]+)", stem)
        adapter = "hx_binary_tree_postorder_depth_v1"
        if not match:
            return {"status": "UNKNOWN", "adapter": adapter, "reason": "tree_statement_format_unsupported"}
        try:
            tree = json.loads(match.group(1))
        except (json.JSONDecodeError, TypeError):
            return {"status": "UNKNOWN", "adapter": adapter, "reason": "tree_json_invalid"}
        if not isinstance(tree, dict) or not tree or len(tree) > 128:
            return {"status": "UNKNOWN", "adapter": adapter, "reason": "tree_size_or_shape_unsupported"}
        parent = Counter()
        for node, children in tree.items():
            if not isinstance(node, str) or not re.fullmatch(r"[A-Za-z0-9]+", node):
                return {"status": "UNKNOWN", "adapter": adapter, "reason": "node_label_unsupported"}
            if not isinstance(children, list) or len(children) != 2:
                return {"status": "UNKNOWN", "adapter": adapter, "reason": "children_must_be_left_right_pair"}
            for child in children:
                if child is not None:
                    if child not in tree or child == node:
                        return {"status": "FAIL", "adapter": adapter, "reason": "invalid_child_reference"}
                    parent[child] += 1
        roots = [node for node in tree if parent[node] == 0]
        if any(count != 1 for node, count in parent.items()) or len(roots) != 1 or any(parent[node] > 1 for node in tree):
            return {"status": "FAIL", "adapter": adapter, "reason": "tree_must_have_one_root_and_one_parent_per_nonroot"}
        depths, postorder, visiting = {}, [], set()

        def walk(node, depth):
            if node in visiting:
                raise ValueError("cycle")
            visiting.add(node)
            depths[node] = depth
            left, right = tree[node]
            if left is not None:
                walk(left, depth + 1)
            if right is not None:
                walk(right, depth + 1)
            postorder.append(node)
            visiting.remove(node)

        try:
            walk(roots[0], 0)
        except ValueError:
            return {"status": "FAIL", "adapter": adapter, "reason": "tree_contains_cycle"}
        if set(depths) != set(tree):
            return {"status": "FAIL", "adapter": adapter, "reason": "tree_contains_unreachable_nodes"}
        stated_postorder = match.group(2).split(",")
        target_node = match.group(3)
        if len(stated_postorder) != len(tree) or len(set(stated_postorder)) != len(tree) or stated_postorder != postorder:
            return {"status": "FAIL", "adapter": adapter, "reason": "stated_postorder_conflicts_with_transcribed_tree",
                    "derived_postorder": postorder}
        if target_node not in depths:
            return {"status": "FAIL", "adapter": adapter, "reason": "target_node_missing"}
        if len(options) != 4:
            return {"status": "UNKNOWN", "adapter": adapter, "reason": "expected_four_options"}
        matching = []
        normalized_options = {}
        for key, raw in options.items():
            value = _norm(raw).strip("（()）")
            if value not in depths:
                return {"status": "UNKNOWN", "adapter": adapter, "reason": "option_node_missing", "option": key}
            normalized_options[key] = value
            if value != target_node and depths[value] == depths[target_node]:
                matching.append(key)
        return _choice_result(q, adapter, matching,
            {"root": roots[0], "derived_postorder": postorder, "target_node": target_node,
             "target_depth_zero_based": depths[target_node], "same_depth_labels": sorted(
                 node for node, depth in depths.items() if depth == depths[target_node]),
             "options_checked": normalized_options,
             "scope": "explicit left/right child JSON transcribed from a cited tree diagram"})

    if "主存每次最多读写" in stem and "double型变量x的主存地址为" in stem:
        adapter = "hx_unaligned_memory_transfer_cycles_v1"
        match = re.search(r"主存每次最多读写(\d{1,3})位数据.*?double型变量x的主存地址为([0-9A-F]+)H", stem)
        if not match:
            return {"status": "UNKNOWN", "adapter": adapter, "reason": "memory_statement_format_unsupported"}
        width_bits, address_hex = int(match.group(1)), match.group(2)
        if width_bits < 8 or width_bits > 128 or width_bits % 8:
            return {"status": "UNKNOWN", "adapter": adapter, "reason": "transfer_width_outside_byte_bound"}
        transfer_bytes = width_bits // 8
        value_bytes = 8
        address = int(address_hex, 16)
        offset = address % transfer_bytes
        cycles = (offset + value_bytes + transfer_bytes - 1) // transfer_bytes
        numeric_options = {}
        for key, raw in options.items():
            value = _norm(raw).strip("（）()。.")
            if not re.fullmatch(r"\d{1,4}", value):
                return {"status": "UNKNOWN", "adapter": adapter, "reason": "non_integer_cycle_option"}
            numeric_options[key] = int(value)
        matches = [key for key, value in numeric_options.items() if value == cycles]
        return _choice_result(q, adapter, matches,
            {"address_hex": address_hex, "address_mod_transfer_bytes": offset,
             "value_bytes_double": value_bytes, "transfer_bytes_per_cycle": transfer_bytes,
             "covered_byte_span": offset + value_bytes, "derived_cycles": cycles,
             "options_checked": numeric_options,
             "assumption": "byte-addressed memory; each stated cycle transfers at most the stated bus width"})

    return None
