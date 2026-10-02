"""随项目发布的知识讲解：文件是正文真相，数据库资料是可重建的检索副本。"""

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
from backend.models.learning import KnowledgePoint
from backend.models.rag import Material
from backend.resources import bundled_path

LESSON_DIR = Path(__file__).resolve().parents[2] / "seed" / "lessons"
_SAFE_CODE = re.compile(r"[a-z0-9][a-z0-9._-]{0,119}\Z")
_TITLE_SUFFIX = " · 系统讲解"


def lesson_file(code: str) -> Path | None:
    """只接受稳定业务编号，不让 URL 参数变成任意文件路径。"""
    if not _SAFE_CODE.fullmatch(code):
        return None
    return bundled_path(f"seed/lessons/{code}.md")


def read_lesson(code: str) -> str | None:
    path = lesson_file(code)
    if path is None or not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


async def sync_builtin_lessons(db: Session, *, materials_root: Path) -> dict[str, int]:
    """幂等导入可考核叶子的讲解，供内置资料问答检索。

    阅读接口始终读随仓库发布的 Markdown，不依赖向量模型。这里仅把同一文件
    复制为 source_type=builtin 的资料，并交给现有后台任务构建可引用索引。
    """
    created = updated = unchanged = 0
    root = materials_root.resolve()
    leaves = db.scalars(
        select(KnowledgePoint)
        .where(KnowledgePoint.is_active.is_(True), KnowledgePoint.is_assessable.is_(True))
        .order_by(KnowledgePoint.code)
    ).all()
    for node in leaves:
        path = lesson_file(node.code)
        if path is None or not path.is_file():
            raise ValueError(f"missing_builtin_lesson:{node.code}")
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        title = f"{node.name}{_TITLE_SUFFIX}"
        material = db.scalar(
            select(Material).where(
                Material.source_type == "builtin",
                Material.original_filename == path.name,
            )
        )
        stored_exists = False
        if material is not None:
            stored = (root / material.stored_path).resolve()
            stored_exists = root in stored.parents and stored.is_file()
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
            root=root,
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
