"""Read-only progress and restore verification after original batch 08."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import phase45z5_progress_checkpoint_batch05 as prior  # noqa: E402

BASE = ROOT / "storage/quality-audits/phase45z5-20261013"
CHECKPOINT = BASE / "originals/batch08/checkpoint.json"
BACKUP = BASE / "originals/batch08/post-batch08.dump"
OUT = BASE / "progress-after-batch08.json"
prior.DATABASES = (
    ("phase45z5_work_20261013_test", "postgresql+psycopg://postgres@127.0.0.1:59227/phase45z5_work_20261013_test"),
    ("phase45z5_batch08_restore_20261013_test", "postgresql+psycopg://postgres@127.0.0.1:59227/phase45z5_batch08_restore_20261013_test"),
)


def main() -> None:
    if OUT.exists():
        raise SystemExit(f"refusing_to_overwrite:{OUT}")
    if not CHECKPOINT.is_file() or not BACKUP.is_file():
        raise SystemExit("batch08_checkpoint_or_backup_missing")
    batch = json.loads(CHECKPOINT.read_text(encoding="utf-8"))
    if batch.get("status") != "BATCH08_APPLIED" or batch.get("rejected"):
        raise SystemExit("batch08_not_cleanly_applied")
    current, _, current_tables = prior.inspect_database(*prior.DATABASES[0])
    _, _, restored_tables = prior.inspect_database(*prior.DATABASES[1])
    if current_tables != restored_tables:
        mismatches = {name: {"current": current_tables.get(name), "restored": restored_tables.get(name)}
                      for name in sorted(set(current_tables) | set(restored_tables))
                      if current_tables.get(name) != restored_tables.get(name)}
        raise RuntimeError("batch08_independent_restore_mismatch:" +
                           json.dumps(mismatches, ensure_ascii=False, sort_keys=True))
    accepted = {row["question_id"] for row in batch["accepted"]}
    if len(accepted) != len(batch["accepted"]):
        raise RuntimeError("batch08_duplicate_question_ids")
    current["status"] = "PHASE45Z5_IN_PROGRESS_RESTORE_VERIFIED"
    current["latest_batch"] = {
        "batch_id": "08", "candidates": len(batch["accepted"]) + len(batch.get("rejected", [])),
        "accepted": len(accepted), "new_graduation_set_publications": len(batch.get("publications", [])),
        "paid_model_calls": batch.get("paid_model_calls", 0),
    }
    current["independent_restore"] = {
        "database": prior.DATABASES[1][0], "full_public_table_count": len(current_tables),
        "all_table_fingerprints_match": True, "backup_path": str(BACKUP),
        "backup_sha256": hashlib.sha256(BACKUP.read_bytes()).hexdigest().upper(),
    }
    current["shortfall_to_2000"] = max(0, 2000 - current["formal_questions"])
    current["deployment_ready"] = False
    OUT.write_text(json.dumps(current, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({key: current[key] for key in (
        "status", "question_records", "formal_questions", "formal_subjects", "formal_sources",
        "formal_nodes", "graduation_set_count", "latest_batch", "shortfall_to_2000",
        "sample_candidates_pending", "protected_history", "independent_restore",
    )}, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
