"""Split an existing OCR ledger into UNVERIFIED candidates, without model calls."""
import argparse
import json
from pathlib import Path
import re


def build(report):
    candidates = []
    for subject in ("math2", "cs408"):
        pages = sorted((r for r in report["records"] if r["subject"] == subject and r.get("success")), key=lambda r: r["page"])
        text, ranges = "", []
        for page in pages:
            start = len(text)
            text += page["response"]["text"] + "\n"
            ranges.append((start, len(text), page))
        markers = list(re.finditer(r"(?m)^\s*(\d{1,2})[.．、]\s*", text))
        for index, match in enumerate(markers):
            end = markers[index + 1].start() if index + 1 < len(markers) else len(text)
            raw = text[match.start():end].strip()
            number = int(match.group(1))
            source_pages = [p for start, stop, p in ranges if start < end and stop > match.start()]
            is_choice = subject == "cs408" or number <= 10
            options = sorted(set(re.findall(r"(?:\(([A-D])\)|\b([A-D])[.．])", raw)))
            option_letters = sorted({a or b for a, b in options})
            issues = ["needs_visual_comparison", "knowledge_mapping_not_reviewed", "answer_not_reviewed"]
            if is_choice and option_letters != list("ABCD"):
                issues.append("missing_choice_options")
            if not re.search(r"【答案】", raw):
                issues.append("source_answer_not_present_in_transcription")
            if subject == "cs408" and index == len(markers) - 1:
                issues.append("last_page_boundary_requires_next_page")
            candidates.append({"subject": subject, "year": 2026, "source_type": "exam",
                "source_edition": "回忆版" if subject == "cs408" else "第三方汇编",
                "question_number": number, "status": "UNVERIFIED_TRANSCRIPTION",
                "raw_transcription": raw, "option_letters_detected": option_letters,
                "pages": [p["page"] for p in source_pages], "source_file": source_pages[0]["source_file"],
                "source_sha256": source_pages[0]["source_sha256"], "issues": issues,
                "can_import": False, "verified": False})
    return {"version": "exam-transcription-candidates-v1", "questions": candidates,
        "candidate_count": len(candidates), "online_questions_imported": 0,
        "claim": "Question-number splitting is not transcription, answer or mapping verification."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Refuse to overwrite existing candidate evidence")
    result = build(json.loads(args.report.read_text(encoding="utf-8")))
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "questions"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
