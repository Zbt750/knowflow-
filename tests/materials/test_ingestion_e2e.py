"""「上传 → 队列 → 解析 → 建索引 → 可检索」端到端测试。

这是阶段 C 的核心验证：资料必须真的能被放进知识库，并且检索能引用回原文。
用真实数据库、真实文件、真实分块算法；只有 embedding 与向量库是替身。
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.ingestion.text_normalize import normalize_text
from backend.jobs.worker import (
    DEFAULT_LEASE_SECONDS,
    claim_job,
    enqueue_job,
    recover_expired_jobs,
    requeue_stale_pending_jobs,
    run_pending_jobs,
)
from backend.models.jobs import DocumentJob
from backend.models.rag import ChunkKnowledgePoint, DocumentChunk, Material
from backend.retrieval.protocols import EmbeddingUnavailableError
from backend.services.ingestion_service import (
    IngestionError,
    compute_index_version,
    is_valid_index_version,
)

LECTURE = "seed/materials/gaoshu-lecture-01.md"
LP = "math.calculus.limit.lhopital"


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def lecture_bytes() -> bytes:
    return (project_root() / LECTURE).read_bytes()


def upload(
    client: TestClient,
    *,
    title: str = "高等数学核心考点讲义",
    filename: str = "gaoshu-lecture-01.md",
    content: bytes | None = None,
    source_type: str = "builtin",
) -> dict:
    response = client.post(
        "/api/materials",
        params={"title": title, "source_type": source_type},
        files={"file": (filename, content if content is not None else lecture_bytes())},
    )
    assert response.status_code == 201, response.text
    return response.json()


def drain(runner, *, advance: bool = False) -> list:
    """把队列跑干：反复 run_once 直到没有可领任务。

    失败任务会按退避时间推迟下次领取，因此需要「跑干重试」的测试要用
    `advance=True` 让每轮的时间往后跳，否则第二轮就会领不到任务。
    """
    from datetime import datetime, timedelta, timezone

    results = []
    now = datetime.now(timezone.utc)
    for attempt in range(10):
        if advance:
            # 退避是按 5 * 2^(n-1) 秒递增的，跳 1 小时足以跨过任何一轮退避。
            now = now + timedelta(hours=1) * attempt if attempt else now
        batch = runner.run_once(now=now)
        if not batch:
            break
        results.extend(batch)
        if any(result.status in {"retry", "failed"} for result in batch):
            now = now + timedelta(hours=1)
    return results


def material_id_of(body: dict) -> UUID:
    return UUID(body["material"]["id"])


# ---------------------------------------------------------------------------
# 索引版本号契约
# ---------------------------------------------------------------------------


def test_index_version_is_deterministic_and_formatted() -> None:
    """版本号必须只依赖正文、模型与分块算法：同样输入永远同样结果。"""
    first = compute_index_version("abc123", "BAAI/bge-small-zh-v1.5")
    second = compute_index_version("abc123", "BAAI/bge-small-zh-v1.5")
    assert first == second
    assert is_valid_index_version(first)
    # 换模型必须换版本号，否则新旧向量会混在一个版本里。
    assert compute_index_version("abc123", "other-model") != first
    # 换正文也必须换版本号。
    assert compute_index_version("def456", "BAAI/bge-small-zh-v1.5") != first


@pytest.mark.parametrize("value", ["", "v1-", "v1-xyz", "v2-0123456789abcdef", "v1-0123"])
def test_invalid_index_version_is_rejected(value: str) -> None:
    assert is_valid_index_version(value) is False


# ---------------------------------------------------------------------------
# 上传接口
# ---------------------------------------------------------------------------


def test_upload_creates_pending_material_and_job(client: TestClient) -> None:
    body = upload(client)
    assert body["material"]["status"] == "pending"
    assert body["material"]["title"] == "高等数学核心考点讲义"
    assert body["material"]["source_type"] == "builtin"
    # 上传响应不得泄露落盘路径。
    assert "stored_path" not in body["material"]


def test_upload_rejects_unsupported_suffix(client: TestClient) -> None:
    response = client.post(
        "/api/materials",
        params={"title": "坏格式", "source_type": "user"},
        files={"file": ("notes.exe", b"MZ\x90\x00")},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unsupported_type"


def test_upload_rejects_empty_file(client: TestClient) -> None:
    response = client.post(
        "/api/materials",
        params={"title": "空文件", "source_type": "user"},
        files={"file": ("empty.md", b"")},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "empty_file"


def test_upload_rejects_bad_source_type(client: TestClient) -> None:
    response = client.post(
        "/api/materials",
        params={"title": "来源不对", "source_type": "hacked"},
        files={"file": ("a.md", b"# t\n")},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"


def test_failed_upload_leaves_no_orphan_material(client: TestClient, session_factory) -> None:
    """落盘失败时不能留下「有记录没文件」的孤儿资料。"""
    client.post(
        "/api/materials",
        params={"title": "坏格式", "source_type": "user"},
        files={"file": ("notes.exe", b"MZ")},
    )
    with session_factory() as db:
        assert db.scalars(select(Material)).all() == []
        assert db.scalars(select(DocumentJob)).all() == []


# ---------------------------------------------------------------------------
# 完整摄取链路
# ---------------------------------------------------------------------------


def test_ingest_makes_material_ready_and_retrievable(
    client: TestClient, runner, session_factory
) -> None:
    """主链路：上传 → 处理成功 → ready → 能按知识点检索到对应原文。"""
    body = upload(client)
    material_id = material_id_of(body)

    results = drain(runner)
    assert [result.status for result in results] == ["succeeded"]
    assert results[0].chunk_count > 0

    with session_factory() as db:
        material = db.get(Material, material_id)
        assert material.status == "ready"
        assert is_valid_index_version(material.active_index_version or "")
        # 规范化正文已写入，且它是 offset 的坐标系。
        assert material.normalized_text
        assert material.content_hash

        chunks = list(
            db.scalars(
                select(DocumentChunk)
                .where(DocumentChunk.material_id == material_id)
                .order_by(DocumentChunk.ordinal)
            ).all()
        )
        assert len(chunks) == results[0].chunk_count
        # 每个块的正文必须等于规范化全文的原始切片。
        for chunk in chunks:
            assert material.normalized_text[chunk.start_offset : chunk.end_offset] == chunk.content
        # 序号必须从 0 连续递增，否则「第几块」不可靠。
        assert [chunk.ordinal for chunk in chunks] == list(range(len(chunks)))

    # 检索必须能命中，并且带上正确的知识点关联。
    lp_kp_id = _kp_id(session_factory, LP)
    response = client.post(
        "/api/materials/search",
        json={"query": "洛必达法则的适用条件是什么", "top_k": 5, "kp_ids": [str(lp_kp_id)]},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["hits"], "应能检索到洛必达法则相关原文"
    assert all(str(lp_kp_id) in [str(k) for k in hit["kp_ids"]] for hit in payload["hits"])
    assert payload["degraded"] is False


def _kp_id(session_factory, code: str) -> UUID:
    from backend.models.learning import KnowledgePoint

    with session_factory() as db:
        return db.scalar(select(KnowledgePoint.id).where(KnowledgePoint.code == code))


def test_keyword_index_is_populated_after_ingest(client: TestClient, runner, stack) -> None:
    """摄取成功后关键词索引必须真的有内容。

    回归用例：曾经在 build_index 里重建关键词索引，而那时资料状态还是 indexing，
    被 _load_keyword_records 的 ready 条件过滤掉，结果是「关键词候选永远 0 条」——
    检索看起来能用，实际只剩向量一路。
    """
    upload(client)
    drain(runner)

    assert stack.keyword_index.count() > 0, "关键词索引不能为空"
    # 用真实关键词查询，确认关键词路确实召回了结果。
    response = client.post(
        "/api/materials/search", json={"query": "洛必达法则适用条件", "top_k": 5}
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["keyword_candidates"] > 0, "关键词路必须有召回"
    assert any(hit["keyword_rank"] is not None for hit in payload["hits"])


def test_ingest_links_chunks_to_knowledge_points(client: TestClient, runner, session_factory) -> None:
    """每个 kp 标记都必须真的在关联表里产生一行，否则 matched_kp 无从谈起。"""
    upload(client)
    drain(runner)

    with session_factory() as db:
        links = db.execute(
            select(ChunkKnowledgePoint.kp_id, ChunkKnowledgePoint.confidence)
        ).all()
    assert links, "必须建立知识点关联"
    # 显式标记是人工写的，置信度必须是 1.0，不能被「模型猜的」稀释。
    assert all(confidence == 1.0 for _, confidence in links)
    # 内置讲义覆盖 5 个叶子知识点。
    assert len({kp_id for kp_id, _ in links}) == 5


def test_ingest_is_idempotent_on_reindex(client: TestClient, runner, session_factory) -> None:
    """重建索引不能产生重复块：同版本重跑必须覆盖而不是累加。"""
    body = upload(client)
    material_id = material_id_of(body)
    drain(runner)

    with session_factory() as db:
        version = db.get(Material, material_id).active_index_version
        first_count = db.query(DocumentChunk).filter_by(material_id=material_id).count()
        # 记录「内容 hash 序列」而不是 chunk id：chunk 是重新生成的，
        # id 必然变化；真正必须稳定的是分块结果本身。
        first_hashes = [
            chunk.content_hash
            for chunk in db.scalars(
                select(DocumentChunk)
                .where(DocumentChunk.material_id == material_id)
                .order_by(DocumentChunk.ordinal)
            ).all()
        ]

    # 直接再建一条 reindex 任务（模拟用户点「重建」）。
    response = client.post(f"/api/materials/{material_id}/reindex")
    assert response.status_code == 202
    drain(runner)

    with session_factory() as db:
        material = db.get(Material, material_id)
        second_count = db.query(DocumentChunk).filter_by(material_id=material_id).count()
        # 版本号只依赖内容与模型，重建后必须还是同一个版本。
        assert material.active_index_version == version
        assert second_count == first_count, "重建不能留下重复块"
        second_hashes = [
            chunk.content_hash
            for chunk in db.scalars(
                select(DocumentChunk)
                .where(DocumentChunk.material_id == material_id)
                .order_by(DocumentChunk.ordinal)
            ).all()
        ]
        assert second_hashes == first_hashes, "重建必须得到完全相同的分块结果"


def test_ingest_marks_material_failed_when_source_missing(
    client: TestClient, runner, session_factory, materials_root: Path
) -> None:
    """源文件被删掉后任务必须失败并给出稳定错误码，且不能把结果标成 ready。"""
    body = upload(client)
    material_id = material_id_of(body)
    with session_factory() as db:
        stored_path = db.get(Material, material_id).stored_path
    (materials_root / stored_path).unlink()

    results = drain(runner)
    # 第一次失败会进入 retry（还有重试机会），这里确认错误码正确且资料没被标成 ready。
    assert results[0].status in {"retry", "failed"}
    assert results[0].error_code == "material_file_not_found"

    with session_factory() as db:
        material = db.get(Material, material_id)
        assert material.status != "ready"
        assert material.active_index_version is None
        assert material.last_error_code == "material_file_not_found"


def test_retry_exhaustion_sets_failed(client: TestClient, runner, session_factory, materials_root: Path) -> None:
    """重试用尽后必须落到 failed 终态，而不是无限重试。"""
    body = upload(client)
    material_id = material_id_of(body)
    with session_factory() as db:
        stored_path = db.get(Material, material_id).stored_path
    (materials_root / stored_path).unlink()

    # max_attempts=3：跑足够多轮把重试次数用尽（每次跨越退避等待）。
    drain(runner, advance=True)

    with session_factory() as db:
        job = db.scalars(select(DocumentJob)).one()
        assert job.attempts == job.max_attempts
        assert job.status == "failed"
        assert db.get(Material, material_id).status == "failed"


def test_scanned_pdf_reports_specific_error(client: TestClient, runner, session_factory) -> None:
    """扫描件 PDF 必须报 scanned_pdf，而不是「解析出零个块」这种含糊结果。"""
    from pypdf import PdfWriter

    import io

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    writer.write(buffer)

    body = upload(client, title="扫描件", filename="scan.pdf", content=buffer.getvalue())
    assert material_id_of(body)
    results = drain(runner)
    assert results[0].error_code == "scanned_pdf"


def test_unresolved_kp_hint_does_not_break_ingest(
    client: TestClient, runner, session_factory
) -> None:
    """标注了不存在的知识点编号时仍要能入库：只记录，不阻断。"""
    content = "# 讲义\n\n<!-- kp:not.exist.code -->\n\n## 第一章\n\n正文内容。\n".encode("utf-8")
    upload(client, title="未知知识点", filename="unknown.md", content=content)
    results = drain(runner)
    assert results[0].status == "succeeded"

    with session_factory() as db:
        assert db.scalars(select(ChunkKnowledgePoint)).all() == []
        assert db.scalars(select(DocumentChunk)).all()


def test_embedding_failure_keeps_material_retryable(client: TestClient, session_factory, materials_root: Path) -> None:
    """embedding 不可用是可恢复错误：任务进入 retry，资料不能被标成 ready。"""
    from backend.jobs.runner import MaterialJobRunner
    from backend.retrieval.keyword import KeywordIndex
    from backend.retrieval.rerank import IdentityReranker
    from backend.retrieval.stack import RetrievalStack
    from backend.retrieval.vector_store import InMemoryVectorStore

    class BrokenEmbedder:
        model_name = "broken-embedder"

        @property
        def dimension(self) -> int:
            return 8

        def encode(self, texts):
            raise EmbeddingUnavailableError("模型不可用")

    body = upload(client)
    material_id = material_id_of(body)
    broken = RetrievalStack(
        embedder=BrokenEmbedder(),
        vector_store=InMemoryVectorStore(embedding_model="broken-embedder"),
        keyword_index=KeywordIndex(),
        reranker=IdentityReranker(),
    )
    runner = MaterialJobRunner(
        session_factory=session_factory, stack=broken, materials_root=materials_root
    )
    results = runner.run_once()

    assert results[0].error_code == "embedding_unavailable"
    assert results[0].status == "retry"
    with session_factory() as db:
        material = db.get(Material, material_id)
        assert material.status != "ready"
        assert material.active_index_version is None


# ---------------------------------------------------------------------------
# 任务租约与崩溃恢复
# ---------------------------------------------------------------------------


def test_claim_job_respects_lease_and_backoff(client: TestClient, session_factory) -> None:
    """已被别人领走且租约未过期的任务不能被重复领取。"""
    from datetime import datetime, timedelta, timezone

    body = upload(client)
    material_id = material_id_of(body)

    with session_factory() as db:
        now = datetime.now(timezone.utc)
        first = claim_job(db, worker_id="w1", now=now)
        assert first is not None
        assert first.material_id == material_id
        # 同一时刻第二个 worker 不能再领到同一条。
        assert claim_job(db, worker_id="w2", now=now) is None
        # 租约过期后可以被回收重领。
        later = now + timedelta(seconds=DEFAULT_LEASE_SECONDS + 1)
        reclaimed = claim_job(db, worker_id="w2", now=later)
        assert reclaimed is not None
        assert reclaimed.worker_id == "w2"
        db.commit()


def test_recover_expired_jobs_returns_to_retry(client: TestClient, session_factory) -> None:
    """worker 崩溃后租约过期，任务必须能被别人重新领取。"""
    from datetime import datetime, timedelta, timezone

    upload(client)
    with session_factory() as db:
        now = datetime.now(timezone.utc)
        job = claim_job(db, worker_id="dead-worker", now=now)
        assert job is not None
        job.lease_until = now - timedelta(seconds=1)
        db.flush()

        recovered = recover_expired_jobs(db, now=now)
        assert recovered == 1
        assert job.status == "retry"
        assert job.worker_id is None
        assert job.error_code == "lease_expired"
        # attempts 已经计过，回收不能再吃一次重试机会。
        assert job.attempts == 1
        db.commit()


def test_requeue_stale_pending_job(client: TestClient, session_factory) -> None:
    """资料卡在 indexing 时，pending 任务必须重新可领，否则永远无法恢复。"""
    from datetime import datetime, timedelta, timezone

    body = upload(client)
    with session_factory() as db:
        material = db.get(Material, UUID(body["material"]["id"]))
        material.status = "indexing"
        job = db.scalars(select(DocumentJob)).one()
        job.next_run_at = datetime.now(timezone.utc) + timedelta(hours=1)
        db.flush()

        requeued = requeue_stale_pending_jobs(db)
        assert requeued == 1
        assert job.next_run_at <= datetime.now(timezone.utc)
        db.commit()


def test_run_pending_jobs_returns_empty_when_queue_is_empty(runner) -> None:
    """没有任务时返回空列表，而不是抛错。"""
    assert runner.run_once() == []


# ---------------------------------------------------------------------------
# 列表 / 详情 / 删除
# ---------------------------------------------------------------------------


def test_list_materials_reports_stats(client: TestClient, runner) -> None:
    upload(client, title="讲义甲")
    upload(client, title="讲义乙", filename="b.md", content=b"# b\n\n## t\n\naaa\n")
    drain(runner)

    response = client.get("/api/materials")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 2
    assert payload["stats"]["ready"] == 2
    assert {item["title"] for item in payload["items"]} == {"讲义甲", "讲义乙"}


def test_list_materials_searches_titles_beyond_current_page(client: TestClient) -> None:
    upload(client, title="跨页目标讲义")
    for index in range(4):
        upload(client, title=f"普通讲义{index}")

    first_page = client.get("/api/materials", params={"limit": 2}).json()
    assert first_page["total"] == 5
    assert all(item["title"] != "跨页目标讲义" for item in first_page["items"])

    result = client.get("/api/materials", params={"limit": 2, "q": "目标"})
    assert result.status_code == 200
    payload = result.json()
    assert payload["total"] == 1
    assert [item["title"] for item in payload["items"]] == ["跨页目标讲义"]
    assert payload["stats"]["total"] == 5


def test_detail_reports_chunk_count_and_latest_job(client: TestClient, runner) -> None:
    body = upload(client)
    material_id = material_id_of(body)
    drain(runner)

    response = client.get(f"/api/materials/{material_id}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["chunk_count"] > 0
    assert payload["latest_job"]["status"] == "succeeded"
    assert payload["active_index_version"]


def test_chunk_preview_is_consistent_with_material_text(
    client: TestClient, runner, session_factory
) -> None:
    """块预览必须能对上正文：预览内容要真的出现在规范化全文里。"""
    body = upload(client)
    material_id = material_id_of(body)
    drain(runner)

    response = client.get(f"/api/materials/{material_id}/chunks", params={"limit": 5})
    assert response.status_code == 200
    payload = response.json()
    assert payload["items"]
    with session_factory() as db:
        text = db.get(Material, material_id).normalized_text
    for item in payload["items"]:
        assert item["preview"] in text
        assert item["char_count"] >= len(item["preview"])


def test_focus_chunk_is_returned_even_outside_preview_limit(
    client: TestClient, runner, session_factory
) -> None:
    """引用回跳按 UUID 精确定位，不能受「前 20 块」预览上限影响。"""
    body = upload(client)
    material_id = material_id_of(body)
    drain(runner)

    with session_factory() as db:
        target = db.scalars(
            select(DocumentChunk)
            .where(DocumentChunk.material_id == material_id)
            .order_by(DocumentChunk.ordinal.desc())
            .limit(1)
        ).one()

    response = client.get(
        f"/api/materials/{material_id}/chunks",
        params={"limit": 1, "focus_chunk_id": str(target.id)},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert any(item["id"] == str(target.id) for item in payload["items"])
    focused = next(item for item in payload["items"] if item["id"] == str(target.id))
    assert focused["ordinal"] == target.ordinal
    assert focused["preview"] in target.content

def test_unknown_material_returns_404(client: TestClient) -> None:
    response = client.get(f"/api/materials/{uuid4()}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "material_not_found"


def test_delete_removes_material_and_index(
    client: TestClient, runner, session_factory, stack, materials_root: Path
) -> None:
    """删除必须同时清掉数据库记录、磁盘文件与向量索引，不留残影。"""
    body = upload(client)
    material_id = material_id_of(body)
    drain(runner)

    with session_factory() as db:
        stored_path = db.get(Material, material_id).stored_path
    # 删除前文件确实在磁盘上。
    assert (materials_root / stored_path).exists()

    response = client.delete(f"/api/materials/{material_id}")
    assert response.status_code == 204, response.text

    with session_factory() as db:
        assert db.get(Material, material_id) is None
        assert db.scalars(select(DocumentChunk).where(DocumentChunk.material_id == material_id)).all() == []
        assert db.scalars(select(DocumentJob).where(DocumentJob.material_id == material_id)).all() == []

    # 向量索引必须清干净，否则检索会召回到已删除的资料。
    assert stack.vector_store.count() == 0
    # 磁盘文件也应删掉。
    assert not (materials_root / stored_path).exists()
    # 关键词索引同样要刷新：它是内存索引，不刷新会留下已删资料的残影。
    assert stack.keyword_index.count() == 0


def test_delete_then_search_returns_nothing(client: TestClient, runner) -> None:
    body = upload(client)
    material_id = material_id_of(body)
    drain(runner)

    before = client.post("/api/materials/search", json={"query": "洛必达法则", "top_k": 5})
    assert before.json()["hits"], "删除前应能检索到"

    assert client.delete(f"/api/materials/{material_id}").status_code == 204

    after = client.post("/api/materials/search", json={"query": "洛必达法则", "top_k": 5})
    assert after.json()["hits"] == []


def test_search_requires_query(client: TestClient) -> None:
    response = client.post("/api/materials/search", json={"query": "", "top_k": 5})
    assert response.status_code == 422


def test_index_version_has_no_chunk_is_rejected(session_factory) -> None:
    """激活一个没有任何块的版本必须报错：否则资料会「ready 却检索不到」。"""
    from backend.services.ingestion_service import activate_version

    with session_factory() as db:
        material = Material(
            title="空资料",
            source_type="user",
            stored_path="x/source.md",
            status="ready",
            active_index_version="v1-0000000000000000",
        )
        db.add(material)
        db.flush()
        with pytest.raises(IngestionError, match="index_version_has_no_chunk"):
            activate_version(db, material, "v1-1111111111111111")


def test_normalized_text_is_offset_coordinate(client: TestClient, runner, session_factory) -> None:
    """分块 offset 必须以规范化文本为坐标系 —— 这是引用回跳的前提。"""
    body = upload(client)
    material_id = material_id_of(body)
    drain(runner)

    with session_factory() as db:
        material = db.get(Material, material_id)
        # 数据库里的正文必须与「重新规范化原文」的结果逐字节一致。
        expected = normalize_text(
            (project_root() / LECTURE).read_text(encoding="utf-8")
        )
        assert material.normalized_text == expected
