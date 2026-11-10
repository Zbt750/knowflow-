from types import SimpleNamespace
from uuid import uuid4

from backend.services.question_similarity import version_similarity_basis


def version(kp_id, question_type, tags, group=None):
    return SimpleNamespace(id=uuid4(), question_id=uuid4(), kp_id=kp_id,
        question_type=question_type, skill_tags=tags, variant_group=group)


def test_question_similarity_requires_specific_shared_evidence_and_same_type():
    kp_id = uuid4()
    node = SimpleNamespace(id=kp_id, name="隐函数求导", code="math.implicit")
    reference = version(kp_id, "single_choice", ["隐函数求导", "二阶导数"])

    same_topic_only = version(kp_id, "single_choice", ["隐函数求导"])
    different_type = version(kp_id, "fill_blank", ["二阶导数"])
    valid_shared_skill = version(kp_id, "single_choice", ["二阶导数"])

    assert version_similarity_basis(reference, same_topic_only, node) is None
    assert version_similarity_basis(reference, different_type, node) is None
    basis = version_similarity_basis(reference, valid_shared_skill, node)
    assert basis == {
        "same_knowledge_point": True,
        "same_question_type": True,
        "shared_skill_tags": ["二阶导数"],
        "same_variant_group": False,
        "reference_question_id": str(reference.question_id),
        "reference_version_id": str(reference.id),
    }


def test_same_versioned_variant_group_is_usable_without_skill_tags():
    kp_id = uuid4()
    node = SimpleNamespace(id=kp_id, name="洛必达法则", code="math.lhopital")
    reference = version(kp_id, "calculation", ["洛必达法则"], "limit-rule-v2")
    candidate = version(kp_id, "calculation", ["洛必达法则"], "limit-rule-v2")

    basis = version_similarity_basis(reference, candidate, node)
    assert basis is not None
    assert basis["shared_skill_tags"] == []
    assert basis["same_variant_group"] is True
