"""Pinned 2026 paper-page intake: six images, transcription only, never retries.

Run default preparation and inspect the rendered pages BEFORE --live. Explicit
human authorization is required for the two papers' first three pages only.
Reports are unverified intake, not reviewed QuestionPack or grading evidence.
"""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SOURCES = {
    "math2": "数学/2026/数学二_2026_真题.pdf",
    "cs408": "408/2026/2026年计算机408统考真题_回忆版.pdf",
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("C:/Users/ZBT/Desktop/考研知识点"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    folder = args.output.resolve()
    manifest_path = folder / "pages.json"
    audit = json.loads((ROOT / "eval/reports/question-provenance-20261002/pdf-intake.json").read_text(encoding="utf-8"))
    pinned = {r["file"]: r["sha256"] for r in audit["records"]}
    for relative in SOURCES.values():
        if digest(args.root / relative) != pinned[relative]:
            parser.error("PDF changed since the approved intake audit; refuse to send")
    from backend.services.vision_recognition_service import normalized_image
    if not args.live:
        if manifest_path.exists():
            parser.error("Refuse to overwrite prepared manifest")
        folder.mkdir(parents=True, exist_ok=True)
        records = []
        for subject, relative in SOURCES.items():
            target = folder / subject
            target.mkdir(exist_ok=True)
            subprocess.run(["pdftoppm", "-f", "1", "-l", "3", "-r", "120", "-png",
                            str(args.root / relative), str(target / "page")], check=True)
            images = sorted(target.glob("page-*.png"), key=lambda p: int(p.stem.split("-")[-1]))
            if len(images) != 3:
                parser.error("Expected exactly three rendered pages per approved PDF")
            for page, image in enumerate(images, 1):
                normalized_image(image.read_bytes())
                records.append({"id": f"{subject}-page-{page}", "subject": subject, "page": page,
                    "source_file": relative, "source_sha256": pinned[relative],
                    "image": image.relative_to(folder).as_posix(), "image_sha256": digest(image)})
        manifest = {"version": "exam-2026-first-three-pages-v1", "max_calls": 6,
                    "status": "UNVERIFIED_TRANSCRIPTION", "records": records}
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        print("Prepared exactly six approved paper-page images; no model calls.")
        return
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = {f"{subject}-page-{page}" for subject in SOURCES for page in range(1, 4)}
    records = manifest["records"]
    if len(records) != 6 or {r["id"] for r in records} != expected or manifest.get("max_calls") != 6:
        parser.error("Only the six approved pages are allowed")
    images = {}
    for r in records:
        if (r["subject"] not in SOURCES or r["page"] not in (1, 2, 3)
                or r["id"] != f'{r["subject"]}-page-{r["page"]}'
                or r["source_file"] != SOURCES[r["subject"]]
                or r["source_sha256"] != pinned[r["source_file"]]):
            parser.error("Page identity changed")
        path = (folder / r["image"]).resolve()
        if not path.is_relative_to(folder) or digest(path) != r["image_sha256"]:
            parser.error("Prepared image changed or escaped output directory")
        images[r["id"]] = normalized_image(path.read_bytes())
    report_path = folder / "transcription.json"
    if report_path.exists():
        parser.error("Existing call ledger: refuse automatic rerun/resume")
    from backend.config import get_settings
    from backend.services.model_settings_service import load_local_settings
    from backend.services.vision_settings_service import effective_vision_settings
    from backend.services.vision_recognition_service import recognize_work, PROMPT_VERSION
    from backend.errors import AppError
    settings = load_local_settings(get_settings())
    effective = effective_vision_settings(settings)
    report = {"version": manifest["version"], "status": "UNVERIFIED_TRANSCRIPTION", "calls": 0,
        "automatic_retry": False, "model": effective.llm_model,
        "endpoint_host": urlsplit(effective.llm_base_url).hostname, "prompt_version": PROMPT_VERSION,
        "changes_learning_data": False, "source_note": "408文件标注回忆版，不认定为官方核验原卷",
        "records": [], "complete": False}

    def save():
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    async def run():
        save()
        for r in records:
            result = dict(r)
            report["records"].append(result)
            report["calls"] += 1
            save()  # Durable call ledger before sending; a killed run never auto-resumes.
            try:
                response = await recognize_work(settings, images[r["id"]])
                result.update(success=True, response=response.model_dump(mode="json"))
            except AppError as error:
                result.update(success=False, error_code=error.code)
            save()
            print(f'{r["id"]}: {"transcribed" if result["success"] else result["error_code"]}', flush=True)
        report["complete"] = True
        save()
    asyncio.run(run())


if __name__ == "__main__":
    main()
