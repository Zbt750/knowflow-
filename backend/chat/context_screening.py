"""Opt-in, bounded ordinary-query screening; never use rank scores as relevance.

The threshold is a versioned experimental candidate, not a universal guarantee.
Keep this disabled by default until actual-answer validation is authorized.
"""
from dataclasses import dataclass
import math
from typing import Literal, Sequence

POLICY_VERSION = "ordinary-cosine-screen-v1"
MIN_COSINE = 0.50
ScreeningMode = Literal["off", "shadow", "filter"]


@dataclass(frozen=True)
class ScreeningResult:
    hits: list
    diagnostic: dict[str, object]


def screen_context(hits: Sequence, *, mode: ScreeningMode, bypass_reason: str | None = None) -> ScreeningResult:
    if mode not in {"off", "shadow", "filter"}:
        raise ValueError("Invalid context screening mode")
    original = list(hits)
    diagnostic = {"version": POLICY_VERSION, "mode": mode, "threshold": MIN_COSINE,
                  "before_count": len(original), "after_count": len(original),
                  "would_remove_count": 0, "removed_count": 0,
                  "unknown_score_count": 0, "applied": False,
                  "reason": "disabled" if mode == "off" else bypass_reason or "eligible"}
    if mode == "off" or bypass_reason:
        return ScreeningResult(original, diagnostic)
    kept = []
    for hit in original:
        raw = getattr(hit, "vector_score", None)
        # A keyword-only hit or unobserved/invalid vector score is not low relevance.
        if not isinstance(raw, (int, float)) or isinstance(raw, bool) or not math.isfinite(raw):
            diagnostic["unknown_score_count"] += 1
            kept.append(hit)
        elif raw >= MIN_COSINE:
            kept.append(hit)
    removed = len(original) - len(kept)
    diagnostic["would_remove_count"] = removed
    if mode == "filter":
        diagnostic.update(after_count=len(kept), removed_count=removed, applied=True)
        return ScreeningResult(kept, diagnostic)
    return ScreeningResult(original, diagnostic)
