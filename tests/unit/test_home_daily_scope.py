from uuid import uuid4
from backend.services.home_recommendation_service import _referenced_scope


def test_remove_displayed_third_node_uses_current_preview_order():
    ids=[uuid4() for _ in range(4)]
    previous={'selected_kp_ids':[str(x) for x in reversed(ids)],'questions':[{'kp_id':str(x)} for x in ids]}
    assert _referenced_scope('把刚才推荐的第三个知识点去掉。',previous,None)==[ids[0],ids[1],ids[3]]


def test_keep_two_and_add_resolved_rank_node_preserves_both_parts():
    ids=[uuid4() for _ in range(4)];extra=uuid4()
    previous={'selected_kp_ids':[str(x) for x in ids]}
    assert _referenced_scope('保留前两个知识点，再增加矩阵的秩。',previous,[extra])==ids[:2]+[extra]
    assert _referenced_scope('保留前两个知识点，再增加不存在节点。',previous,None)==[]


def test_invalid_index_never_silently_substitutes_another_scope():
    ids=[uuid4(),uuid4()];previous={'selected_kp_ids':[str(x) for x in ids]}
    assert _referenced_scope('把刚才推荐的第三个知识点去掉',previous,None)==[]
    assert _referenced_scope('正常数学问题',previous,None) is None
