"""Offline P1 audit; no database/LLM calls and no automatic VERIFIED promotion."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.services.golden_learning_slice import GoldenSlice, audit_slice, reviewed_pack
from backend.services.exam_reference_service import build_exam_reference_seed


def audit_files(asset: GoldenSlice, root: Path = ROOT) -> dict:
    report = audit_slice(asset)
    nodes, _ = build_exam_reference_seed()
    nodes = {n["code"]: n for n in nodes}
    topics = []
    for topic in asset.topics:
        path = root / "seed" / "lessons" / (topic.kp_code + ".md")
        raw = path.read_bytes() if path.is_file() else b""
        text = raw.decode("utf-8")
        node = nodes.get(topic.kp_code)
        topics.append({"kp_code": topic.kp_code, "name": topic.name,
            "node_binding_matches": bool(node and node["name"] == topic.name
                and node.get("is_assessable", True) and
                (node["subject"] == "考研数学" if topic.subject == "math2" else node["subject"] == "408")),
            "lesson_path": path.relative_to(root).as_posix(),
            "lesson_sha256": hashlib.sha256(raw).hexdigest(),
            "lesson_hash_matches": bool(raw) and hashlib.sha256(raw).hexdigest() == topic.lesson_sha256,
            "lesson_review": topic.lesson_review.status,
            "has_concept_conditions_example": all(term in text for term in ("概念", "条件", "例题")),
            "draft_question_count": sum(q.content.kp_code == topic.kp_code for q in asset.questions)})
    report["topics"] = topics
    report["structural_checks_passed"] = report["all_probes_passed"] and all(
        t["node_binding_matches"] and t["lesson_hash_matches"] and t["has_concept_conditions_example"] for t in topics)
    report["release_ready"] = report["structural_checks_passed"] and report["human_review_complete"]
    return report


def render_review_sheet(asset: GoldenSlice, report: dict) -> str:
    """Deterministic human-readable sheet; not an automated content review."""
    lines = [f"# Golden Learning Slice · {asset.slice_id} v{asset.version}", "",
        "这是人工核验清单，不是已核验题库。数学二与 408 各一个小范围原创合成专题；不是历年真题。",
        "自动验算和判题测试不能把 GENERATED / UNVERIFIED 自动变成 VERIFIED。", "",
        f"资产哈希：`{report['asset_sha256']}`", "",
        "逐题核对题干、选项唯一性、标准答案、解析、知识映射、判题方式和发布来源。",
        "数值最终答案判对不代表过程正确；证明、符号表达式和算法题不得强行数值评分。", ""]
    by_id = {r["source_id"]: r for r in report["cases"]}
    for topic in asset.topics:
        lines.extend([f"## {topic.name}（{topic.subject}）", "",
            f"节点：`{topic.kp_code}`；讲解状态：{topic.lesson_review.status}。",
            f"讲解：`seed/lessons/{topic.kp_code}.md`；SHA256：`{topic.lesson_sha256}`。", ""])
        for q in asset.questions:
            c = q.content
            if c.kp_code != topic.kp_code: continue
            lines.extend([f"### {c.source_id} · {c.question_type} · {c.question_role}", "",
                c.stem, ""])
            if c.options:
                lines.extend([f"- {key}. {value}" for key, value in c.options.items()] + [""])
            lines.extend([f"候选答案：{c.correct_answer}", "", f"候选解析：{c.explanation}", "",
                f"技能标签：{'、'.join(c.skill_tags)}；估计 {c.estimated_minutes} 分钟（未进行学习耗时校准）。",
                f"拟用判题：{c.grading_method or '不自动判分'}；内容来源：{q.source.origin}。",
                "审核状态：" + "；".join(f"{key}={q.reviews[key].status}" for key in sorted(q.reviews)) + "。",
                f"审核绑定哈希：`{q.content_hash()}`。",
                f"判题协议探针：{len(q.probes)} 个，{'通过' if all(p['passed'] for p in by_id[c.source_id]['probes']) else '未通过'}（不等于内容通过）。", ""])
    lines.extend(["## 发布与学习闭环边界", "",
        "全部六项题目审核需记录真实人工审核人、日期、说明和上述绑定哈希；修改内容后旧审核失效。",
        "讲解需独立确认并绑定文件哈希。审核完成后才导出 reviewed pack，再用现有导入器先 dry-run。",
        "原引用节点上线在线题还需单独核对毕业策略，不由导入器自动修改。",
        "当前集成测试中的人工审核是明确标注的隔离模拟，不是本文件已获真人确认。", ""])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("asset", nargs="?", type=Path,
        default=ROOT / "eval/golden/integral_binary_tree_v1.json")
    parser.add_argument("--export-reviewed", type=Path, help="Export only after full human review; refuses overwrite")
    parser.add_argument("--review-sheet", type=Path, help="Create a readable review checklist; refuses overwrite")
    args = parser.parse_args()
    if args.asset.stat().st_size > 4 * 1024 * 1024:
        raise ValueError("golden asset exceeds 4 MiB")
    asset = GoldenSlice.model_validate_json(args.asset.read_text(encoding="utf-8"))
    report = audit_files(asset)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.review_sheet:
        with args.review_sheet.open("x", encoding="utf-8") as stream:
            stream.write(render_review_sheet(asset, report))
    if args.export_reviewed:
        if not report["release_ready"]:
            raise ValueError("golden slice is not release-ready; human review or structural checks pending")
        pack = reviewed_pack(asset)
        # Create exclusively: never overwrite reviewed evidence or an older pack.
        with args.export_reviewed.open("x", encoding="utf-8") as stream:
            stream.write(pack.model_dump_json(indent=2) + "\n")
    return 0 if report["structural_checks_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
