#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""只读盘点：真实知识树 × 现有题库快照，判定每个叶子是否适合大题。

数据源（都不连接数据库）：
1. tmp/phase1_20261006/question_counts.json
   —— 项目自己的知识树+在线题量审计导出（304 节点 / 284 可考核叶子）。
2. storage/quality-audits/long-question-supply-20261017/sealed-questions.copy.sql
   —— 项目自己的封存题目快照（2380 条，含 provenance / trust / active）。

说明：
- 快照里 253 个叶子能通过 grading_config.generation.node_code 反查到稳定 code；
  剩余叶子用审计导出的在线题量，快照列留空并标 snapshot_mapped=false。
- 这不是实时库；导入前仍需在隔离库重跑一次同一脚本（脚本本身支持后续换成实时导出）。
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import re
from pathlib import Path

LONG_TYPES = {"calculation", "proof", "subjective", "discussion", "program"}

# 明确只适合短题（选择/填空/概念辨析）的 408 考点。
# 判定依据：节点名描述的是“分类、组成、层次、定义、优缺点比较”，
# 或同一章已有更具体的计算/设计节点承接大题。
CONCEPT_ONLY_408 = {
    # 计算机网络
    "网络概念组成与功能", "传输介质", "通信基础", "网络分层与参考模型",
    "网络应用模型", "传输层功能", "网络层功能", "数据链路层功能与组帧",
    "路由器组成与功能", "流量控制与可靠传输", "拥塞控制（网络层视角）",
    # 计算机组成原理
    "计算机系统层次结构", "CISC 与 RISC", "总线基本概念与组成",
    "存储器层次结构", "多处理器基本概念", "控制器", "I/O 接口",
    # 操作系统
    "操作系统概念与发展", "OS 结构", "系统调用", "CPU 运行模式",
    "虚拟机", "内存管理基础", "进程与线程基本概念", "文件基本概念",
    "I/O 设备分类与接口", "操作系统引导", "虚拟文件系统与挂载",
    "同步与互斥基本概念", "CPU 调度基本概念", "I/O 软件层次结构",
    # 数据结构
    "图基本概念", "排序通论", "各排序算法比较", "各查找算法比较", "树与森林",
}

# 数学二不考无穷级数；树里有 2 个节点属于数一/数三范围。
OUT_OF_SCOPE_MATH_KEYWORDS = ("无穷级数", "series")

# 纯定义性数学节点：出大题会退化成默写定义。
MATH_DEFINITION_ONLY = {"极值定义"}


def uncopy(value: str):
    if value == r"\N":
        return None
    escapes = {"t": "\t", "n": "\n", "r": "\r", "b": "\b", "f": "\f", "v": "\v", "\\": "\\"}
    return re.sub(
        r"\\([0-7]{1,3}|.)",
        lambda m: chr(int(m[1], 8)) if m[1][0] in "01234567" else escapes.get(m[1], m[1]),
        value,
    )


def load_snapshot(copy_path: Path) -> dict:
    """按 kp_id 聚合封存题目快照；返回 {kp_id: stats} 与 kp_id->code 映射。"""
    columns = None
    per_kp = collections.defaultdict(lambda: collections.Counter())
    code_by_kp: dict[str, set[str]] = collections.defaultdict(set)
    rows = 0
    for line in copy_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("COPY public.questions ("):
            columns = line.split("(", 1)[1].split(")", 1)[0].split(", ")
            continue
        if columns is None:
            continue
        if line == r"\.":
            break
        values = line.split("\t")
        if len(values) != len(columns):
            continue
        row = dict(zip(columns, values))
        rows += 1
        kp_id = row["kp_id"]
        qtype = uncopy(row["question_type"])
        active = uncopy(row["is_active"]) == "t"
        hidden = uncopy(row["is_hidden"]) == "t"
        provenance = uncopy(row["question_provenance"]) or ""
        trust = uncopy(row["content_trust"]) or ""
        c = per_kp[kp_id]
        c["total"] += 1
        if active and not hidden:
            c["active"] += 1
            if qtype in LONG_TYPES:
                c["active_long"] += 1
            if trust == "auto_verified":
                c["formal"] += 1
                if qtype in LONG_TYPES:
                    c["formal_long"] += 1
            if provenance == "ai_generated_practice":
                c["ai_practice"] += 1
                if qtype in LONG_TYPES:
                    c["ai_practice_long"] += 1
        if not active:
            c["archived"] += 1
        gc = uncopy(row.get("grading_config"))
        if gc:
            try:
                node_code = ((json.loads(gc).get("generation") or {}).get("node_code") or "").strip()
            except (ValueError, TypeError):
                node_code = ""
            if node_code:
                code_by_kp[kp_id].add(node_code)
    mapping = {kp: next(iter(codes)) for kp, codes in code_by_kp.items() if len(codes) == 1}
    return {"per_kp": per_kp, "code_by_kp": mapping, "rows": rows}


def classify(node: dict) -> tuple[bool, str]:
    code = node["code"]
    name = node["name"]
    path = node["path"]
    subject = node["subject"]
    if not node["assessable"]:
        return False, "非可考核叶子（父节点只做结构汇总）"
    if name.startswith("专题汇总") or ".family." in code:
        return False, "专题汇总节点：用于章节组织，不对应单一可考核考点"
    if "待核对" in name or "来源未提供考点标签" in name:
        return False, "考点标签缺失、范围未确认：先核对，不自动生成"
    if subject == "考研数学":
        if any(k in path or k in code for k in OUT_OF_SCOPE_MATH_KEYWORDS):
            return False, "超出数学二考试范围（无穷级数属数一/数三）"
        if name in MATH_DEFINITION_ONLY:
            return False, "纯定义性内容，更适合选择/填空短题"
        return True, ""
    if subject == "408":
        if name in CONCEPT_ONLY_408:
            return False, "概念/分类/层次/组成类考点，更适合选择、填空或概念辨析短题"
        return True, ""
    return True, ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--counts", type=Path, default=Path("tmp/phase1_20261006/question_counts.json"))
    parser.add_argument("--copy", type=Path,
                        default=Path("storage/quality-audits/long-question-supply-20261017/sealed-questions.copy.sql"))
    parser.add_argument("--out-dir", type=Path, default=Path("docs"))
    parser.add_argument("--target-per-node", type=int, default=2)
    args = parser.parse_args()

    tree = json.loads(args.counts.read_text(encoding="utf-8"))
    snapshot = load_snapshot(args.copy)
    per_kp, code_by_kp = snapshot["per_kp"], snapshot["code_by_kp"]

    rows = []
    for node in tree["nodes"]:
        path_parts = node["path"].split(" / ")
        chapter = path_parts[1] if len(path_parts) > 1 else node["subject"]
        parent = " / ".join(path_parts[:-1])
        suitable, reason = classify(node)
        # 审计导出的 online 只统计可用题；types 里有各题型数量。
        types = node.get("types") or {}
        online_long = sum(n for t, n in types.items() if t in LONG_TYPES)
        online_total = int(node.get("online") or 0)

        kp_id = next((k for k, v in code_by_kp.items() if v == node["code"]), None)
        stats = per_kp.get(kp_id, collections.Counter()) if kp_id else collections.Counter()
        mapped = kp_id is not None
        existing_long = stats.get("formal_long", 0) if mapped else online_long
        target = args.target_per_node if suitable else 0
        gap = max(0, target - existing_long)
        rows.append({
            "知识点ID（稳定code）": node["code"],
            "知识点名称": node["name"],
            "学科": node["subject"],
            "章节": chapter,
            "父节点路径": parent,
            "有效叶子": "是" if node["assessable"] else "否",
            "可考核": "是" if node["assessable"] else "否",
            "在线题目总数": online_total,
            "在线大题数(审计)": online_long,
            "快照可映射": "是" if mapped else "否",
            "快照题目总数": stats["total"] if mapped else "",
            "快照有效题": stats["active"] if mapped else "",
            "快照公共正式题": stats["formal"] if mapped else "",
            "快照AI生成练习": stats["ai_practice"] if mapped else "",
            "快照归档题": stats["archived"] if mapped else "",
            "快照有效大题": stats["formal_long"] if mapped else "",
            "现有有效大题数(采用)": existing_long,
            "适合大题": "是" if suitable else "否",
            "需要补充": "是" if gap > 0 else "否",
            "目标大题数": target,
            "缺口": gap,
            "暂不生成理由": reason,
        })

    args.out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = args.out_dir / "long-question-inventory-20261018.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    leaves = [r for r in rows if r["有效叶子"] == "是"]
    suitable = [r for r in leaves if r["适合大题"] == "是"]
    unsuitable = [r for r in leaves if r["适合大题"] == "否"]
    reasons = collections.Counter(r["暂不生成理由"] for r in unsuitable)
    by_subject = {}
    for subject in sorted({r["学科"] for r in leaves}):
        sub = [r for r in leaves if r["学科"] == subject]
        sub_s = [r for r in sub if r["适合大题"] == "是"]
        by_subject[subject] = {
            "有效叶子": len(sub),
            "适合大题": len(sub_s),
            "需要补充": sum(1 for r in sub_s if r["需要补充"] == "是"),
            "现有有效大题": sum(int(r["现有有效大题数(采用)"]) for r in sub_s),
            "目标大题": sum(int(r["目标大题数"]) for r in sub_s),
        }
    # 按章节生成可断点续跑的批次计划；批次内按知识点缺口排序。
    chapters: dict[tuple[str, str], list[dict]] = collections.defaultdict(list)
    for row in suitable:
        chapters[(row["学科"], row["章节"])].append({
            "kp_code": row["知识点ID（稳定code）"],
            "kp_name": row["知识点名称"],
            "existing_long": int(row["现有有效大题数(采用)"]),
            "target": int(row["目标大题数"]),
            "gap": int(row["缺口"]),
        })
    plan = []
    pilot_codes = {
        "math.exam.936d8c834760", "math.exam.4586eb88acb7",
        "cs408.ds.topic.64cda87cdc82", "cs408.co.topic.ba9896acc602",
        "cs408.os.topic.006da51a6b0f",
    }
    for index, ((subject, chapter), nodes) in enumerate(
            sorted(chapters.items(), key=lambda kv: (kv[0][0], kv[0][1])), start=1):
        nodes.sort(key=lambda item: (-item["gap"], item["kp_code"]))
        plan.append({
            "batch_id": f"LQB-{index:02d}",
            "subject": subject,
            "chapter": chapter,
            "node_count": len(nodes),
            "target": sum(item["target"] for item in nodes),
            "gap": sum(item["gap"] for item in nodes),
            "pilot_nodes": [item["kp_code"] for item in nodes if item["kp_code"] in pilot_codes],
            "nodes": nodes,
        })
    (args.out_dir / "long-question-batch-plan-20261018.json").write_text(
        json.dumps({"created_at": "2026-10-18", "source": "offline inventory snapshot",
                    "pilot_batch": "longbank-20261018-pilot",
                    "batches": plan}, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = {
        "source_counts": str(args.counts),
        "source_questions": str(args.copy),
        "scope": "offline_snapshot_not_live_database",
        "created_at": "2026-10-18",
        "nodes_total": len(rows),
        "assessable_leaves": len(leaves),
        "suitable_for_long": len(suitable),
        "not_suitable": len(unsuitable),
        "suitable_by_subject": by_subject,
        "existing_long_on_suitable": sum(int(r["现有有效大题数(采用)"]) for r in suitable),
        "target_total": sum(int(r["目标大题数"]) for r in suitable),
        "gap_total": sum(int(r["缺口"]) for r in suitable),
        "snapshot_rows": snapshot["rows"],
        "snapshot_kp_ids_mapped": len(code_by_kp),
        "reasons": dict(reasons),
        "note": "在线题量来自项目 2026-10-06 审计导出；题目来源分布来自 2026-10-17 封存快照；"
                "未连接开发库，导入前需在隔离库重跑。",
    }
    (args.out_dir / "long-question-inventory-20261018.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
