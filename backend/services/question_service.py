from __future__ import annotations

import re


class DuplicateQuestionStemError(ValueError):
    """同一知识点内存在高度相似题干时抛出。"""


def normalize_stem(stem: str) -> str:
    # 只去格式噪声；汉字、数字和公式正文仍保留，避免把不同题误当成同题。
    return re.sub(r"[\s，。！？；：、,.!?;:]+", "", stem).lower()


def _trigrams(text: str) -> set[str]:
    # 三字符片段让“只改少量字”的题仍有很高交集；短字符串单独当作一个片段。
    if len(text) < 3:
        return {text} if text else set()
    return {text[index : index + 3] for index in range(len(text) - 2)}


def stem_similarity(left: str, right: str) -> float:
    # Jaccard = 交集 / 并集，结果在 0 到 1；两边都为空时定义为 1，避免 0/0。
    left_grams = _trigrams(normalize_stem(left))
    right_grams = _trigrams(normalize_stem(right))
    if not left_grams and not right_grams:
        return 1.0
    return len(left_grams & right_grams) / len(left_grams | right_grams)


def assert_not_duplicate_stem(
    stem: str, existing_stems: list[str], *, threshold: float = 0.85
) -> None:
    """seed / 题目录入先查同一 kp 的旧题干，再把结果交给这个纯函数判断。"""
    if not stem.strip():
        raise DuplicateQuestionStemError("duplicate_question_stem")
    for existing_stem in existing_stems:
        if stem_similarity(stem, existing_stem) >= threshold:
            raise DuplicateQuestionStemError("duplicate_question_stem")