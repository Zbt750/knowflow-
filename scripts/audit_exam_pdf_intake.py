"""Read-only annual PDF intake audit; no OCR, answer extraction or redistribution."""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

from pypdf import PdfReader


def inspect_pdf(path: Path):
    if path.stat().st_size > 64 * 1024 * 1024:
        return {"status": "size_limit"}
    try:
        reader = PdfReader(path)
        if reader.is_encrypted:
            return {"status": "encrypted"}
        if len(reader.pages) > 100:
            return {"status": "page_limit", "pages": len(reader.pages)}
        texts, sparse_pages = [], []
        for index, page in enumerate(reader.pages, 1):
            text = page.extract_text() or ""
            if len(text.strip()) < 30:
                sparse_pages.append(index)
            texts.append(text)
            if sum(map(len, texts)) > 200000:
                return {"status": "text_limit"}
        text = "\n".join(texts)
        return {"status": "text_candidate" if len(text.strip()) >= 200 else "needs_ocr_or_manual",
                "pages": len(reader.pages), "text_chars": len(text), "sparse_text_pages": sparse_pages,
                "possible_question_markers": len(re.findall(r"(?m)^\s*\d{1,2}\s*[.．、)]", text)),
                "answer_section_indicator": bool(re.search(r"参考答案|答案解析|试题解析|【答案】", text)),
                "suspicious_glyphs": sum(c == "�" or "\ue000" <= c <= "\uf8ff" for c in text),
                "ready_for_auto_grading": False}
    except Exception as exc:
        return {"status": "read_error", "error_type": type(exc).__name__}


def audit(root: Path, *, first_year=2010, last_year=2026):
    records, missing = [], []
    for subject in ("数学", "408"):
        for year in range(first_year, last_year + 1):
            folder = root / subject / str(year)
            files = sorted(folder.glob("*.pdf"))
            if not files:
                missing.append(f"{subject}/{year}")
            for path in files:
                result = inspect_pdf(path)
                digest = hashlib.sha256()
                with path.open("rb") as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b""): digest.update(block)
                records.append({"subject": subject, "year": year, "file": path.relative_to(root).as_posix(),
                                "sha256": digest.hexdigest(), **result})
    return {"scope": "pdf_intake_not_question_verification", "files": len(records),
            "missing_annual_pdf_folders": missing,
            "status_counts": dict(Counter(row["status"] for row in records)), "records": records,
            "rights_review_required": True, "claim": "文字层/题号线索不证明题干、公式、图示或答案完整正确"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not args.root.is_dir(): parser.error("input folder does not exist")
    result = audit(args.root)
    if args.output:
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({key: value for key, value in result.items() if key != "records"}, ensure_ascii=False))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
