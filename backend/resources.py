"""Read-only bundled resources; never depend on cwd or user-upload directories."""
from pathlib import Path
import os
import sys


def resource_root() -> Path:
    if os.environ.get("APP_RUNTIME_PROFILE") == "desktop" and os.environ.get("DESKTOP_RESOURCE_ROOT"):
        root = Path(os.environ["DESKTOP_RESOURCE_ROOT"])
        if not root.is_absolute():
            raise ValueError("desktop_resource_root_invalid")
        return root.resolve()
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS).resolve()
    return Path(__file__).resolve().parents[1]


def bundled_path(relative: str) -> Path:
    root = resource_root()
    name = Path(relative)
    path = root / name
    if name.is_absolute() or not path.resolve().is_relative_to(root):
        raise ValueError("desktop_resource_path_escape")
    if any(parent.is_symlink() for parent in (path, *path.parents) if parent != root):
        raise ValueError("desktop_resource_links_forbidden")
    return path
