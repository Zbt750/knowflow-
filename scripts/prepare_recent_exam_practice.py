"""Prepare locally compared 2025/2026 transcripts, not verified exam answers.

Input text is local-only. Reference answer letters may be fetched from two
explicit sources; no private material or model request is sent. Import remains
a separate existing dry-run/apply transaction.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.services.question_pack import QuestionPack
from backend.services.exam_reference_service import build_exam_reference_seed

CS_URL = "https://raw.githubusercontent.com/Become-ILLUSORY/408-quiz/81329e467a29043f4357b439e22bc2930132fea1/questions.json"
MATH_URL = "https://raw.githubusercontent.com/lx-ruc/kaoyanshuxue/main/kaoyan_math_images/%E6%95%B0%E5%AD%A6%E4%BA%8C/answers.json"
BLOCKED = {("math2", 2026, 6), ("408", 2026, 3)}


def build(selection, sources, references):
    if selection.get("version") != "local-recent-exam-comparison-v1":
        raise ValueError("Unsupported comparison ledger")
    questions, seen = [], set()
    refs = {(r["subject"], r["year"], r["question_number"], r["knowledge_point_code"]) for r in references}
    for row in selection["questions"]:
        identity = (row["subject"], row["year"], row["number"])
        if row["subject"] not in {"math2", "408"} or row["year"] not in {2025, 2026}:
            raise ValueError("Only the requested two years and subjects are allowed")
        if identity in BLOCKED or identity in seen or row.get("comparison_complete") is not True:
            raise ValueError("Blocked, duplicate or uncompared question")
        seen.add(identity)
        if row.get("unresolved_issues") or not row.get("mapping_rationale"):
            raise ValueError("Unresolved source or mapping problem")
        label = "数学二" if row["subject"] == "math2" else "408"
        if (label, row["year"], row["number"], row["kp_code"]) not in refs:
            raise ValueError("Primary mapping must match an existing source pointer")
        paper = selection["papers"][f'{row["subject"]}-{row["year"]}']
        pages = [row["page"], *row.get("additional_pages", [])]
        if any(not isinstance(page, int) or page < 1 for page in pages) or not row.get("type_basis"):
            raise ValueError("Explicit page and question type basis required")
        if row["subject"] == "408":
            matches = [r for r in sources["408"]["rows"] if r["year"] == row["year"] and r["num"] == row["number"]]
            if len(matches) != 1:
                raise ValueError("Reference answer identity missing or duplicated")
            answer = matches[0].get("answer")
            answer_source = CS_URL
        elif row.get("printed_answer"):
            answer = row["printed_answer"]
            answer_source = "local PDF printed answer (unverified)"
        else:
            answer = sources["math2"]["rows"][f'数学二_{row["year"]}_Q{row["number"]:02d}']["answer"]
            answer_source = MATH_URL
        if answer not in row["options"] or set(row["options"]) != set("ABCD"):
            raise ValueError("Four complete options and a source answer letter required")
        questions.append({
            "source_id": f'{row["subject"]}-{row["year"]}-q{row["number"]:03d}',
            "kp_code": row["kp_code"], "question_type": "single_choice",
            "stem": row["stem"], "options": row["options"], "correct_answer": answer,
            "explanation": f"来源给出的参考答案：{answer}。答案来源：{answer_source}。题干已由 AI 对照本地原页转录；参考答案与解析尚未经过真人核验，不自动判分。",
            "estimated_minutes": row.get("minutes", 5), "skill_tags": [row["mapping_rationale"]],
            "question_role": "typical", "difficulty": "medium", "grading_method": None,
            "content_status": "source_transcribed", "answer_reviewed_by": None,
            "source": {"kind": "user_provided", "source_type": "exam", "year": row["year"],
                "question_number": row["number"], "paper_title": paper["title"], "subject": label,
                "edition": paper["edition"],
                "citation": f'{paper["relative_path"]}，PDF第{",".join(map(str, pages))}页，SHA256:{paper["sha256"]}',
                "rights_basis": "本项目已有本地试卷的个人学习转录；未确认公开再分发许可，题干仅本地保存，不进入公共仓库或发布包",
                "reviewed_by": "Codex AI 原页对照（非真人审核、非官方认证）",
                "reviewed_on": selection["compared_on"]},
        })
    return QuestionPack(pack_id="recent-local-exams-2025-2026-v1", version="1", questions=questions)


def download(url):
    import requests
    with requests.get(url, stream=True, timeout=(10, 35)) as response:
        response.raise_for_status()
        chunks, size = [], 0
        for chunk in response.iter_content(65536):
            size += len(chunk)
            if size > 12 * 1024 * 1024:
                raise ValueError("Reference response exceeds 12 MiB")
            chunks.append(chunk)
    raw = b"".join(chunks)
    return {"rows": json.loads(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("selection", type=Path)
    parser.add_argument("--paper-root", type=Path, default=Path("C:/Users/ZBT/Desktop/考研知识点"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / "storage/question-intake") or output.exists() or output.with_suffix(".sources.json").exists():
        parser.error("Use a new local ignored intake output; refuse overwrites")
    selection = json.loads(args.selection.read_text(encoding="utf-8"))
    for paper in selection["papers"].values():
        path = (args.paper_root / paper["relative_path"]).resolve()
        if not path.is_relative_to(args.paper_root.resolve()) or hashlib.sha256(path.read_bytes()).hexdigest() != paper["sha256"]:
            parser.error("Source paper changed or escaped paper directory")
    sources = {"408": download(CS_URL), "math2": download(MATH_URL)}
    pack = build(selection, sources, build_exam_reference_seed()[1])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(pack.model_dump_json(indent=2), encoding="utf-8")
    output.with_suffix(".sources.json").write_text(json.dumps({k: {"sha256": v["sha256"]} for k, v in sources.items()}, indent=2), encoding="utf-8")
    print(f"Prepared {len(pack.questions)} local transcripts, zero verified graders; database unchanged")


if __name__ == "__main__":
    main()
