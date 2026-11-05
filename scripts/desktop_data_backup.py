"""Stopped, owned desktop data backup/inspect/restore; no live developer DB."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from desktop.backup import create_backup, inspect_backup, restore_backup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create")
    create.add_argument("--data", type=Path, required=True)
    create.add_argument("--archive", type=Path, required=True)
    create.add_argument("--pg-bin", type=Path, required=True)
    inspect = commands.add_parser("inspect")
    inspect.add_argument("--archive", type=Path, required=True)
    restore = commands.add_parser("restore")
    restore.add_argument("--archive", type=Path, required=True)
    restore.add_argument("--data", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "create":
            result = create_backup(args.data, args.archive, pg_bin=args.pg_bin)
        elif args.command == "restore":
            result = restore_backup(args.archive, args.data)
        else:
            manifest = inspect_backup(args.archive)
            # Do not log uploaded filenames or filesystem paths by default.
            result = {"format": manifest["format"], "files": len(manifest["files"]),
                      "encrypted": False, "same_path_and_windows_account_required": True}
        print(json.dumps(result))
        return 0
    except Exception as exc:
        category = str(exc)
        if not category.startswith("desktop_") or " " in category:
            category = "desktop_backup_failed"
        print(category, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
