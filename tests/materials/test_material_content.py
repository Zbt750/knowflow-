"""资料阅读接口的直接契约测试。"""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from tests.retrieval.conftest import create_material


def test_content_returns_title_and_normalized_text(client: TestClient, session_factory) -> None:
    with session_factory() as db:
        material = create_material(db, title="阅读测试讲义", body="# 第一章\n\n正文内容。")
        material_id = material.id
        expected_text = material.normalized_text
        db.commit()

    response = client.get(f"/api/materials/{material_id}/content")
    assert response.status_code == 200
    assert response.json() == {"title": "阅读测试讲义", "text": expected_text}


def test_content_missing_material_returns_404(client: TestClient) -> None:
    response = client.get(f"/api/materials/{uuid4()}/content")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "material_not_found"
