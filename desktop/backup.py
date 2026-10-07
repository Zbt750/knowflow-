"""Cold, same-path desktop data backup. No live cluster copying or data overwrite.

Archives contain private uploads/database data and are NOT encrypted. DPAPI
credentials still require the original Windows account/machine. Restore is only
allowed at the original data path when that path no longer exists.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
from uuid import uuid4
import zipfile

from desktop.postgres import DataDirectoryLock, _private_file

FORMAT = "kaoyan-cold-backup-v1"
TREES = {"postgres/cluster", "uploads", "chroma"}
CONFIG = {"config/postgres-owner.json", "config/postgres-credentials.bin", "config/bootstrap.json",
          "config/model-settings.bin", "config/vision-model-settings.bin"}
REQUIRED = {"postgres/cluster/PG_VERSION", "config/postgres-owner.json",
            "config/postgres-credentials.bin", "config/bootstrap.json"}
MAX_FILES = 100_000
MAX_BYTES = 20 * 1024**3


def _plain(path: Path):
    for part in (path, *path.parents):
        if part.is_symlink() or (hasattr(part, "is_junction") and part.is_junction()):
            raise ValueError("desktop_backup_links_forbidden")


def _name(name: str):
    parts = PurePosixPath(name).parts
    if (not parts or name != PurePosixPath(name).as_posix() or name.startswith("/")
            or any(p in {".", ".."} or ":" in p or "\\" in p or p.endswith((".", " ")) for p in parts)):
        raise ValueError("desktop_backup_member_invalid")
    if name not in CONFIG and not any(name.startswith(tree + "/") for tree in TREES):
        raise ValueError("desktop_backup_member_invalid")
    if name.endswith("/postmaster.pid"):
        raise ValueError("desktop_backup_cluster_running")


def _owned(data: Path, *, final_path: Path | None = None):
    try:
        owner = json.loads((data / "config/postgres-owner.json").read_text("utf-8"))
        receipt = json.loads((data / "config/bootstrap.json").read_text("utf-8"))
        expected = hashlib.sha256(str(((final_path or data) / "postgres/cluster").resolve()).encode()).hexdigest()
        if (owner["format"] != 1 or owner["major"] != 18 or owner["root_hash"] != expected
                or not isinstance(owner["cluster_id"], str) or not re.fullmatch(r"[a-f0-9]{32}", owner["cluster_id"])
                or receipt["format"] != 1 or receipt["initialized"] is not True
                or receipt["cluster_id"] != owner["cluster_id"]
                or (data / "postgres/cluster/PG_VERSION").read_text().strip() != "18"):
            raise ValueError()
        if (data / "postgres/cluster/postmaster.pid").exists():
            raise ValueError("desktop_backup_cluster_running")
        # PostgreSQL's control state must prove clean shutdown, not merely no PID.
        return owner
    except (OSError, KeyError, TypeError, json.JSONDecodeError):
        raise ValueError("desktop_backup_owned_data_invalid") from None


def create_backup(data: Path, destination: Path, *, pg_bin: Path):
    from desktop.postgres import _run
    if not data.is_absolute() or not destination.is_absolute() or not pg_bin.is_absolute():
        raise ValueError("desktop_backup_absolute_paths_required")
    _plain(data); _plain(destination); _plain(pg_bin)
    data = data.resolve(); destination = destination.resolve()
    if destination.is_relative_to(data) or destination.exists():
        raise ValueError("desktop_backup_destination_invalid")
    if not data.is_dir() or not destination.parent.is_dir():
        raise ValueError("desktop_backup_directory_missing")
    lock = DataDirectoryLock(data)
    temporary = destination.with_name(destination.name + "." + uuid4().hex + ".part")
    lock.acquire()
    try:
        owner = _owned(data)
        binary = pg_bin / ("pg_controldata.exe" if os.name == "nt" else "pg_controldata")
        _plain(binary)
        if not binary.is_file():
            raise ValueError("desktop_backup_control_binary_missing")
        control = _run([str(binary), str(data / "postgres/cluster")], extra_env={"LC_ALL": "C", "LANG": "C"})
        if control.returncode or b"Database cluster state:               shut down" not in control.stdout:
            raise ValueError("desktop_backup_clean_shutdown_required")
        candidates = [data / name for name in CONFIG if (data / name).exists()]
        directories = []
        for tree in sorted(TREES):
            root = data / tree
            _plain(root)
            if root.exists():
                directories.append(tree)
                for path in root.rglob("*"):
                    _plain(path)
                    if path.is_file():
                        candidates.append(path)
                    elif path.is_dir():
                        directories.append(path.relative_to(data).as_posix())
        if len(candidates) + len(directories) > MAX_FILES:
            raise ValueError("desktop_backup_limit_exceeded")
        rows = []
        total = 0
        with temporary.open("xb"):
            _private_file(temporary)  # Restrict before any private data is written.
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_STORED) as archive:
            for path in sorted(candidates):
                _plain(path)
                name = path.relative_to(data).as_posix(); _name(name)
                before = path.stat(); total += before.st_size
                if total > MAX_BYTES:
                    raise ValueError("desktop_backup_limit_exceeded")
                digest = hashlib.sha256()
                with path.open("rb") as source, archive.open(name, "w", force_zip64=True) as target:
                    while block := source.read(1024**2):
                        digest.update(block); target.write(block)
                after = path.stat()
                if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    raise ValueError("desktop_backup_data_changed")
                rows.append({"path": name, "bytes": before.st_size, "sha256": digest.hexdigest()})
            if not REQUIRED.issubset({row["path"] for row in rows}):
                raise ValueError("desktop_backup_owned_data_invalid")
            manifest = {"format": FORMAT, "data_path": str(data), "cluster_id": owner["cluster_id"],
                        "created_at": datetime.now(timezone.utc).isoformat(), "encrypted": False,
                        "same_windows_account_required": True, "excluded": ["models", "logs", "backups"],
                        "directories": sorted(directories), "files": rows}
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
        # Hard link is exclusive: a racing existing destination is never replaced.
        os.link(temporary, destination)
        return {"files": len(rows), "bytes": total, "encrypted": False, "same_path_required": True}
    finally:
        temporary.unlink(missing_ok=True)
        lock.release()


def inspect_backup(archive_path):
    if isinstance(archive_path, Path):
        _plain(archive_path)
    with zipfile.ZipFile(archive_path) as archive:
        infos = archive.infolist()
        if len(infos) > MAX_FILES + 1 or sum(row.file_size for row in infos) > MAX_BYTES + 16 * 1024**2:
            raise ValueError("desktop_backup_limit_exceeded")
        names = [row.filename for row in infos]
        if len(set(name.casefold() for name in names)) != len(names) or names.count("manifest.json") != 1:
            raise ValueError("desktop_backup_duplicate_members")
        if archive.getinfo("manifest.json").file_size > 16 * 1024**2:
            raise ValueError("desktop_backup_limit_exceeded")
        manifest = json.loads(archive.read("manifest.json"))
        if not isinstance(manifest, dict) or manifest.get("format") != FORMAT or not isinstance(manifest.get("files"), list):
            raise ValueError("desktop_backup_manifest_invalid")
        rows = manifest["files"]
        directories = manifest.get("directories")
        if not isinstance(directories, list) or len(directories) + len(rows) > MAX_FILES:
            raise ValueError("desktop_backup_manifest_invalid")
        if len({name.casefold() for name in directories}) != len(directories):
            raise ValueError("desktop_backup_manifest_invalid")
        file_names = {row["path"].casefold() for row in rows}
        for name in directories:
            if name not in TREES:
                _name(name)
            if name in CONFIG or name.casefold() in file_names:
                raise ValueError("desktop_backup_manifest_invalid")
        expected = {row["path"] for row in rows}
        if len(expected) != len(rows) or set(names) != expected | {"manifest.json"} or not REQUIRED.issubset(expected):
            raise ValueError("desktop_backup_manifest_invalid")
        for row in rows:
            _name(row["path"])
            info = archive.getinfo(row["path"])
            mode = info.external_attr >> 16
            if info.is_dir() or stat.S_IFMT(mode) not in {0, stat.S_IFREG} or info.flag_bits & 1 or info.file_size != row["bytes"]:
                raise ValueError("desktop_backup_member_invalid")
            digest = hashlib.sha256()
            with archive.open(info) as source:
                while block := source.read(1024**2):
                    digest.update(block)
            if digest.hexdigest() != row["sha256"]:
                raise ValueError("desktop_backup_checksum_mismatch")
        return manifest


def restore_backup(archive_path: Path, data: Path):
    """Never replace existing data. This is NOT cross-machine migration."""
    if not data.is_absolute() or not archive_path.is_absolute():
        raise ValueError("desktop_backup_absolute_paths_required")
    _plain(data); _plain(archive_path)
    data = data.resolve()
    if data.exists() or not data.parent.is_dir():
        raise ValueError("desktop_backup_restore_target_exists_or_missing_parent")
    # Keep one archive descriptor open from verification to extraction: no reopen race.
    with archive_path.open("rb") as handle:
        manifest = inspect_backup(handle)
        if manifest.get("data_path") != str(data):
            raise ValueError("desktop_backup_restore_requires_original_path")
        stage = Path(tempfile.mkdtemp(prefix=".kaoyan-restore-", dir=data.parent))
        try:
            _private_file(stage)
            with zipfile.ZipFile(handle) as archive:
                for name in manifest["directories"]:
                    (stage / name).mkdir(parents=True, exist_ok=True)
                for row in manifest["files"]:
                    target = stage / row["path"]
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(row["path"]) as source, target.open("xb") as output:
                        digest = hashlib.sha256()
                        while block := source.read(1024**2):
                            digest.update(block); output.write(block)
                    if digest.hexdigest() != row["sha256"] or target.stat().st_size != row["bytes"]:
                        raise ValueError("desktop_backup_checksum_mismatch")
            # Marker binds the final cluster path rather than the temporary stage.
            owner = _owned(stage, final_path=data)
            if owner.get("cluster_id") != manifest.get("cluster_id"):
                raise ValueError("desktop_backup_owned_data_invalid")
            if data.exists():
                raise ValueError("desktop_backup_restore_target_exists_or_missing_parent")
            stage.rename(data)
        finally:
            if stage.exists():
                # Only the exact temporary child created by this function is removed.
                shutil.rmtree(stage)
    return {"restored_files": len(manifest["files"]), "models_need_reinstall": True}
