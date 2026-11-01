"""Recover 2016 Math II Q1-Q3 from the preserved batch-02 isolated checkpoint."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import run_phase45hx_batch02 as batch


def main():
    batch.SOURCE_RUN = ROOT / "storage/quality-audits/phase45hx-20261010/batch-12"
    batch.OUT = ROOT / "storage/quality-audits/phase45hx-20261010/batch-13"
    batch.PACK = ROOT / "storage/question-intake/phase45hx-20261010/phase45hx-math2-2016-v1.json"
    batch.PDF = Path("C:/Users/ZBT/Desktop/考研知识点/数学/2016/2016年数学二真题及解析_公开仓库版.pdf")
    batch.PDF_SHA = "356c4639aef59aeed9e0f395dd5500b5375ff4dae8e45b70d88b252ca65c9af1"
    batch.EXPECTED_QUESTIONS = 3
    batch.SOURCE_SUCCESS_STATUS = "BATCH_02_COMPLETE"
    batch.PHASE_LABEL = "4.5H-X-batch-03"
    batch.SUCCESS_STATUS = "BATCH_03_COMPLETE"
    return batch.main()


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
