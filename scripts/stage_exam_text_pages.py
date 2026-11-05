"""Stage local annual paper pages for source comparison, without model/DB calls.

Text-layer availability does not mean formulas, figures, question boundaries,
answers or the primary knowledge mapping have been verified. Never import these
files as Questions. Output belongs in an ignored local report/storage directory.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re

from pypdf import PdfReader


def stage(root, manifest, output):
    root = root.resolve()
    if output.exists():
        raise ValueError("Refuse to overwrite existing page evidence")
    checked = []
    for record in manifest["records"]:
        path = (root / record["file"]).resolve()
        if not path.is_relative_to(root) or path.suffix.lower() != ".pdf":
            raise ValueError("Source must be a PDF inside the explicit source root")
        if hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]:
            raise ValueError("Source changed since inventory; audit it again")
        checked.append((record, path))
    output.mkdir(parents=True)
    results = []
    for record, path in checked:
        reader = PdfReader(path)
        pages = []
        for number, page in enumerate(reader.pages, 1):
            text = page.extract_text() or ""
            glyphs = sum(c == "�" or "\ue000" <= c <= "\uf8ff" for c in text)
            pages.append({"page": number, "text": text,
                "suspicious_glyphs": glyphs,
                "question_number_clues": [int(m) for m in re.findall(r"(?m)^\s*(\d{1,2})\s*[.．、)]", text)],
                "status": "NEEDS_VISUAL_COMPARISON" if len(text.strip()) >= 30 and not glyphs
                          else "NEEDS_OCR_OR_MANUAL_COMPARISON",
                "question_type": None, "primary_kp_code": None, "can_import": False})
        relative = Path(record["subject"]) / str(record["year"]) / (record["sha256"][:16] + ".json")
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        evidence = {"version": "source-page-evidence-v1", "source_file": record["file"],
            "source_sha256": record["sha256"], "subject": record["subject"], "year": record["year"],
            "pages": pages, "verified": False, "online_questions_imported": 0,
            "claim": "题号线索不是独立题，代码/公式/插图必须对照原页；题型和主节点不能按题号猜测。"}
        destination.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
        results.append({"file": record["file"], "evidence": relative.as_posix(),
            "pages": len(pages), "comparison_pages": sum(p["status"] == "NEEDS_VISUAL_COMPARISON" for p in pages),
            "ocr_or_manual_pages": sum(p["status"] == "NEEDS_OCR_OR_MANUAL_COMPARISON" for p in pages)})
    summary = {"version": "annual-source-page-intake-v1", "files": len(results),
        "pages": sum(r["pages"] for r in results),
        "ocr_or_manual_pages": sum(r["ocr_or_manual_pages"] for r in results),
        "online_questions_imported": 0, "records": results}
    (output / "manifest.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = stage(args.root, json.loads(args.manifest.read_text(encoding="utf-8")), args.output)
    print(json.dumps({k: v for k, v in result.items() if k != "records"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
