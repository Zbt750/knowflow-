"""Retry the H-X public-original Today regression in a fresh isolated clone."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import run_phase45hx_batch02 as batch

batch.SOURCE_RUN = ROOT / "storage/quality-audits/phase45hx-20261011/batch-18-originals"
batch.OUT = ROOT / "storage/quality-audits/phase45hx-20261011/batch-19-e2e-retry"
batch.PACK = None
batch.PDF = None
batch.PROCESS_PACK = False
batch.CODEX_PUBLIC_ORIGINALS = []
batch.EXPECTED_QUESTIONS = 0
batch.SOURCE_SUCCESS_STATUS = "BATCH_18_ORIGINALS_COMPLETE"
batch.PHASE_LABEL = "4.5H-X-batch-19-e2e-retry"
batch.SUCCESS_STATUS = "BATCH_19_E2E_COMPLETE"
batch.TEST_FILES = ["tests/integration/test_auto_question_review.py"]
batch.TEST_ARGS = ["-k", "codex_public_original_review_qualifies_without_family_solver_and_excludes_personal_copy"]

if __name__ == "__main__":
    batch.main()
