"""Complete backup/restore verification for the fourth H-X batch."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import checkpoint_phase45hx_bank as checkpoint


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    checkpoint.RUN = ROOT / "storage/quality-audits/phase45hx-20261010/batch-14"
    checkpoint.OUT = checkpoint.RUN / "final-checkpoint"
    checkpoint.EXPECTED_STATUS = "BATCH_04_COMPLETE"
    raise SystemExit(checkpoint.main())
