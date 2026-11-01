"""Retry two correctly derived multiple-choice originals in a fresh clone."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import run_phase45hx_batch02 as batch
from scripts import run_phase45hx_batch22_originals as previous

batch.SOURCE_RUN = ROOT / "storage/quality-audits/phase45hx-20261011/batch-22-originals"
batch.OUT = ROOT / "storage/quality-audits/phase45hx-20261011/batch-23-originals-retry"
batch.PACK = None
batch.PDF = None
batch.EXPECTED_QUESTIONS = 0
batch.PROCESS_PACK = False
batch.SOURCE_SUCCESS_STATUS = "BATCH_22_ORIGINALS_COMPLETE"
batch.PHASE_LABEL = "4.5H-X-batch-23-originals-retry"
batch.SUCCESS_STATUS = "BATCH_23_ORIGINALS_RETRY_COMPLETE"
batch.TEST_FILES = ["tests/integration/test_auto_question_review.py"]
batch.TEST_ARGS = ["-k", "codex_public_original_review_qualifies_without_family_solver_and_excludes_personal_copy"]
batch.CODEX_PUBLIC_ORIGINALS = [
    {**spec, "derived_answer": answer}
    for spec, answer in zip(previous.batch.CODEX_PUBLIC_ORIGINALS[:2], ("A", "C"), strict=True)
]

if __name__ == "__main__":
    batch.main()
