"""Recover and qualify 2017 408 sorting questions 10 and 11.

Uses only the named isolated batch-16 clone; no developer database or paid
provider is used. Codex review receipts are bound to the imported content.
"""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import run_phase45hx_batch02 as batch

batch.SOURCE_RUN = ROOT / "storage/quality-audits/phase45hx-20261011/batch-16-final"
batch.OUT = ROOT / "storage/quality-audits/phase45hx-20261011/batch-17"
batch.PACK = ROOT / "storage/question-intake/phase45hx-20261011/phase45hx-408-2017-q10-q11-batch17-v1.json"
batch.PDF = Path("C:/Users/ZBT/Desktop/考研知识点/408/2017/2017年计算机408统考真题.pdf")
batch.PDF_SHA = "16f9c9afac663bc64e4057fe666d4563091349f71ba4113c26f58a66ea449883"
batch.EXPECTED_QUESTIONS = 2
batch.SOURCE_SUCCESS_STATUS = "BATCH_16_COMPLETE"
batch.PHASE_LABEL = "4.5H-X-batch-17"
batch.SUCCESS_STATUS = "BATCH_17_COMPLETE"
batch.TEST_FILES = [
    "tests/integration/test_auto_question_review.py",
    "tests/integration/test_question_pack_import.py",
    "tests/unit/test_phase45hx_recovery.py",
]
batch.TEST_ARGS = ["-k", "hash_bound_codex_review_can_replace_missing_solver"]

batch.CODEX_REVIEW_EVIDENCE = {
    "cs408-2017-q10": {
        "derived_answer": "B",
        "method_evidence": [
            {"method": "asymptotic-complexity-comparison", "result": "Merge sort runs in O(n log n); direct insertion is O(n^2) on average/worst case, so the runtime statement III is the only true reason."},
            {"method": "storage-and-implementation-comparison", "result": "Standard merge sort needs O(n) auxiliary storage, while insertion sort is in-place; recursive splitting/merging is not shorter code, so I and II are false."},
        ],
        "explanation_key_steps": [
            "Compare both algorithms' time bounds: only III favors merge sort for sufficiently large n.",
            "Compare auxiliary storage and implementation burden: merge sort uses more space and more steps, so I and II are false; exactly option B is true.",
        ],
        "option_truth_table": {"A": False, "B": True, "C": False, "D": False},
    },
    "cs408-2017-q11": {
        "derived_answer": "D",
        "method_evidence": [
            {"method": "access-pattern-analysis", "result": "Shell sort requires efficient gap-based indexed access and heap sort relies on array parent/child indexing; linked storage removes those constant-time accesses."},
            {"method": "algorithm-by-algorithm-list-feasibility", "result": "Insertion, selection and bubble sorting can be implemented with sequential scans and link/key updates at O(n^2); Shell and heap do not preserve their normal efficient access patterns."},
        ],
        "explanation_key_steps": [
            "Classify each algorithm by its access pattern: I, II and III can be implemented using linked traversal without changing their quadratic order.",
            "IV and V depend on gap/index or heap-index access; replacing the array with linked storage makes those accesses slower, so only option D is correct.",
        ],
        "option_truth_table": {"A": False, "B": False, "C": False, "D": True},
    },
}


if __name__ == "__main__":
    batch.main()
