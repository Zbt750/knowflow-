"""Build an explicit source-resource manifest, not a distributable installer."""
from hashlib import sha256
from pathlib import Path

RULES = {
    "backend": {".py"}, "desktop": {".py"}, "migrations": {".py"}, "seed": {".json", ".md"},
    "frontend/dist": {".html", ".js", ".css", ".woff", ".woff2", ".ttf", ".svg", ".png", ".ico"},
}
BLOCKED = {"storage", ".pgdata", "node_modules", "__pycache__", ".git", "eval"}
ROOT_FILES = {"alembic.ini", "scripts/seed.py"}


def build_manifest(root: Path):
    root = root.resolve()
    entries = []
    candidates = [root / name for name in ROOT_FILES if (root / name).is_file()]
    for directory, suffixes in RULES.items():
        base = root / directory
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            relative = path.relative_to(root)
            if any(part in BLOCKED or part.startswith(".env") for part in relative.parts):
                continue
            if path.suffix.lower() not in suffixes or not path.is_file():
                continue
            candidates.append(path)
    for path in sorted(candidates):
        relative = path.relative_to(root)
        if any(parent.is_symlink() for parent in (path, *path.parents) if parent != root):
            raise ValueError(f"resource links are forbidden: {relative.as_posix()}")
        if not path.resolve().is_relative_to(root):
            raise ValueError("resource escapes workspace")
        digest = sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        entries.append({"path": relative.as_posix(), "bytes": path.stat().st_size, "sha256": digest.hexdigest()})
    return {"kind": "source-resource-manifest", "files": entries,
            "total_bytes": sum(entry["bytes"] for entry in entries),
            "installer_ready": False,
            "pending_release_gates": ["backend_executable", "bundled_postgres_runtime", "electron_shell",
                                      "offline_models", "backup_upgrade", "clean_windows_install_uninstall"]}
