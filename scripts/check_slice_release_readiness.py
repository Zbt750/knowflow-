"""Offline readiness audit of UNVERIFIED worksheets; never release or write DB.

Hypothetical verified configs below exist only in memory to inspect parser
applicability. They are NOT content attestations or production configuration.
"""
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.services.answer_grading import available_grading_method, grade_final_answer
from backend.services.golden_learning_slice import digest
from scripts.prepare_real_slice_review import identity


def options_dict(options):
    if isinstance(options, dict):
        return options
    if isinstance(options, list) and all(isinstance(o, dict) and o.get("label") for o in options):
        labels = [o["label"] for o in options]
        if len(set(labels)) != len(labels):
            return None
        return {o["label"]: o.get("text", o.get("html", "")) for o in options}
    return None


def audit(worksheet, batch):
    if worksheet.get("version") != "real-slice-derivation-worksheet-v1":
        raise ValueError("Unsupported worksheet")
    if batch.get("version") != "structured-real-slice-intake-v1":
        raise ValueError("Unsupported batch")
    if worksheet.get("batch_sha256") != digest(batch):
        raise ValueError("Worksheet no longer matches intake batch")
    indexed = {}
    for q in batch["questions"]:
        key = identity(q)
        if key in indexed:
            raise ValueError("Duplicate intake identity")
        indexed[key] = q
    rows, seen = [], set()
    source_rows = [(q, q.get("candidate"), "candidate_sha256", False) for q in worksheet["questions"]]
    source_rows += [(q, q.get("record"), "record_sha256", True)
                   for q in worksheet.get("online_integral_review", {}).get("questions", [])]
    for row, content, hash_field, online in source_rows:
        key = row["candidate_id"]
        if key in seen:
            raise ValueError("Duplicate worksheet identity")
        seen.add(key)
        if not isinstance(content, dict) or row.get(hash_field) != digest(content):
            raise ValueError(f"Content changed since worksheet: {key}")
        if not online and (key not in indexed or digest(indexed[key]) != digest(content)):
            raise ValueError(f"Candidate differs from intake: {key}")
        # The worksheet is only an AI draft. Never accept a caller flipping flags.
        if row.get("human_review_confirmed") is not False or row.get("can_import") is not False:
            raise ValueError("Use existing six-aspect human-review bridge, not worksheet approval flags")
        method = row.get("potential_grading_method_after_review")
        kind = content.get("question_type")
        expected = content.get("correct_answer") if online else row.get("proposed_answer")
        options = options_dict(content.get("options"))
        hypothetical = {"verified": True, "method": method}
        supported = available_grading_method(question_type=kind, config=hypothetical,
                                              expected=expected, options=options)
        submitted = expected if kind != "single_choice" else None
        selected = expected if kind == "single_choice" else None
        unverified = grade_final_answer(question_type=kind, config={"verified": False, "method": method},
            answer=submitted, selected_option=selected, expected=expected, options=options)
        simulated = grade_final_answer(question_type=kind, config=hypothetical,
            answer=submitted, selected_option=selected, expected=expected, options=options)
        blockers = ["six_aspect_human_review_missing", "original_source_and_rights_review_missing"]
        # Carry source comparison findings as blockers, not just passive notes.
        blockers.extend(issue for issue in sorted(set(content.get("issues", [])) | set(row.get("original_issues", [])))
                        if issue in {"local_source_year_conflict", "local_source_subject_edition_conflict",
                                     "local_source_question_number_conflict", "primary_mapping_conversion_conflict"})
        if not kind:
            blockers.append("structured_question_type_missing")
        if not supported:
            blockers.append("proposed_grader_not_applicable_to_current_content")
        if row.get("actual_option_check") and not row["actual_option_check"].get("matches_proposal"):
            blockers.append("actual_option_parse_or_derivation_failed")
        if row.get("printed_answer_matches_proposal") is False:
            blockers.append("printed_answer_conflicts_with_derivation")
        if row.get("probe_id"):
            probe = worksheet.get("probes", {}).get(row["probe_id"])
            if not probe or probe.get("passed") is not True:
                blockers.append("derivation_probe_missing_or_failed")
        proposal = row.get("structural_proposal")
        draft_applicability = None
        if proposal:
            if not isinstance(proposal, dict) or proposal.get("status") != "UNVERIFIED" or proposal.get("can_import") is not False:
                raise ValueError("Structural proposal cannot carry approval")
            draft_applicability = available_grading_method(
                question_type=proposal.get("proposed_question_type"), config=hypothetical,
                expected=expected, options=proposal.get("proposed_options"))
        rows.append({"candidate_id": key, "online_snapshot": online,
            "current_unverified_verdict": asdict(unverified),
            "hypothetical_parser_verdict_NOT_APPROVAL": asdict(simulated),
            "hypothetical_supported_method": supported, "blockers": blockers,
            "draft_structure_applicability_NOT_APPROVAL": draft_applicability,
            "preserved_original_issues": sorted(set(content.get("issues", [])) | set(row.get("original_issues", []))),
            "preserved_review_boundary": row.get("remaining_boundary", row.get("boundaries", [])),
            "can_release": False, "can_produce_objective_evidence": False})
    # These queues schedule review, never certify content or silently discard
    # difficult cases. Every worksheet row belongs to exactly one queue.
    queues = {name: [] for name in (
        "source_conflict", "structure_missing", "grader_unsupported", "ready_for_human_review")}
    conflicts = {"local_source_year_conflict", "local_source_subject_edition_conflict",
                 "local_source_question_number_conflict", "primary_mapping_conversion_conflict"}
    for row in rows:
        blockers = set(row["blockers"])
        if blockers & conflicts:
            queue = "source_conflict"
        elif "structured_question_type_missing" in blockers:
            queue = "structure_missing"
        elif blockers - {"six_aspect_human_review_missing", "original_source_and_rights_review_missing"}:
            queue = "grader_unsupported"
        else:
            queue = "ready_for_human_review"
        queues[queue].append(row["candidate_id"])
    selected_candidates = {r["candidate_id"] for r in rows if not r["online_snapshot"]}
    return {"version": "real-slice-release-preflight-v1", "worksheet_sha256": digest(worksheet),
        "code_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in (
            "scripts/check_slice_release_readiness.py", "backend/services/answer_grading.py")},
        "intake_sha256": digest(batch), "database_written": False, "release_ready": False,
        "questions": rows, "count": len(rows),
        "intake_count": len(indexed), "selected_intake_count": len(selected_candidates),
        "not_selected_intake_ids": sorted(set(indexed) - selected_candidates),
        "review_queues": queues,
        "review_queue_boundary": "Review scheduling only: ready_for_human_review is not VERIFIED, released, rights-cleared or suitable for objective evidence. Unsupported grading does not forbid reviewed readable questions.",
        "hypothetical_parser_applicable_count": sum(bool(r["hypothetical_supported_method"]) for r in rows),
        "verified_count": 0, "verified_count_scope": "this UNVERIFIED worksheet, not a global DB audit",
        "limits": ["No human review accepted here; use prepare_real_slice_review.py.",
                   "Online rows are historical snapshots, not freshly queried DB state.",
                   "Parser success does not certify source, answer correctness or knowledge mapping.",
                   "Unsupported verified proof questions can remain readable; they cannot yield machine-final-answer evidence."]}


def markdown(report):
    lines = ["# 真实题释放预检", "", "这是离线适用性检查，不是审核、题库写入或真实闭环通过。", "",
        f"工作单 SHA256：{report['worksheet_sha256']}", "",
        f"{report['count']} 道待核验题；{report['hypothetical_parser_applicable_count']} 道当前格式下假设核验后可被现有解析器识别；释放数 0。", "",
        "| 题目 | 当前未核验判定 | 假设核验后的解析器 | 结构草稿适用性（非批准） | 释放阻塞 |", "| --- | --- | --- | --- | --- |"]
    for q in report["questions"]:
        a = q["current_unverified_verdict"]
        b = q["hypothetical_parser_verdict_NOT_APPROVAL"]
        lines.append(f"| {q['candidate_id']} | {a['result']}/{a['reason']} | {b['result']}/{b['reason']} | {q['draft_structure_applicability_NOT_APPROVAL'] or '无'} | {', '.join(q['blockers'])} |")
    lines += ["", "## 审核队列（不是通过清单）", "",
        "来源/映射冲突优先于结构缺失，再优先于解析器或推导阻塞。可进入人工审核不表示来源许可、答案、映射或判题配置已核验。",
        "不支持机器判题的题可以在内容核验后用于阅读与辅助练习，但不能产生机器最终答案确认。", ""]
    for name, ids in report["review_queues"].items():
        lines.append(f"- {name}（{len(ids)}）：{', '.join(ids) or '无'}")
    lines += ["", f"候选批次共 {report['intake_count']} 道，工作单选入 {report['selected_intake_count']} 道；未选入不等于已通过或已否决。",
        f"未选入：{', '.join(report['not_selected_intake_ids']) or '无'}", "",
        "## 释放后才可执行的三种验收", "",
        "- A 薄弱调整：真实题作答产生证据后，第二轮工具读到新证据，方案符合目标、约束与真实题池；不强制换题。",
        "- B 解析后完成：Wrong → Solution Viewed → Correct 保留全部序列，不算首次独立正确；换题独立正确再增强证据。",
        "- C 同题记忆：重复正确不无限增加确认；有新题时检查是否合理验证迁移，并保留选择理由。", "",
        "本报告没有执行上述真实题/真实模型场景。来源、题干、答案、解析、映射、判题配置须先独立核验。"]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("worksheet", type=Path)
    parser.add_argument("--batch", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if not any(output.is_relative_to(ROOT / folder) for folder in ("storage/question-intake", "eval/reports")):
        parser.error("Keep diagnostic reports local")
    if output.exists() or output.with_suffix(".md").exists():
        parser.error("Refuse to overwrite reports")
    if any(p.stat().st_size > 16 * 1024 * 1024 for p in (args.worksheet, args.batch)):
        parser.error("Bounded input exceeded")
    result = audit(json.loads(args.worksheet.read_text(encoding="utf-8")), json.loads(args.batch.read_text(encoding="utf-8")))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    output.with_suffix(".md").write_text(markdown(result), encoding="utf-8")
    print(f"Preflight: {result['count']} UNVERIFIED rows; {result['hypothetical_parser_applicable_count']} hypothetical parser matches; released 0; DB untouched")


if __name__ == "__main__":
    main()
