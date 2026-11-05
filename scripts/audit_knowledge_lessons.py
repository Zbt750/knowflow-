"""生成逐节点讲解状态清单，文件存在不等于内容已核验。"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.generate_knowledge_lessons import _all_nodes, LESSON_DIR


def quality(text: str) -> str:
    if "knowledge-lesson-quality:subject-textbook-draft-v3" in text:
        return "教材式逐节点讲解初稿（待用户检查与独立审核）"
    if "knowledge-lesson-quality:topic-draft-v2" in text:
        return "专题讲解草稿（待独立审核）"
    if "章节背景摘要，非完整专题讲解" in text:
        return "章节背景摘要（待逐节点补写）"
    return "原有讲解（核验状态未认定）"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--hashes", type=Path, help="在生成文件检查通过后保存本次更新前的指纹")
    args = parser.parse_args()
    if args.hashes:
        from scripts.generate_knowledge_lessons import generate
        result = generate(check=True)
        if result["missing"] or result["outdated"]:
            raise SystemExit("存在手工修改或过期生成文件，拒绝自动建立更新基准")
        hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in LESSON_DIR.glob("*.md")}
        args.hashes.write_text(json.dumps(hashes, indent=2), encoding="utf-8")
    rows = []
    counts = Counter()
    for node in _all_nodes()[0]:
        path = LESSON_DIR / f"{node['code']}.md"
        state = quality(path.read_text(encoding="utf-8")) if path.is_file() else "缺失"
        counts[state] += 1
        rows.append(f"| {node['name']} | `{node['code']}` | {state} |")
    report = "# 知识节点讲解状态（自动生成）\n\n"
    report += "重建命令：`python scripts/audit_knowledge_lessons.py --output docs/knowledge-lesson-status.md`。\n\n"
    report += "仅检查当前文件与声明状态，不认证教学正确性、考纲完整性或问答召回质量。专题草稿由项目补写，不等于 VERIFIED。练习从关联题库进入，不在讲解中重复生成题库。\n\n"
    report += "\n".join(f"- {label}：{count}" for label, count in counts.items())
    report += "\n\n| 节点 | 编号 | 当前状态 |\n| --- | --- | --- |\n" + "\n".join(rows) + "\n"
    if args.output:
        args.output.write_text(report, encoding="utf-8", newline="\n")
    print(dict(counts))


if __name__ == "__main__":
    main()
