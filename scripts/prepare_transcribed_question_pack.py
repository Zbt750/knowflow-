"""Prepare complete, visually compared source transcriptions, never verified grading.

Selections explicitly specify type/node/expected printed answer; do not infer
types from a universal year/number rule or invent a solution. Import is separate.
"""
import argparse
import json
from pathlib import Path
import re
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.services.question_pack import QuestionPack


def extract(candidate, selection):
    text = candidate["raw_transcription"]
    if "missing_choice_options" in candidate["issues"] or "last_page_boundary_requires_next_page" in candidate["issues"]:
        raise ValueError("Incomplete source question")
    marker = re.search(r"【答案】\s*([^\n]+)", text)
    if not marker:
        raise ValueError("Printed source answer is required; do not generate it")
    answer = marker.group(1).strip()
    body = text[:marker.start()].strip()
    body = re.sub(r"^\d{1,2}[.．、]\s*", "", body)
    options = None
    if selection["question_type"] == "single_choice":
        matches = list(re.finditer(r"(?m)^[ \t]*\(([A-D])\)[ \t]*", body))
        if [m.group(1) for m in matches] != list("ABCD"):
            raise ValueError("Four visually compared options required")
        options = {m.group(1): body[m.end():matches[i+1].start() if i+1 < len(matches) else len(body)].strip()
                   for i, m in enumerate(matches)}
        body = body[:matches[0].start()].strip()
        answer = answer.strip("()（） ")
    if answer != selection["printed_answer"]:
        raise ValueError("Printed answer changed; review instead of silently repairing")
    if not body or not selection.get("visual_comparison_complete"):
        raise ValueError("Explicit source-page comparison is required")
    return body, options, answer


def prepare(candidates, selections, review):
    # A previous source contradiction cannot disappear just because a later
    # selection omits its warning. Resolution needs a new, independently
    # compared source, not an answer guessed to fit the printed option.
    blocked = {(o["subject"], o.get("year", 2026), o["question_number"])
               for o in review.get("observations", [])}
    indexed = {(q["subject"], q["year"], q["question_number"]): q for q in candidates["questions"]}
    questions = []
    identities = set()
    for item in selections["questions"]:
        identity = (item["subject"], item["year"], item["question_number"])
        if identity in blocked:
            raise ValueError("Known source/review problem: independently compare a new source first")
        if not item.get("type_basis", "").strip() or not item.get("mapping_rationale", "").strip():
            raise ValueError("Explicit source type basis and primary-knowledge mapping rationale required")
        if identity in identities:
            raise ValueError("Duplicate selected source question")
        identities.add(identity)
        q = indexed[identity]
        if q["source_edition"] != item["edition"] or q["pages"] != item["pages"]:
            raise ValueError("Source edition/pages changed")
        stem, options, answer = extract(q, item)
        questions.append({"source_id": f'{item["subject"]}-{item["year"]}-q{item["question_number"]:03d}',
            "kp_code": item["kp_code"], "question_type": item["question_type"], "stem": stem,
            "options": options, "correct_answer": answer,
            "explanation": "原文件给出的参考答案：" + answer + "。原文件本页未提供完整逐步解析；答案待核验，本题不自动判分。",
            "estimated_minutes": item["estimated_minutes"], "skill_tags": item["skill_tags"],
            "question_role": "typical", "difficulty": "medium", "is_variant": False,
            "grading_method": None, "content_status": "source_transcribed", "answer_reviewed_by": None,
            "source": {"kind": "user_provided", "source_type": "exam", "year": item["year"],
                "question_number": item["question_number"], "paper_title": item["paper_title"],
                "subject": item["subject_label"], "edition": item["edition"],
                "citation": f'{q["source_file"]}，第{q["pages"]}页，SHA256:{q["source_sha256"]}',
                "rights_basis": "用户本地提供文件的个人学习转录；未确认公开再分发许可，不提交题干至公共仓库",
                "reviewed_by": "Codex原页逐字对照（非人工或官方认证）", "reviewed_on": selections["compared_on"]}})
    pack = QuestionPack.model_validate({"pack_id": selections["pack_id"], "version": "1", "questions": questions})
    return pack.model_dump(mode="json")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidates", type=Path)
    parser.add_argument("selection", type=Path)
    parser.add_argument("--review", type=Path, required=True, help="保留并检查之前发现的原稿/OCR问题")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Refuse to overwrite an existing source pack")
    pack = prepare(json.loads(args.candidates.read_text(encoding="utf-8")),
                   json.loads(args.selection.read_text(encoding="utf-8")),
                   json.loads(args.review.read_text(encoding="utf-8")))
    args.output.write_text(json.dumps(pack, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f'Prepared {len(pack["questions"])} transcribed practice questions; 0 verified automatic graders.')


if __name__ == "__main__":
    main()
