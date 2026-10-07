"""Read-only per-node online supply and indexed-exam year-window comparison.

References are potential source questions, not full, verified online exercises.
Quantity thresholds are configurable planning aids, never mastery certification.
"""
from collections import Counter, defaultdict
from datetime import datetime
import argparse
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.services.answer_grading import available_grading_method

WINDOWS = {"2010_2026": (2010, 2026), "2017_2026": (2017, 2026), "2021_2026": (2021, 2026)}


def summarize(nodes, questions, references, minimum=5):
    if not 1 <= minimum <= 100:
        raise ValueError("minimum must be between 1 and 100")
    active = {n.id: n for n in nodes if n.is_active}
    online, refs = defaultdict(list), defaultdict(set)
    for q in questions:
        if q.is_active and q.kp_id in active:
            online[q.kp_id].append(q)
    for r in references:
        if r.knowledge_point_id in active:
            refs[r.knowledge_point_id].add((r.subject, r.year, r.question_number))

    def path(node):
        names, seen = [], set()
        while node is not None and node.id not in seen:
            seen.add(node.id)
            names.append(node.name)
            node = active.get(node.parent_id)
        return " / ".join(reversed(names))

    rows = []
    for n in sorted(active.values(), key=lambda n: n.code):
        qs = online[n.id]
        grading = sum(bool(available_grading_method(question_type=q.question_type, config=q.grading_config,
                                                   expected=q.correct_answer, options=q.options)) for q in qs)
        windows = {key: len({r for r in refs[n.id] if first <= r[1] <= last})
                   for key, (first, last) in WINDOWS.items()}
        rows.append({"code": n.code, "name": n.name, "path": path(n), "subject": n.subject,
            "assessable": n.is_assessable, "topic_summary": ".family." in n.code or n.code.startswith("math.family."),
            "online": len(qs), "automatic_grading": grading,
            "types": dict(Counter(q.question_type for q in qs)),
            "transcribed_unverified": sum((q.grading_config or {}).get("provenance", {}).get("content_status") == "source_transcribed" for q in qs),
            "exam_reference_windows": windows,
            "reference_years": sorted({r[1] for r in refs[n.id]}),
            "online_gap": max(0, minimum - len(qs)) if n.is_assessable else None})
    subjects = {}
    for subject in sorted({n.subject for n in active.values()}):
        scoped = [r for r in rows if r["subject"] == subject and r["assessable"]]
        leaf_scoped = [r for r in scoped if not r["topic_summary"]]
        unique = set().union(*(refs[n.id] for n in active.values() if n.subject == subject))
        subjects[subject] = {"assessable_nodes": len(scoped), "topic_summary_nodes": len(scoped)-len(leaf_scoped),
            "individual_nodes": len(leaf_scoped), "online_questions": sum(r["online"] for r in scoped),
            "automatic_grading": sum(r["automatic_grading"] for r in scoped),
            "online_quantity_distribution": dict(sorted(Counter(r["online"] for r in scoped).items())),
            "windows": {key: {"distinct_indexed_questions": len({r for r in unique if first <= r[1] <= last}),
                "individual_nodes_with_zero_refs": sum(r["exam_reference_windows"][key] == 0 for r in leaf_scoped),
                "individual_nodes_below_minimum_refs": sum(r["exam_reference_windows"][key] < minimum for r in leaf_scoped),
                "individual_nodes_with_5_plus_refs": sum(r["exam_reference_windows"][key] >= 5 for r in leaf_scoped),
                "individual_nodes_with_10_plus_refs": sum(r["exam_reference_windows"][key] >= 10 for r in leaf_scoped)}
                for key, (first, last) in WINDOWS.items()}}
    return {"created_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(), "minimum_quantity_only": minimum,
        "quality_and_mapping_certified": False, "nodes": rows, "subjects": subjects,
        "active_nodes": len(rows), "assessable_nodes": sum(r["assessable"] for r in rows),
        "online_total": sum(r["online"] for r in rows),
        "distinct_indexed_exam_questions": len(set().union(*refs.values())) if refs else 0,
        "mock_source_availability": "not_certified; catalog entries are not full question records"}


def markdown(report):
    def safe(value):
        return str(value).replace("|", "\\|").replace("\n", " ")
    text = ["# 当前逐知识点题量与年份范围对比", "", f"统计时间：{report['created_at']}（Asia/Shanghai）。只读开发数据库，不改题库或学习记录。", "",
        "## 统计口径", "",
        f"- 共{report['active_nodes']}个活跃节点，{report['assessable_nodes']}个标记可评估；分类节点另列，不要求父节点独立拥有题目。",
        f"- 在线题{report['online_total']}道；真题题号索引跨节点去重{report['distinct_indexed_exam_questions']}道。索引不是已录入的题干和答案，不能两者相加。",
        f"- 暂用每节点{report['minimum_quantity_only']}道作为最低数量观察线，不是题型覆盖、毕业条件或质量合格线；同时给出5/10道来源覆盖对比。",
        "- 专题汇总节点与细知识点会关联同一道原卷题，分别列出，但不把汇总节点数量作为新的独立知识点覆盖。",
        "- 原卷引用归类尚未逐题核验。模拟题目录不算题量，AI候选及已停用演示题不算在线题。",
        "- 当前细节点仍按已有考点标签分列，相近概念可能分散在多个code下；某标签0题不代表该知识在历年考试中从未出现。尤其旧演示节点与后来导入的真题标签节点未做自动语义合并。",
        "- 例如‘反常积分敛散性’与‘反常积分的计算与敛散性’分别计数。若要判断课程级考点是否题量够，须先复核同义/父子/交叉标签，再对相关题号取并集，不能直接相加。",
        "- 缩小年份只会减少可选来源题，不会让每节点题量增加；可用于缩小录入工作量，但低频考点可能更缺题。", "",
        "## 学科总量", "", "| 学科 | 可评估节点 | 其中专题汇总 | 细知识节点 | 在线题 | 可自动判题 |", "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for subject, row in report["subjects"].items():
        text.append(f"| {safe(subject)} | {row['assessable_nodes']} | {row['topic_summary_nodes']} | {row['individual_nodes']} | {row['online_questions']} | {row['automatic_grading']} |")
    text += ["", "## 缩小年份后的来源题量（不是在线题量）", "",
        "| 学科 | 年份 | 去重索引题数 | 细节点无引用 | 细节点低于观察线 | 细节点≥5引用 | 细节点≥10引用 |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |"]
    for subject, row in report["subjects"].items():
        for window, r in row["windows"].items():
            text.append(f"| {safe(subject)} | {window.replace('_', '—')} | {r['distinct_indexed_questions']} | {r['individual_nodes_with_zero_refs']} | {r['individual_nodes_below_minimum_refs']} | {r['individual_nodes_with_5_plus_refs']} | {r['individual_nodes_with_10_plus_refs']} |")
    for subject in report["subjects"]:
        text += ["", f"## {subject}：每个细知识点", "",
            "| 知识点 | 在线题 | 自动判题 | 2010—2026引用 | 2017—2026引用 | 2021—2026引用 | 在线数量判断 | 节点code |",
            "| --- | ---: | ---: | ---: | ---: | ---: | --- | --- |"]
        for r in report["nodes"]:
            if r["subject"] != subject or not r["assessable"] or r["topic_summary"]:
                continue
            w = r["exam_reference_windows"]
            judgment = "无在线题" if r["online"] == 0 else f"低于{report['minimum_quantity_only']}道" if r["online_gap"] else "数量达到观察线（不代表覆盖够）"
            text.append(f"| {safe(r['name'])} | {r['online']} | {r['automatic_grading']} | {w['2010_2026']} | {w['2017_2026']} | {w['2021_2026']} | {judgment} | {r['code']} |")
    text += ["", "## 专题汇总节点（与上表引用重叠，不相加）", "",
        "| 汇总节点 | 在线题 | 2010—2026引用 | 2017—2026引用 | 2021—2026引用 | code |", "| --- | ---: | ---: | ---: | ---: | --- |"]
    for r in report["nodes"]:
        if r["topic_summary"]:
            w = r["exam_reference_windows"]
            text.append(f"| {safe(r['name'])} | {r['online']} | {w['2010_2026']} | {w['2017_2026']} | {w['2021_2026']} | {r['code']} |")
    text += ["", "## 分类节点（不独立考核）", "", "| 分类名称 | code |", "| --- | --- |"]
    for r in report["nodes"]:
        if not r["assessable"]:
            text.append(f"| {safe(r['name'])} | {r['code']} |")
    return "\n".join(text) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--minimum", type=int, default=5)
    args = parser.parse_args()
    from sqlalchemy import select
    from backend.config import get_settings
    from backend.db import create_db_engine, create_session_factory
    from backend.models.learning import KnowledgePoint, Question, ExamQuestionReference
    engine = create_db_engine(str(get_settings().active_database_url))
    try:
        with create_session_factory(engine)() as db:
            report = summarize(list(db.scalars(select(KnowledgePoint))), list(db.scalars(select(Question))),
                               list(db.scalars(select(ExamQuestionReference))), args.minimum)
    finally:
        engine.dispose()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.with_suffix(".json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    args.output.write_text(markdown(report), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "nodes"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
