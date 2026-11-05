"""`matched_kp` 归因测试：语义阈值与「明显领先」是硬要求。

契约 §5：`matched_kp` 只能由最终 hits 的 `chunk_knowledge_points` 计算 ——
第一名必须**语义相关度过阈值**且**明显领先第二名**，否则 `null`。
禁止从用户问题、前端字段或 LLM 文本里取知识点。

为什么这两个条件必须真的生效：`matched_kp` 决定「推荐哪些追练题」。
归因错了，用户会被推去做与问题无关的题 —— 比不推荐更糟。

判据的量化口径（两个判据建在不同量纲上，这是刻意的）：
- **语义阈值** `KP_MIN_COSINE` 比的是**原始向量余弦相似度**（`hit.vector_score`）。
  绝不能用 RRF 融合分：它只反映名次，第一名必然是约 0.0164，
  实测越界问题（知识库里根本没有）也能拿到 0.0315，比正常用例的最低值还高。
- **领先度** `KP_LEAD_RATIO` 比的是累积分 Σ（score × 1/名次），
  它衡量「被多少条命中、排得多前」，与量纲无关。
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import pytest

from backend.chat.service import (
    KP_LEAD_RATIO,
    KP_MIN_COSINE,
    compute_matched_kp,
    matched_kp_attribution,
)

KP_LIMIT = UUID("00000000-0000-0000-0000-000000000101")
KP_DERIVATIVE = UUID("00000000-0000-0000-0000-000000000102")


@dataclass(frozen=True)
class Hit:
    """检索命中的最小替身。

    `score` 是融合分（只影响累积分与排序），
    `vector_score` 是原始余弦（才是语义阈值的依据）—— 两者必须分开给，
    否则测不出「阈值建在哪个量纲上」这件事。
    """

    kp_ids: tuple[UUID, ...]
    score: float
    vector_score: float | None = None


def hit(score: float, *kp_ids: UUID, cosine: float = 0.8) -> Hit:
    """构造一个命中：融合分 `score`，原始余弦 `cosine`（默认明显相关）。"""
    return Hit(kp_ids=tuple(kp_ids), score=score, vector_score=cosine)


def strong() -> float:
    """一个明显高于阈值的融合分（用于累积分为主的判据）。"""
    return 0.03


# ---------------------------------------------------------------------------
# 基本归因
# ---------------------------------------------------------------------------


def test_single_clear_winner_is_attributed() -> None:
    assert compute_matched_kp([hit(strong(), KP_LIMIT), hit(0.0001)]) == KP_LIMIT


def test_no_hits_returns_none() -> None:
    assert compute_matched_kp([]) is None


def test_hits_without_any_kp_link_return_none() -> None:
    """没有显式关联（`<!-- kp: -->` 标记）时不得归因。"""
    assert compute_matched_kp([hit(0.5), hit(0.4)]) is None


def test_higher_rank_carries_more_weight() -> None:
    """两块同分、各带一个知识点：靠前那个得分翻倍，明确归因。"""
    equal = strong()
    assert compute_matched_kp([hit(equal, KP_LIMIT), hit(equal, KP_DERIVATIVE)]) == KP_LIMIT


def test_multiple_hits_agreeing_on_same_kp_is_attributed() -> None:
    """多个命中都指向同一个知识点：累积得分，明确归因。"""
    hits = [
        hit(strong(), KP_LIMIT),
        hit(strong(), KP_LIMIT),
        hit(strong() / 3, KP_DERIVATIVE),
    ]
    assert compute_matched_kp(hits) == KP_LIMIT


# ---------------------------------------------------------------------------
# 语义阈值：相关度太低不归因（判据建在原始余弦上）
# ---------------------------------------------------------------------------


def test_low_cosine_returns_none() -> None:
    """余弦低于阈值就不归因 —— 哪怕融合分很高。"""
    assert compute_matched_kp([hit(strong(), KP_LIMIT, cosine=KP_MIN_COSINE / 2)]) is None


def test_solo_kp_below_cosine_threshold_returns_none() -> None:
    """只有一个知识点在竞争，但语义相关度太低 —— 仍然不归因。"""
    assert compute_matched_kp([hit(strong(), KP_LIMIT, cosine=0.2)]) is None


def test_solo_kp_above_cosine_threshold_is_attributed() -> None:
    assert compute_matched_kp([hit(strong(), KP_LIMIT, cosine=0.9)]) == KP_LIMIT


def test_out_of_scope_query_is_not_attributed() -> None:
    """真实越界问题的回归：必须不归因。

    数据来自真实 embedding 模型的实测 —— 问「这个软件怎么安装」「今天天气怎么样」
    时，知识库里根本没有相关内容，最高余弦只有约 0.34；
    但它们的 RRF 融合分仍有约 0.03（因为 RRF 只看名次）。

    这正是旧实现的错误：阈值曾写成「融合分 > 0.01」，比所有实测值都低，
    于是越界问题照样被归因到某个叶子知识点，进而给出无关的追练候选。
    """
    # 越界实测 cosine = 0.3368
    assert compute_matched_kp([hit(0.0315, KP_LIMIT, cosine=0.3368)]) is None
    assert compute_matched_kp([hit(0.0292, KP_LIMIT, cosine=0.2900)]) is None
    # 对照：真实命中最低 cosine = 0.5673，必须仍然归因
    assert compute_matched_kp([hit(0.0164, KP_LIMIT, cosine=0.5673)]) == KP_LIMIT


def test_keyword_only_hit_is_not_attributed() -> None:
    """纯关键词命中（没有向量分）不做语义判断 → 不归因。

    宁可返回 null 让人工核对，也不要靠「词面像」就给出一个可能无关的知识点。
    """
    assert compute_matched_kp([hit(strong(), KP_LIMIT, cosine=None)]) is None  # type: ignore[arg-type]


def test_weak_single_block_is_not_attributed_even_if_repeated() -> None:
    """阈值看的是**最佳命中的相关度**，不是累积分。

    为什么：把多个弱命中累加成一个高分，会让「一堆噪声凑出归因」，
    那正是 matched_kp 最该避免的事。阈值必须卡在真实命中的强度上。
    """
    weak = 0.1
    hits = [
        hit(strong(), KP_LIMIT, cosine=weak),
        hit(strong(), KP_LIMIT, cosine=weak),
        hit(strong(), KP_LIMIT, cosine=weak),
    ]
    assert compute_matched_kp(hits) is None


def test_many_strong_hits_on_same_kp_are_attributed() -> None:
    """同一知识点被多个**足够强**的命中支持：明确归因。"""
    hits = [hit(strong(), KP_LIMIT), hit(strong(), KP_LIMIT), hit(strong(), KP_LIMIT)]
    assert compute_matched_kp(hits) == KP_LIMIT


# ---------------------------------------------------------------------------
# 领先度：咬得太紧不归因
# ---------------------------------------------------------------------------


def test_close_second_place_returns_none() -> None:
    """第二名紧咬第一名：返回 None，而不是随便选一个。

    构造：两块同分且各带一个知识点时，靠前的权重是 1.0、靠后是 0.5，
    比例正好 2.0 —— 那是「明确领先」。这里把第二块分数抬高到比例不足 1.5。
    """
    top = strong()
    # 第二块分数 = top * (KP_LEAD_RATIO - 0.1) / 0.5，使总得分比刚好低于 1.5
    close_second = top * (KP_LEAD_RATIO - 0.1)
    hits = [hit(top, KP_LIMIT), hit(close_second, KP_DERIVATIVE)]
    assert compute_matched_kp(hits) is None


def test_clear_lead_is_attributed() -> None:
    """第一名显著领先第二名时归因。"""
    hits = [hit(strong() * 3, KP_LIMIT), hit(strong() / 4, KP_DERIVATIVE)]
    assert compute_matched_kp(hits) == KP_LIMIT


def test_lead_ratio_boundary() -> None:
    """刚好达到领先比例时应当归因（边界包含）。"""
    top = strong()
    # 让第二名 kp 的总得分 = top / KP_LEAD_RATIO
    runner_up_block = (top / KP_LEAD_RATIO) / 0.5
    hits = [hit(top, KP_LIMIT), hit(runner_up_block, KP_DERIVATIVE)]
    assert compute_matched_kp(hits) == KP_LIMIT


# ---------------------------------------------------------------------------
# 一个块带多个知识点
# ---------------------------------------------------------------------------


def test_one_chunk_with_three_kps_returns_none() -> None:
    """单块挂了三个知识点：三者完全同分，谈不上「明显领先」，返回 None。

    这是「宁可 null 也不硬猜」的直接体现：一个块同时属于多个知识点时，
    无法判断用户问的是哪一个，归因到任意一个都会误导追练推荐。
    """
    third = UUID("00000000-0000-0000-0000-000000000103")
    assert compute_matched_kp([hit(strong(), KP_LIMIT, KP_DERIVATIVE, third)]) is None


def test_multi_kp_on_first_hit_with_other_hits_still_works() -> None:
    """第一块带两个 kp、后面还有别的块：仍然要能给出稳定结果或 None。"""
    hits = [hit(strong(), KP_LIMIT, KP_DERIVATIVE), hit(strong() / 10)]
    result = compute_matched_kp(hits)
    assert result in {KP_LIMIT, KP_DERIVATIVE, None}


# ---------------------------------------------------------------------------
# 稳定性与不变量
# ---------------------------------------------------------------------------


def test_result_is_deterministic() -> None:
    hits = [hit(strong(), KP_LIMIT), hit(0.001, KP_DERIVATIVE)]
    assert compute_matched_kp(hits) == compute_matched_kp(hits)


def test_result_is_stable_for_the_same_input() -> None:
    """同一输入必须永远得到同一结果（契约要求可复现）。"""
    hits = [hit(strong(), KP_LIMIT), hit(strong() * 0.2, KP_DERIVATIVE)]
    assert compute_matched_kp(hits) == compute_matched_kp(hits) == KP_LIMIT


def test_conflicting_rank_and_score_signals_return_none() -> None:
    """名次与分数给出**冲突**结论时不归因。

    场景：A 块的分数高得多，但它排在 B 块之后。分数与名次都源自 RRF
    融合结果，两者冲突说明这次检索本身不够确定 —— 此时硬选一个，
    就会把用户推向可能与问题无关的追练题。宁可返回 None。
    """
    strong_a = strong()
    weak_b = strong() * 0.2
    # 分数高但名次靠后：名次优先，累积分不占优 → None
    assert compute_matched_kp([hit(weak_b, KP_DERIVATIVE), hit(strong_a, KP_LIMIT)]) is None
    # 分数高且名次也靠前：明确归因
    assert compute_matched_kp([hit(strong_a, KP_LIMIT), hit(weak_b, KP_DERIVATIVE)]) == KP_LIMIT


def test_thresholds_are_positive() -> None:
    """阈值必须是正数：为 0 或负数会让弱命中也被归因。

    余弦阈值还必须**高于实测的越界相关度**（约 0.34），
    否则「弱命中不归因」又会退化成一句空话。
    """
    assert KP_MIN_COSINE > 0
    assert KP_MIN_COSINE > 0.34, "阈值必须高于实测越界相关度，否则门槛形同虚设"
    assert KP_MIN_COSINE < 0.5673, "也不该高于实测真实命中的最低相关度，否则几乎永不归因"
    assert KP_LEAD_RATIO > 1.0


def test_zero_score_hits_are_never_attributed() -> None:
    """融积分全为 0 时不归因：0 的若干倍仍是 0，谈不上「明显领先」。"""
    assert compute_matched_kp([hit(0.0, KP_LIMIT)]) is None


def test_attribution_records_the_cosine_it_judged_on() -> None:
    """归因依据里必须留下当时用的余弦 —— 否则事后无法解释「凭什么归到它」。"""
    found = matched_kp_attribution([hit(strong(), KP_LIMIT, cosine=0.7234)])
    assert found is not None
    assert found.cosine == pytest.approx(0.7234)
    assert found.as_dict()["cosine"] == pytest.approx(0.7234, abs=1e-6)
