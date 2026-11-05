"""Read-only desktop resource manifest. Does not copy private runtime files."""
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from desktop.resource_manifest import build_manifest

if __name__ == "__main__":
    print(json.dumps(build_manifest(ROOT), ensure_ascii=False, indent=2))
