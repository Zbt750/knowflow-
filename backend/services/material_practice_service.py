"""资料 → 个人练习：复用资料正文与个人题生成服务，不进入公共题库或今日卷。"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from backend.errors import AppError
from backend.models.learning import KnowledgePoint
from backend.models.rag import Material
from backend.schemas.material_practice import MaterialPracticeRequest
from backend.schemas.personal_questions import GenerationTarget, PersonalGenerationRequest
from backend.services.personal_question_service import run_generation

# PersonalGenerationRequest.reference_text 的硬上限；资料正文更长时只带前
# MATERIAL_REFERENCE_LIMIT 个字符。生成预算按 UTF-8 字节硬限 8000，中文资料
# 若带满 6000 字会先撞预算，因此这里按可出题的最小充分片段截断，并在来源里
# 保留完整资料标识，避免假装读全。
MATERIAL_REFERENCE_LIMIT = 1200


def _validated_material(db: Session, material_id: UUID) -> Material:
    material = db.get(Material, material_id)
    if material is None:
        raise AppError("material_not_found", status_code=404)
    if material.status != "ready" or not material.active_index_version:
        raise AppError("material_not_ready", status_code=409)
    text = (material.normalized_text or "").strip()
    if not text:
        raise AppError("material_content_empty", status_code=422)
    return material


def _validated_nodes(db: Session, kp_ids: list[UUID]) -> list[KnowledgePoint]:
    unique = list(dict.fromkeys(kp_ids))
    nodes: list[KnowledgePoint] = []
    for kp_id in unique:
        node = db.get(KnowledgePoint, kp_id)
        if node is None:
            raise AppError("knowledge_point_not_found", status_code=404)
        if not node.is_active or not node.is_assessable or node.is_reference_only:
            raise AppError("personal_training_node_not_assessable", status_code=422)
        nodes.append(node)
    return nodes


def build_request(
    db: Session, *, material_id: UUID, body: MaterialPracticeRequest
) -> tuple[PersonalGenerationRequest, Material]:
    material = _validated_material(db, material_id)
    nodes = _validated_nodes(db, body.knowledge_point_ids)
    selected = nodes[: min(len(nodes), body.question_count)]
    counts = [1] * len(selected)
    counts[0] += body.question_count - len(selected)
    text = (material.normalized_text or "").strip()[:MATERIAL_REFERENCE_LIMIT]
    requirement = body.user_requirement or f"基于资料《{material.title}》出题，考查资料中的方法与例题，不要照抄原文。"
    request = PersonalGenerationRequest(
        request_key=body.request_key,
        generation_mode="ai_generated",
        targets=[
            GenerationTarget(
                kp_id=node.id,
                question_type=body.question_type,
                count=count,
                difficulty=body.difficulty,
            )
            for node, count in zip(selected, counts)
        ],
        surface="chat",
        reference_text=text,
        reference_source={
            "type": "material",
            "material_id": str(material.id),
            "material_title": material.title,
            "reference_limit_chars": MATERIAL_REFERENCE_LIMIT,
        },
        user_requirement=requirement,
    )
    return request, material


def generate_from_material(
    factory,
    *,
    material_id: UUID,
    body: MaterialPracticeRequest,
    provider,
    now: datetime,
) -> dict:
    with factory() as db:
        request, material = build_request(db, material_id=material_id, body=body)
        title = material.title
    result = run_generation(factory, request, provider, now=now)
    return {
        **result,
        "material_id": str(material_id),
        "material_title": title,
        "request_key": str(body.request_key),
    }
