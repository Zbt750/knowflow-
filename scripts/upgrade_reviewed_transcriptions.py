"""Six-aspect review bridge + explicit snapshot-bound transcription upgrade.

Default is preview; --apply is never inferred. No public endpoint or AI approval.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.config import get_settings
from backend.db import create_db_engine, create_session_factory
from backend.services.question_verification_upgrade import build_targets, upgrade_transcriptions
from scripts.prepare_real_slice_review import prepare


def local_output(path):
    resolved = path.resolve()
    if not any(resolved.is_relative_to(ROOT / folder) for folder in ("storage/question-intake", "eval/reports")):
        raise ValueError("Keep review/upgrade artifacts in ignored local directories")
    if resolved.exists():
        raise ValueError("Refuse to overwrite previous upgrade artifact")
    return resolved


def read_json(path):
    if path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("Input exceeds 16 MiB")
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("batch", type=Path)
    parser.add_argument("--decisions", type=Path, required=True)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--targets", type=Path)
    choice.add_argument("--snapshot-only", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.apply and args.snapshot_only:
        parser.error("Snapshot creation cannot apply changes")
    output = local_output(args.output)
    batch, decisions = read_json(args.batch), read_json(args.decisions)
    pack = prepare(batch, decisions)  # All original issues + six human review hashes.
    reviews = {r["candidate_id"]: r["reviews"] for r in decisions["questions"]}
    engine = create_db_engine(str(get_settings().active_database_url))
    try:
        with create_session_factory(engine)() as db:
            result = build_targets(db, pack) if args.snapshot_only else upgrade_transcriptions(
                db, pack, read_json(args.targets), reviews, apply=args.apply)
            # Serialize and reserve the artifact BEFORE commit. A failed commit
            # leaves a clearly marked intent report, never a false success report.
            output.parent.mkdir(parents=True, exist_ok=True)
            with output.open("x", encoding="utf-8") as stream:
                json.dump({"status": "prepared_outcome_not_confirmed", "result": result}, stream, ensure_ascii=False, indent=2)
            if args.apply:
                db.commit()
            else:
                db.rollback()
            # Snapshot files remain directly consumable as targets; reports are
            # final only after a successful commit/rollback.
            output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            print("Applied explicit reviewed upgrade; history not regraded." if args.apply
                  else "Read-only snapshot/preview complete; database unchanged.")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
