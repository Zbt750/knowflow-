"""Interactive local six-aspect human review. No apply command or DB writes."""
from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import text
from backend.config import get_settings
from backend.db import create_db_engine, create_session_factory
from backend.services.golden_review_session import (
    DEFAULT_IDS, ORDER, ISSUES, read_json, material_index, load_views, new_draft,
    configure, record_review, export_bundle, private_directory, save_revision, restore, grader_probes,
)
from backend.services.question_pack import QuestionPack
from backend.services.question_verification_upgrade import build_targets


def fingerprints(db):
    """All public row data, including historical evidence and verification pointers."""
    tables = db.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")).scalars().all()
    quote = db.bind.dialect.identifier_preparer.quote
    result = {}
    for table in tables:
        sql = f"SELECT count(*), md5(coalesce(string_agg(md5(to_jsonb(t)::text), '' ORDER BY md5(to_jsonb(t)::text)), '')) FROM public.{quote(table)} t"
        count, sha = db.execute(text(sql)).one()
        result[table] = {"count": count, "rows_md5": sha}
    return result


def read_live(ids, materials, *, audit=False, approved_pack=None):
    engine = create_db_engine(str(get_settings().active_database_url))
    try:
        with create_session_factory(engine)() as db:
            db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
            views = load_views(db, ids, materials)
            info = {"database": db.scalar(text("SELECT current_database()")),
                    "revision": db.scalar(text("SELECT version_num FROM alembic_version")),
                    "transaction_read_only": db.scalar(text("SHOW transaction_read_only"))}
            if audit:
                info["fingerprints"] = fingerprints(db)
            targets = build_targets(db, approved_pack) if approved_pack else None
            db.rollback()
            return views, info, targets
    finally:
        engine.dispose()


def show_question(row, emit=print):
    view = row["view"]
    c, src, node = view["content"], view["source"], view["node"]
    emit(f"\n{src.get('year')} {src.get('subject')} Q{src.get('question_number')} | {view['question_id']}")
    emit("题干：\n" + c["stem"])
    for option, value in (c["options"] or {}).items():
        emit(f"  {option}: {value}")
    emit("当前答案（待人工核验）：" + c["correct_answer"])
    emit("当前解析：\n" + c["explanation"])
    emit(f"知识节点：{node['name']} ({node['code']})；skills：{', '.join(c['skill_tags'])}")
    emit("来源说明：" + str(src.get("citation", "")))
    emit("权限/使用范围：" + str(src.get("rights_basis", "")))
    emit("对照文件：" + str(view["source_file"].get("path")))
    emit("审核定位：" + str(view["material"].get("locator")))
    emit("来源文件检查：" + json.dumps(view["source_file"], ensure_ascii=False))
    for label, key in (("Question content SHA", "question_content_sha256"),
                       ("Answer version SHA", "answer_version_sha256"),
                       ("Live snapshot SHA", "snapshot_sha256")):
        emit(f"{label}: {view[key]}")
    emit("机器记录（不等于人工审核）：" + json.dumps(view["eligibility"], ensure_ascii=False))
    emit("硬阻断项：" + (", ".join(view["hard_blockers"]) or "无"))
    for issue, resolution in row["resolutions"].items():
        emit(f"待审核事项 {issue}: {resolution or 'PENDING'}")
    if row["proposal"]:
        proposal = row["proposal"]
        emit(f"未签核候选：{proposal['answer_reviewed_by']} / {proposal['answer_reviewed_on']} / {proposal['grading_method']}")
        emit("候选来源：" + proposal["source"]["citation"])
        emit("候选内容 fingerprint：" + row["proposal_sha256"])
    for aspect in ORDER:
        r = row["reviews"][aspect]
        emit(f"{aspect}: {r['status']} | {r.get('note', '')}")
    if row["probes"]:
        emit("真实判题器测试（仅测试配置，不授予 verified grader）：")
        for probe in row["probes"]["cases"]:
            value = probe["selected_option"] if probe["selected_option"] is not None else probe["raw_answer"]
            emit(f"  {probe['case']} 输入={value!r} 期望={probe['expected']} 实际={probe['actual']} [{probe['reason']}]")


def summary(draft, emit=print):
    for i, row in enumerate(draft["questions"], 1):
        source, view = row["view"]["source"], row["view"]
        emit(f"{i}. {source.get('year')} {source.get('subject')} Q{source.get('question_number')} {view['question_id']}")
        emit("   " + " / ".join(f"{a}={row['reviews'][a]['status']}" for a in ORDER))


def interactive(draft, save, input_fn=input, emit=print):
    """Only explicit typed VERIFIED sets an individual approval; Enter skips."""
    emit("这是本地人工审核草稿。机器检查不会签核题目，草稿也不会修改数据库。")
    while True:
        summary(draft, emit)
        choice = input_fn("选择题目编号；s 保存，q 保存并退出，e 导出已完成的整个审核批次：").strip().lower()
        if choice in {"q", "s", "e"}:
            save(draft)
            if choice == "q":
                return "quit"
            if choice == "e":
                return "export"
            continue
        if not choice.isdigit() or not 1 <= int(choice) <= len(draft["questions"]):
            emit("请选择实际题目编号。")
            continue
        row = draft["questions"][int(choice) - 1]
        show_question(row, emit)
        while True:
            command = input_fn("p 准备候选配置；1 source / 2 stem / 3 answer / 4 explanation / 5 mapping / 6 grading；v 查看；b 返回：").strip().lower()
            try:
                if command == "b":
                    break
                if command == "v":
                    show_question(row, emit)
                    continue
                if command == "p":
                    reviewer = input_fn("真实审核者身份（必须亲自填写）：").strip()
                    source = row["view"]["source"]
                    emit("当前来源说明：" + str(source.get("citation", "")))
                    citation = input_fn("候选来源说明/精确页码（Enter 保留当前说明，不代表签核）：").strip() or source.get("citation", "")
                    emit("当前权限说明：" + str(source.get("rights_basis", "")))
                    rights = input_fn("候选权限及本地使用范围说明（Enter 保留）：").strip() or source.get("rights_basis", "")
                    note = input_fn("独立求解的答案审核说明（至少5字；稍后 answer 签核须引用同一说明）：").strip()
                    method = input_fn("候选判题方法（必须输入 single_choice 或 numeric_final）：").strip()
                    sha = configure(row, reviewer=reviewer, citation=citation, rights_basis=rights,
                                    answer_note=note, method=method)
                    emit(f"已冻结未签核候选，日期 {date.today().isoformat()}，SHA {sha}；配置变化会清除旧签核。")
                    emit(json.dumps(row["probes"], ensure_ascii=False, indent=2))
                    save(draft)
                    continue
                if not command.isdigit() or not 1 <= int(command) <= 6:
                    emit("请选择一个审核维度。")
                    continue
                aspect = ORDER[int(command) - 1]
                emit(f"当前 {aspect}：{row['reviews'][aspect]['status']}")
                if aspect == "answer" and row["proposal"]:
                    emit("已冻结答案说明：" + row["proposal"]["answer_review_note"])
                status = input_fn("亲自输入 VERIFIED / REJECTED / PENDING；Enter 只跳过：").strip().upper()
                if not status:
                    continue
                note = input_fn("该项审核说明（answer 可明确输入 = 引用上面已填写说明）：").strip()
                if note == "=" and aspect == "answer" and row["proposal"]:
                    note = row["proposal"]["answer_review_note"]
                record_review(row, aspect, status, note)
                # Save the decision immediately even if later issue entry is interrupted.
                save(draft)
                if status == "VERIFIED":
                    issues = list(ISSUES[aspect])
                    if aspect == "source":
                        issues += [i for i in row["view"]["issues"] if i not in {v for values in ISSUES.values() for v in values}]
                    for issue in issues:
                        emit(f"待解决事项 {issue}；现有说明：{row['resolutions'][issue] or '未解决'}")
                        resolution = input_fn("输入具体解决依据（至少5字；Enter 保留原值/未解决）：").strip()
                        if resolution:
                            if len(resolution) < 5:
                                raise ValueError("解决说明至少5字；该事项仍未解决")
                            row["resolutions"][issue] = resolution
                            save(draft)
                show_question(row, emit)
            except (ValueError, KeyError) as error:
                emit("未通过：" + str(error))


def write_bundle(bundle, directory):
    # Every export creates a new directory. Prior drafts/decisions are retained.
    out = directory / ("bundle-" + uuid4().hex)
    out.mkdir(parents=True, exist_ok=False)
    for name in ("batch", "decisions", "targets", "pack"):
        with (out / f"{name}.json").open("x", encoding="utf-8") as stream:
            json.dump(bundle[name], stream, ensure_ascii=False, indent=2)
    with (out / "manifest.json").open("x", encoding="utf-8") as stream:
        json.dump({"status": "READY_FOR_UPGRADE_PREVIEW", "database_written": False,
                   "official_upgrade_preview_executed": False}, stream, indent=2)
    return out


def main(argv=None):
    # Windows redirected output may default to GBK, which cannot print several
    # exam symbols. Use UTF-8 for reports/console pipes instead of crashing.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--question-id", action="append", help="Repeat to choose a custom review batch")
    parser.add_argument("--resume", type=Path)
    parser.add_argument("--export", action="store_true", help="Export only a fully completed real human draft; requires --resume")
    parser.add_argument("--inspect", action="store_true", help="Read and display live questions; no review decisions")
    parser.add_argument("--report", type=Path, help="Private read-only inspection/fingerprint report; requires --inspect")
    parser.add_argument("--materials", type=Path, default=ROOT / "storage/answer-trust/phase45a3-20261008/human-review-package.json")
    parser.add_argument("--corrected-material", type=Path, default=ROOT / "storage/answer-trust/phase45a3-20261008/human-review-q6-corrected-v2.json")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "storage/answer-trust/human-review")
    args = parser.parse_args(argv)
    if args.export and not args.resume or args.report and not args.inspect:
        parser.error("--export requires --resume; --report requires --inspect")
    directory = private_directory(args.output_dir, ROOT)
    materials = material_index(read_json(args.materials) if args.materials.is_file() else None,
                               read_json(args.corrected_material) if args.corrected_material.is_file() else None)
    if args.resume:
        private_directory(args.resume.parent, ROOT)
        saved = read_json(args.resume)
        ids = [q["view"]["question_id"] for q in saved["draft"]["questions"]]
        if args.question_id and args.question_id != ids:
            raise ValueError("--question-id differs from resumed draft")
    else:
        ids = args.question_id or DEFAULT_IDS
    views, info, _ = read_live(ids, materials, audit=bool(args.report))
    draft = restore(args.resume, views, ROOT) if args.resume else new_draft(views)
    print(json.dumps({k: v for k, v in info.items() if k != "fingerprints"}, ensure_ascii=False, indent=2))
    if args.inspect:
        for row in draft["questions"]:
            kind = row["view"]["content"]["question_type"]
            method = "single_choice" if kind == "single_choice" else "numeric_final" if kind in {"fill_blank", "calculation"} else None
            if method:
                row["probes"] = grader_probes(row["view"], method)
            show_question(row)
        if args.report:
            private_directory(args.report.parent, ROOT)
            _, after, _ = read_live(ids, materials, audit=True)
            report = {"status": "INSPECTION_ONLY", "database_written": False,
                      "before": info, "after": after,
                      "fingerprints_unchanged": info["fingerprints"] == after["fingerprints"],
                      "questions": views, "human_review_confirmed": False,
                      "grader_probes": {r["view"]["question_id"]: r["probes"] for r in draft["questions"]}}
            args.report.parent.mkdir(parents=True, exist_ok=True)
            with args.report.open("x", encoding="utf-8") as stream:
                json.dump(report, stream, ensure_ascii=False, indent=2)
        return 0
    def save(value):
        path = save_revision(value, directory, ROOT)
        print("已保存新草稿版本（保留所有旧文件）：" + str(path))
    action = "export" if args.export else interactive(draft, save)
    if action == "export":
        current, _, _ = read_live(ids, materials)
        bundle = export_bundle(draft, current)
        # Existing read-only target resolver must agree before emitting a bundle.
        current, _, targets = read_live(ids, materials, approved_pack=QuestionPack.model_validate(bundle["pack"]))
        bundle = export_bundle(draft, current)
        if targets != bundle["targets"]:
            raise ValueError("Unique live target resolution differs from signed snapshot")
        print("已导出：" + str(write_bundle(bundle, directory)))
        print("未运行正式 upgrade preview/apply；请先检查导出材料。")
    summary(draft)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, KeyError, OSError) as error:
        print("审核停止：" + str(error), file=sys.stderr)
        raise SystemExit(2)
    except (KeyboardInterrupt, EOFError):
        print("审核已退出；已保存的历史草稿保留。", file=sys.stderr)
        raise SystemExit(2)
