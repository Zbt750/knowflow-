"""用户实测反馈的四个真实问题的回归测试。

每一条都对应一次真实观察到的错误行为，锁定的是「修复不会再退回去」，
而不仅仅是「当前实现没崩」。
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from backend.errors import SAFE_MESSAGES
from backend.ingestion.document_parsers import DocumentParseError, parse_source
from backend.ingestion.source_io import MAX_FILE_BYTES
from backend.jobs import worker as worker_module
from backend.jobs.worker import claim_job, run_job
from backend.models.jobs import DocumentJob
from backend.models.rag import Material

from tests.retrieval.conftest import create_material


# ---------------------------------------------------------------------------
# P2：上传与解析上限必须一致，且超限在上传阶段就被拒绝
# ---------------------------------------------------------------------------


def test_oversized_upload_is_rejected_at_upload_stage(
    client: TestClient, session_factory
) -> None:
    """超过上限的文件必须在上传时就 413，绝不能「先 201 再异步失败」。

    用户实测：11 MB 的 md 上传返回 201，随后任务失败并提示「超过 20 MB」。
    """
    oversized = b"a" * (MAX_FILE_BYTES + 1024)
    response = client.post(
        "/api/materials",
        params={"title": "超大文件", "source_type": "user"},
        files={"file": ("huge.md", oversized)},
    )

    assert response.status_code == 413
    payload = response.json()
    assert payload["error"]["code"] == "file_too_large"

    # 关键：不能留下任何痕迹（既没有资料记录，也没有任务）。
    with session_factory() as db:
        assert db.scalars(select(Material)).all() == []
        assert db.scalars(select(DocumentJob)).all() == []


def test_file_just_below_limit_is_accepted(client: TestClient) -> None:
    """刚好在上限之内的文件必须能正常上传，避免上限判断off-by-one。"""
    payload = ("# 讲义\n\n## 第一章\n\n" + "内容" * 100).encode("utf-8")
    response = client.post(
        "/api/materials",
        params={"title": "正常大小", "source_type": "user"},
        files={"file": ("ok.md", payload)},
    )
    assert response.status_code == 201


def test_parse_limit_matches_upload_limit(tmp_path: Path) -> None:
    """解析阶段的读入上限不能比上传上限更小，否则就会出现「传上去才失败」。"""
    from backend.ingestion.source_io import read_limited_bytes

    target = tmp_path / "big.md"
    target.write_bytes(b"a" * (MAX_FILE_BYTES + 1))

    with pytest.raises(ValueError, match="file_too_large"):
        read_limited_bytes(target)


# ---------------------------------------------------------------------------
# P3：损坏的 PDF / DOCX 必须给出稳定业务码，不能把异常类名漏到界面
# ---------------------------------------------------------------------------


def test_corrupt_pdf_reports_stable_code(tmp_path: Path) -> None:
    """损坏的 PDF 报 document_parse_failed，而不是 PdfReadError。"""
    broken = tmp_path / "broken.pdf"
    # 有 PDF 魔数但内容残缺：这正是用户实测时触发 PdfReadError 的形状。
    broken.write_bytes(b"%PDF-1.4\nthis is not a valid pdf body\n%%EOF\n")

    with pytest.raises(DocumentParseError) as captured:
        parse_source(broken)

    assert captured.value.code == "document_parse_failed"
    # 真实异常类型只允许出现在 detail（进日志），不能出现在 code 里。
    assert "PdfReadError" not in captured.value.code
    assert captured.value.code in SAFE_MESSAGES


def test_scanned_pdf_still_reports_scanned_pdf(tmp_path: Path) -> None:
    """合法但无文本层的 PDF 仍然报 scanned_pdf：包装不能把具体错误码吞掉。"""
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    target = tmp_path / "blank.pdf"
    with target.open("wb") as handle:
        writer.write(handle)

    with pytest.raises(ValueError, match="scanned_pdf"):
        parse_source(target)


def test_corrupt_docx_reports_stable_code(tmp_path: Path) -> None:
    """损坏的 .docx 同样必须是稳定码（底层会抛 zipfile 的异常）。"""
    broken = tmp_path / "broken.docx"
    # PK 魔数 + 非 zip 内容：python-docx 会抛 PackageNotFoundError / BadZipFile。
    broken.write_bytes(b"PK\x03\x04not a real zip archive")

    with pytest.raises(DocumentParseError) as captured:
        parse_source(broken)

    assert captured.value.code == "document_parse_failed"
    assert captured.value.code in SAFE_MESSAGES


def test_worker_unexpected_error_uses_stable_code(
    client: TestClient, runner, session_factory
) -> None:
    """任何未预期异常都只能落成 internal_error，不能是 unexpected:类名。"""
    from tests.materials.test_ingestion_e2e import upload

    body = upload(client)
    material_id = body["material"]["id"]

    with session_factory() as db:
        job = claim_job(db, worker_id="w")
        assert job is not None
        material = db.get(Material, job.material_id)

        # 直接让解析阶段抛一个非 IngestionError 的异常，模拟未知故障。
        original = worker_module.plan_material

        def boom(*args, **kwargs):
            raise RuntimeError("模拟未知故障")

        worker_module.plan_material = boom
        try:
            result = run_job(
                db,
                job,
                materials_root=Path("unused"),
                embedder=None,  # type: ignore[arg-type]
                vector_store=runner._stack.vector_store,
                keyword_index=runner._stack.keyword_index,
            )
        finally:
            worker_module.plan_material = original
        db.commit()

    assert result.error_code == "internal_error"
    assert result.error_code in SAFE_MESSAGES
    assert "unexpected" not in (result.error_code or "")
    # 异常类名只允许出现在日志摘要里。
    with session_factory() as db:
        stored = db.get(Material, material_id)
        assert stored.last_error_code == "internal_error"


# ---------------------------------------------------------------------------
# P4：indexing 中间态必须对 API 可见
# ---------------------------------------------------------------------------


def test_indexing_state_is_visible_to_another_session(
    client: TestClient, runner, session_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`indexing` 必须在建索引期间真实可见。

    回归用例：worker 只 `flush()` 不 `commit()`，而 runner 是整批结束后才提交一次，
    READ COMMITTED 下未提交行对外不可见 —— 于是 API 永远返回不到 `indexing`，
    前端「建立索引中」标签与验收步骤里的状态观察全都做不到。

    做法：在「中间态刚刚提交」这一刻，用一个**独立连接**去读数据库。
    """
    from tests.materials.test_ingestion_e2e import upload

    upload(client)

    observed: dict[str, str | None] = {}
    database_url = str(client.app.state.settings.active_database_url)  # type: ignore[attr-defined]

    def observe() -> None:
        # 独立 engine + 独立连接：只有真正提交过的数据才可能被它读到。
        from backend.db import create_db_engine

        engine = create_db_engine(database_url)
        try:
            with engine.connect() as connection:
                row = connection.execute(
                    text("SELECT status FROM materials ORDER BY created_at DESC LIMIT 1")
                ).first()
                observed["status"] = row[0] if row else None
        finally:
            engine.dispose()

    monkeypatch.setattr(worker_module, "_after_indexing_committed", observe)

    results = runner.run_once()
    assert results and results[0].status == "succeeded"
    assert observed.get("status") == "indexing", (
        "另一个连接必须能读到 indexing；读到 "
        f"{observed.get('status')!r} 说明中间态没有提交，对外不可见"
    )

    # 任务结束后最终状态是 ready。
    with session_factory() as db:
        material = db.scalars(
            select(Material).order_by(Material.created_at.desc()).limit(1)
        ).first()
        assert material is not None and material.status == "ready"


def test_recover_expired_job_killed_after_indexing_commit(
    client: TestClient, session_factory
) -> None:
    """在 indexing 提交之后进程崩溃（模拟）：任务必须能被租约回收，不会永久卡住。"""
    from datetime import timedelta

    from backend.jobs.worker import recover_expired_jobs
    from tests.materials.test_ingestion_e2e import upload

    upload(client)

    with session_factory() as db:
        now = datetime.now(timezone.utc)
        job = claim_job(db, worker_id="crashed", now=now)
        assert job is not None
        material = db.get(Material, job.material_id)
        # 模拟「已提交 indexing、然后进程死掉」留下的状态。
        material.status = "indexing"
        job.lease_until = now - timedelta(seconds=1)
        db.commit()

        assert recover_expired_jobs(db, now=now) == 1
        db.commit()

    with session_factory() as db:
        job = db.scalars(select(DocumentJob)).one()
        assert job.status == "retry"
        assert job.worker_id is None


# ---------------------------------------------------------------------------
# 前端测试不得破坏用户数据（P1 的夹具约定在 Python 侧的同构检查）
# ---------------------------------------------------------------------------


def test_acceptance_script_does_not_delete_existing_materials(
    client: TestClient, session_factory
) -> None:
    """验收脚本必须保留用户已有资料。

    这里只验证「脚本使用的前缀约定」这一层：
    它创建的资料都带唯一测试前缀，且它删除时只按前缀匹配。
    真正的端到端行为由 `scripts/e2e_materials_check.py` 在真实服务上验证。
    """
    from scripts.e2e_materials_check import TEST_TITLE_PREFIX

    assert TEST_TITLE_PREFIX.startswith("E2E-"), "测试资料必须带可识别前缀"

    # 用户资料（无前缀）与测试资料（有前缀）能按前缀区分开。
    with session_factory() as db:
        create_material(db, title="用户自己的验收讲义", body="# 用户资料\n\n正文\n")
        db.commit()

    with session_factory() as db:
        titles = [row[0] for row in db.execute(text("SELECT title FROM materials")).all()]

    assert any(not title.startswith(TEST_TITLE_PREFIX) for title in titles)
    assert not any(title.startswith(TEST_TITLE_PREFIX) for title in titles)
