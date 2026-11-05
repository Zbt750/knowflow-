"""Restore-verify the immutable isolated checkpoint produced by H-X batch 05."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import checkpoint_phase45hx_bank as checkpoint

checkpoint.RUN = ROOT / "storage/quality-audits/phase45hx-20261011/batch-15b"
checkpoint.OUT = checkpoint.RUN / "final-checkpoint"
checkpoint.EXPECTED_STATUS = "BATCH_05_COMPLETE"


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(checkpoint.main())
