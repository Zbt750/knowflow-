"""把随项目发布的原创参考讲义幂等导入为可检索内置资料。"""

from __future__ import annotations

import hashlib
import re
from io import BytesIO
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.ingestion.file_storage import save_upload_streaming
from backend.jobs.worker import enqueue_job
from backend.models.rag import Material
from backend.resources import bundled_path

# None means the dynamic bundled location; tests may explicitly override it.
BUILTIN_REFERENCE_DIR: Path | None = None
_SAFE_NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,99}\.md\Z")


def _document_title(path: Path, raw: bytes) -> str:
    text = raw.decode("utf-8")
    for line in text.splitlines()[:20]:
        match = re.match(r"^#\s+(.+?)\s*$", line)
        if match:
            return match.group(1)[:200]
    return path.stem[:200]


async def sync_builtin_reference_materials(
    db: Session, *, materials_root: Path
) -> dict[str, int]:
    """导入固定目录下的 Markdown 参考讲义；不递归、不删除缺失资料。"""
    source_root = (BUILTIN_REFERENCE_DIR or bundled_path("seed/materials/builtin")).resolve()
    storage_root = materials_root.resolve()
    created = updated = unchanged = 0

    for candidate in sorted(source_root.glob("*.md")):
        # 文件名白名单 + resolve 校验：不让符号链接或可控文件名把种子读取越界。
        if not _SAFE_NAME.fullmatch(candidate.name):
            continue
        path = candidate.resolve()
        if source_root not in path.parents or not path.is_file():
            continue

        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        title = _document_title(path, raw)
        material = db.scalar(
            select(Material).where(
                Material.source_type == "builtin",
                Material.original_filename == path.name,
            )
        )
        stored_exists = False
        if material is not None:
            stored = (storage_root / material.stored_path).resolve()
            stored_exists = storage_root in stored.parents and stored.is_file()
        if material is not None and material.raw_hash == digest and stored_exists:
            material.title = title
            unchanged += 1
            continue

        if material is None:
            material = Material(
                title=title,
                source_type="builtin",
                original_filename=path.name,
                stored_path="pending",
                status="pending",
            )
            db.add(material)
            db.flush()
            job_type = "ingest"
            created += 1
        else:
            job_type = "reindex" if material.active_index_version else "ingest"
            material.title = title
            updated += 1

        stored_path, file_size, raw_hash = await save_upload_streaming(
            UploadFile(file=BytesIO(raw), filename=path.name),
            material_id=material.id,
            root=storage_root,
        )
        material.stored_path = stored_path
        material.file_size = file_size
        material.raw_hash = raw_hash
        material.status = "pending"
        material.last_error_code = None
        material.last_error_message = None
        db.flush()
        enqueue_job(db, material_id=material.id, job_type=job_type, max_attempts=3)

    return {"created": created, "updated": updated, "unchanged": unchanged}
