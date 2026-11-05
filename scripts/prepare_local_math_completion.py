"""Build an offline AI-derived practice supplement from explicitly compared local rows."""
import hashlib
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.services.exam_reference_service import build_exam_reference_seed
from backend.services.question_pack import QuestionPack


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-pdf", type=Path, required=True, help="由使用者提供的数学二2025原卷，不随仓库分发")
    parser.add_argument("--intake-dir", type=Path, required=True, help="本地题包和已对照行所在目录，必须在storage/question-intake内")
    args = parser.parse_args()
    allowed_root = Path(__file__).resolve().parents[1] / "storage/question-intake"
    root = args.intake_dir.resolve()
    if not root.is_relative_to(allowed_root.resolve()):
        parser.error("Use an ignored storage/question-intake directory")
    base = QuestionPack.model_validate_json((root / "practice-pack-v1.json").read_text(encoding="utf-8"))
    if not base.questions:
        raise ValueError("Source pack is empty")
    source = base.questions[0].source.model_dump(mode="json")
    path = args.source_pdf.resolve()
    if hashlib.sha256(path.read_bytes()).hexdigest() not in source["citation"]:
        raise ValueError("Local source changed")
    refs = [r for r in build_exam_reference_seed()[1] if r["subject"] == "数学二" and r["year"] == 2025
            and r["knowledge_point_code"].startswith("math.exam.")]
    questions = []
    for row in json.loads((root / "math2025-completion.json").read_text(encoding="utf-8")):
        matches = [r for r in refs if r["question_number"] == row["number"]]
        if len(matches) != 1:
            raise ValueError("Question mapping requires explicit review")
        ref = matches[0]
        pages = [row["page"], *row.get("additional_pages", [])]
        provenance = dict(source)
        provenance["question_number"] = row["number"]
        provenance["citation"] = f"数学/2025/2025年数学二真题.pdf，PDF第{pages}页，SHA256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        questions.append({"source_id": f"math2-2025-q{row['number']:03}", "kp_code": ref["knowledge_point_code"],
                          "question_type": row["type"], "stem": row["stem"], "options": row.get("options"),
                          "correct_answer": row["answer"], "explanation": "## 参考答案\n" + row["answer"] + "\n\n## 解题过程\n" + row["explanation"] + "\n\n说明：AI 独立推导，未经真人核验，不作为客观毕业确认。",
                          "estimated_minutes": 5 if row["type"] in ("single_choice", "fill_blank") else 15,
                          "skill_tags": [ref["topic_label"]], "question_role": "typical", "difficulty": "medium",
                          "source": provenance, "content_status": "source_transcribed"})
    pack = QuestionPack(pack_id="local-math2-2025-completion-v1", version="1", questions=questions)
    output = root / "math2025-completion-pack-v1.json"
    if output.exists():
        raise ValueError("Refuse overwriting an existing prepared pack")
    output.write_text(pack.model_dump_json(indent=2), encoding="utf-8")
    print(f"Prepared {len(questions)} full local questions; no model calls; no verified upgrades")


if __name__ == "__main__":
    main()
