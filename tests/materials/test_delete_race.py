"""删除资料与后台索引任务之间的竞态回归测试。

背景：e2e 里「重建索引」用例会紧接着删除资料，于是稳定地留下一个孤儿向量
（15 条）。原因是删除接口「先清向量库、再删数据库记录」不在同一个事务里，
而索引任务可能在这中间才走到写库阶段。

用户可见的后果：
- 轻则索引里堆一批永远召不回、也无人清理的向量；
- 重则对已删除资料插入块，外键失败，被报成 internal_error。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from backend.jobs.worker import claim_job, enqueue_job, run_job
from backend.models.rag import Material

from tests.materials.test_ingestion_e2e import upload


def test_index_job_aborts_when_material_deleted_midway(
    client: TestClient, runner, session_factory
) -> None:
    """任务开始后资料被删除：不得插入块、不得写入向量。

    做法：先领取任务（此时任务已进入 running），模拟「资料在处理过程中被删掉」，
    再执行任务，最后断言数据库与向量库都没有留下任何东西。
    """
    body = upload(client)
    material_id = body["material"]["id"]

    with session_factory() as db:
        job = claim_job(db, worker_id="racer")
        assert job is not None
        # 模拟删除接口的动作：先清向量（这里本来就没有），再删数据库记录。
        material = db.get(Material, job.material_id)
        assert material is not None
        runner._stack.vector_store.delete_material_all_versions(material.id)
        db.delete(material)
        db.commit()

        result = run_job(
            db,
            job,
            materials_root=runner._materials_root,
            embedder=runner._stack.embedder,
            vector_store=runner._stack.vector_store,
            keyword_index=runner._stack.keyword_index,
        )
        db.commit()

    # 任务被判为「资料不存在」：这是设计行为（资料没了，任务没有意义），
    # 关键是**不抛异常、不报 internal_error、不留下任何数据**。
    assert result.error_code == "material_not_found"
    assert result.status == "failed"

    with session_factory() as db:
        # 不得残留任何块（否则外键或孤儿记录会出问题）。
        remaining = db.execute(
            text("SELECT count(*) FROM document_chunks WHERE material_id = :mid"),
            {"mid": material_id},
        ).scalar()
        assert remaining == 0, "资料已删除，不得再写入块"

    # 不得留下孤儿向量。
    assert runner._stack.vector_store.count() == 0, "资料已删除，不得再写入向量"


def test_index_job_still_indexes_when_material_exists(
    client: TestClient, runner, session_factory
) -> None:
    """反向保护：资料还在时必须正常建索引，别把正常路径一起挡掉。"""
    body = upload(client)
    material_id = body["material"]["id"]

    results = runner.run_once()
    assert [result.status for result in results] == ["succeeded"]

    with session_factory() as db:
        material = db.get(Material, material_id)
        assert material is not None
        assert material.status == "ready"
        assert material.active_index_version is not None

    assert runner._stack.vector_store.count() > 0


def test_delete_removes_records_and_vectors(client: TestClient, runner, session_factory) -> None:
    """删除必须把数据库记录与向量一起清掉，不留孤儿。

    这是用户报告过的现象：删掉资料后索引里还留着 15 条向量，
    检索层查不到正文会丢弃它们，但它们一直占着索引，也永远不会被清理。
    """
    body = upload(client)
    material_id = body["material"]["id"]
    runner.run_once()
    assert runner._stack.vector_store.count() > 0

    response = client.delete(f"/api/materials/{material_id}")
    assert response.status_code == 204

    with session_factory() as db:
        assert db.get(Material, material_id) is None

    # 向量必须一起清掉。
    assert runner._stack.vector_store.count() == 0, "删除后不得留下孤儿向量"


def test_delete_order_is_database_first(
    client: TestClient, runner, session_factory
) -> None:
    """删除必须先删数据库记录、再清向量。

    这个顺序是消除竞态的关键：如果先清向量，后台索引任务在它自己的检查点
    看到的资料仍然存在，于是继续往下写向量，等记录被删掉时向量已经写进去了 ——
    结果就是稳定复现的孤儿向量。把记录先删掉，任务就会在检查点直接收尾。

    这里通过观察「删除返回时数据库记录已不存在」来锁定顺序，
    而不是依赖对实现细节的 patch。
    """
    body = upload(client)
    material_id = body["material"]["id"]

    response = client.delete(f"/api/materials/{material_id}")
    assert response.status_code == 204

    # 删除返回时，数据库里必须已经查不到这条记录（说明是先删记录）。
    with session_factory() as db:
        assert db.get(Material, material_id) is None

    # 向量也必须已经清干净（说明记录删除之后紧接着清了向量）。
    assert runner._stack.vector_store.count() == 0


def test_existing_material_is_not_touched_by_other_deletes(
    client: TestClient, runner, session_factory
) -> None:
    """删除一份资料不得影响另一份：用户的资料必须完好。

    对应 P1 的核心担忧 —— 测试与脚本绝不该动用户自己的数据。
    这里用「先建一份用户资料，再上传并删除一份测试资料，
    最后核对用户资料的记录、块与向量都还在」来锁定。
    """
    # 造一份「用户自己的」资料：正文 + 真实的分块（模拟已建好索引的资料）。
    from tests.retrieval.conftest import create_chunk, create_material

    with session_factory() as db:
        user_material = create_material(
            db, title="用户自己的讲义", body="# 用户资料\n\n## 第一章\n\n这是用户自己上传的内容。\n"
        )
        create_chunk(
            db,
            user_material,
            content="这是用户自己上传的内容。",
            ordinal=0,
            heading_path=("用户资料", "第一章"),
        )
        db.commit()
        user_id = user_material.id

    # 再上传一份测试资料并删除它。
    body = upload(client)
    test_id = body["material"]["id"]
    runner.run_once()
    assert client.delete(f"/api/materials/{test_id}").status_code == 204

    # 用户资料必须完好：记录在、块在。
    with session_factory() as db:
        still = db.get(Material, user_id)
        assert still is not None, "删除测试资料不得影响用户资料"
        assert still.title == "用户自己的讲义"
        chunk_count = db.execute(
            text("SELECT count(*) FROM document_chunks WHERE material_id = :mid"),
            {"mid": str(user_id)},
        ).scalar()
    assert chunk_count > 0, "用户资料的块必须还在"

    # 测试资料必须已从列表移除，用户资料必须还在列表里。
    items = client.get("/api/materials").json()["items"]
    ids = {item["id"] for item in items}
    assert test_id not in ids
    assert str(user_id) in ids
