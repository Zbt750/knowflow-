"""Separate immutable application resources from per-user mutable state."""
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RuntimePaths:
    resources: Path
    data: Path

    @classmethod
    def windows(cls, *, resources: Path, local_app_data: Path):
        if not resources.is_absolute() or not local_app_data.is_absolute():
            raise ValueError("desktop paths must be absolute")
        resource_root = resources.resolve()
        data_root = (local_app_data / "KaoyanStudy").resolve()
        if data_root == resource_root or resource_root in data_root.parents or data_root in resource_root.parents:
            raise ValueError("resource and data paths must not overlap")
        return cls(resource_root, data_root)

    def settings_overrides(self):
        # No database credentials here: the future PG supervisor supplies them.
        return {
            "upload_dir": self.data / "uploads",
            "chroma_dir": self.data / "chroma",
            "model_cache_dir": self.data / "models",
            "model_settings_path": self.data / "config" / "model-settings.bin",
        }

    def ensure_data_dirs(self):
        for name in ("uploads", "chroma", "models", "config", "logs", "backups", "postgres"):
            (self.data / name).mkdir(parents=True, exist_ok=True)
