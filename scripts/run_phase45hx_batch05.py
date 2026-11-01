"""Batch 05: recover four exact 2017 408 candidate identities in an owned clone."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import run_phase45hx_batch02 as batch

batch.SOURCE_RUN = ROOT / "storage/quality-audits/phase45hx-20261010/batch-14"
batch.OUT = ROOT / "storage/quality-audits/phase45hx-20261011/batch-15b"
batch.PACK = ROOT / "storage/question-intake/phase45hx-20261011/phase45hx-408-2017-q04-q05-q13-v1.json"
batch.PDF = Path("C:/Users/ZBT/Desktop/考研知识点/408/2017/2017年计算机408统考真题.pdf")
batch.PDF_SHA = "16f9c9afac663bc64e4057fe666d4563091349f71ba4113c26f58a66ea449883"
batch.EXPECTED_QUESTIONS = 3
batch.SOURCE_SUCCESS_STATUS = "BATCH_04_COMPLETE"
batch.PHASE_LABEL = "4.5H-X-batch-05"
batch.SUCCESS_STATUS = "BATCH_05_COMPLETE"
batch.TEST_FILES = [
    "tests/unit/test_phase45hx_exam_verifiers.py",
    "tests/integration/test_question_pack_import.py",
    "tests/integration/test_auto_question_review.py",
]


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(batch.main())
