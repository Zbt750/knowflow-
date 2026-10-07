"""内置参考讲义导入的目录边界、幂等性与变更重建。"""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.models.rag import Material
from backend.services import builtin_material_service as service


def test_builtin_reference_materials_sync_is_idempotent_and_reindexes_changes(
    tmp_path: Path, monkeypatch
) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "math2-guide.md").write_text("# 数学二讲义\n第一版", encoding="utf-8")
    (source_dir / "408-guide.md").write_text("# 408讲义\n原理内容", encoding="utf-8")
    nested = source_dir / "ignored"
    nested.mkdir()
    (nested / "nested.md").write_text("# 不得递归导入", encoding="utf-8")
    monkeypatch.setattr(service, "BUILTIN_REFERENCE_DIR", source_dir)

    enqueued: list[dict] = []

    async def fake_save(upload, *, material_id, root):
        upload.file.seek(0)
        raw = upload.file.read()
        relative = Path("builtin-reference") / str(material_id) / upload.filename
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        return relative.as_posix(), len(raw), hashlib.sha256(raw).hexdigest()

    monkeypatch.setattr(service, "save_upload_streaming", fake_save)
    monkeypatch.setattr(
        service,
        "enqueue_job",
        lambda _db, **kwargs: enqueued.append(kwargs),
    )

    engine = create_engine(f"sqlite:///{tmp_path / 'materials.db'}")
    Material.__table__.create(engine)
    storage_root = tmp_path / "storage"
    try:
        with Session(engine) as db:
            first = asyncio.run(
                service.sync_builtin_reference_materials(db, materials_root=storage_root)
            )
            db.commit()
            assert first == {"created": 2, "updated": 0, "unchanged": 0}
            assert len(enqueued) == 2
            rows = db.scalars(select(Material).order_by(Material.original_filename)).all()
            assert [row.original_filename for row in rows] == ["408-guide.md", "math2-guide.md"]
            assert all(row.source_type == "builtin" for row in rows)
            assert {row.title for row in rows} == {"数学二讲义", "408讲义"}

            second = asyncio.run(
                service.sync_builtin_reference_materials(db, materials_root=storage_root)
            )
            assert second == {"created": 0, "updated": 0, "unchanged": 2}
            assert len(enqueued) == 2

            (source_dir / "math2-guide.md").write_text("# 数学二讲义\n第二版", encoding="utf-8")
            third = asyncio.run(
                service.sync_builtin_reference_materials(db, materials_root=storage_root)
            )
            assert third == {"created": 0, "updated": 1, "unchanged": 1}
            assert len(enqueued) == 3
            assert enqueued[-1]["job_type"] == "ingest"
    finally:
        engine.dispose()


def test_builtin_reference_guides_and_question_source_index_exist() -> None:
    root = Path(__file__).resolve().parents[2]
    builtin = root / "seed" / "materials" / "builtin"
    assert (builtin / "math2-core-guide.md").is_file()
    assert (builtin / "cs408-core-guide.md").is_file()
    source_index = root / "resources" / "考研统考资料_数学二_408_2000至2026" / "真题来源索引.md"
    assert source_index.is_file()
    text = source_index.read_text(encoding="utf-8")
    assert "2000—2022" in text
    assert "2009—2025" in text
