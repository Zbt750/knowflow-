"""Create a private recoverable working-source archive, without changing Git.

Includes only audited tracked/unignored files; excludes Git history, credentials,
runtime data, model files and ignored assets. Never restores over a checkout.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.audit_repository_checkpoint import audit


def create_checkpoint(root, output, *, auditor=audit):
    root, output = root.resolve(), output.resolve()
    allowed = (root / "storage/backups").resolve()
    if output == allowed or not output.is_relative_to(allowed) or output.exists():
        raise ValueError("Use a new private storage/backups directory")
    inventory = auditor(root)
    if inventory["issues"] or inventory["missing_workspace_files"]:
        raise ValueError("Resolve inventory risks before creating source checkpoint")
    output.mkdir(parents=True)
    archive_path = output / "source-workspace.zip"
    rows = inventory["manifest"]
    with zipfile.ZipFile(archive_path, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for row in rows:
            path = root / row["path"]
            if path.is_symlink() or not path.resolve().is_relative_to(root):
                raise ValueError("Source links are not supported")
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() != row["sha256"]:
                raise ValueError("Workspace changed after inventory; incomplete archive retained")
            archive.writestr(row["path"], data)
    with zipfile.ZipFile(archive_path) as archive:
        if sorted(archive.namelist()) != sorted(row["path"] for row in rows):
            raise ValueError("Archive entries differ from inventory")
        for row in rows:
            if hashlib.sha256(archive.read(row["path"])).hexdigest() != row["sha256"]:
                raise ValueError("Archive content hash mismatch")
    record = {"version": "source-workspace-checkpoint-v1", "inventory": inventory,
              "archive_sha256": hashlib.sha256(archive_path.read_bytes()).hexdigest(),
              "archive_verified": True, "git_modified": False, "restore_executed": False,
              "limitations": ["not_git_history", "ignored_private_data_excluded", "not_a_release_tag",
                              "not_clean_install_verified", "heuristic_inventory_not_exhaustive"]}
    with (output / "source-manifest.json").open("x", encoding="utf-8") as stream:
        json.dump(record, stream, ensure_ascii=False, indent=2)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    record = create_checkpoint(ROOT, args.output)
    print(json.dumps({"source_files": len(record["inventory"]["manifest"]),
                      "archive_verified": True, "git_modified": False, "restore_executed": False}))


if __name__ == "__main__":
    main()
