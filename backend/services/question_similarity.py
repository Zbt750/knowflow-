"""One version-pinned policy for finding formally similar practice questions."""
from __future__ import annotations


_GENERIC_TAGS = {
    "基础", "中等", "较难", "练习题", "同知识点", "同一知识点", "同考点", "同一考点",
}


def specific_skill_tags(tags, *, knowledge_point_name: str | None = None,
                        knowledge_point_code: str | None = None) -> set[str]:
    """Remove topic labels and broad level labels; keep only discriminating skills."""
    generic = set(_GENERIC_TAGS)
    if knowledge_point_name:
        generic.add(knowledge_point_name.strip())
    if knowledge_point_code:
        generic.add(knowledge_point_code.strip())
    return {tag.strip() for tag in (tags or [])
        if isinstance(tag, str) and tag.strip() and tag.strip() not in generic}


def version_similarity_basis(reference_version, candidate_version, knowledge_point) -> dict | None:
    """Require a shared assessable topic, same question type, and skill/group evidence."""
    if (reference_version is None or candidate_version is None or knowledge_point is None
            or reference_version.kp_id != candidate_version.kp_id
            or reference_version.kp_id != knowledge_point.id
            or reference_version.question_type != candidate_version.question_type):
        return None
    reference_tags = specific_skill_tags(reference_version.skill_tags,
        knowledge_point_name=knowledge_point.name, knowledge_point_code=knowledge_point.code)
    candidate_tags = specific_skill_tags(candidate_version.skill_tags,
        knowledge_point_name=knowledge_point.name, knowledge_point_code=knowledge_point.code)
    shared_tags = sorted(reference_tags.intersection(candidate_tags))
    same_group = bool(reference_version.variant_group
        and reference_version.variant_group == candidate_version.variant_group)
    if not shared_tags and not same_group:
        return None
    return {
        "same_knowledge_point": True,
        "same_question_type": True,
        "shared_skill_tags": shared_tags,
        "same_variant_group": same_group,
        "reference_question_id": str(reference_version.question_id),
        "reference_version_id": str(reference_version.id),
    }
