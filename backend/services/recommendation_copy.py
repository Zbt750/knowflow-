"""Punctuation only; never changes recommendation facts."""
import re


def recommendation_sentence(text: str) -> str:
    value = text.strip()
    if not value:
        return ""
    if value.endswith(("！", "？", "!", "?")):
        return value
    return re.sub(r"[。.]+$", "", value) + "。"
