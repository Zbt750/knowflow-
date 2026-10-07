"""Resolve independent document mentions without dropping shorter titles or guessing files."""
from __future__ import annotations

import re
from difflib import SequenceMatcher


def normalized_name(value: str) -> str:
    return re.sub(r"[\W_]+", "", value.casefold())


def aliases(material) -> set[str]:
    names = {material.title}
    if re.search(r"\.(md|txt|pdf|docx)$", material.title, re.I):
        names.add(material.title.rsplit(".", 1)[0])
    filename = getattr(material, "original_filename", None)
    if filename:
        names.update((filename, filename.rsplit(".", 1)[0]))
    # Conservative lexical abbreviations; years/versions and topic words stay intact.
    if "讲义" in material.title:
        names.add(re.sub(r"与|和|专题", "", material.title))
    return {normalized_name(name) for name in names if len(normalized_name(name)) >= 2}


def mention_groups(materials, question: str) -> list[list]:
    query = normalized_name(question)
    occurrences = []
    for material in materials:
        names = aliases(material)
        # Only accept literal trailing shorthand when the user explicitly names
        # a document. Keep all matching versions so ambiguity is not hidden.
        title = normalized_name(material.title.rsplit('.', 1)[0] if re.search(r'\.(md|txt|pdf|docx)$', material.title, re.I) else material.title)
        for length in range(4, len(title)):
            suffix = title[-length:]
            if re.search(re.escape(suffix) + r'(?:这份|这个|那份|那个)?(?:文件|资料|文档)', query):
                names.add(suffix)
        for name in names:
            for match in re.finditer(re.escape(name), query):
                prefix = query[max(0, match.start()-12):match.start()]
                if re.search(r"(?:不要|不必|禁止)(?:读取|阅读|使用|参考|读|看)$", prefix):
                    continue
                occurrences.append((match.start(), match.end(), material))
    # A short title inside a longer mention is not a second explicit file selection.
    # A short title mentioned elsewhere is kept, regardless of global name length.
    maximal = [item for item in occurrences if not any(
        other[0] <= item[0] and item[1] <= other[1]
        and (other[0], other[1]) != (item[0], item[1])
        for other in occurrences
    )]
    grouped = {}
    for start, end, material in maximal:
        grouped.setdefault((start, end), {})[material.id] = material
    return [list(grouped[span].values()) for span in sorted(grouped)]


def matching_materials(materials, question: str) -> list:
    found = {}
    for group in mention_groups(materials, question):
        for material in group:
            found[material.id] = material
    return list(found.values())


def ambiguous_mentions(materials, question: str) -> bool:
    return any(len(group) > 1 for group in mention_groups(materials, question))


def filename_suggestion(materials, question: str) -> str | None:
    """Suggest close names for confirmation; never silently read a fuzzy match."""
    quoted = re.findall(r"《([^》]+)》", question)
    suggestions = []
    for name in quoted:
        target = normalized_name(name)
        if len(target) < 4:
            continue
        if any(target in aliases(material) for material in materials):
            continue
        for material in materials:
            candidate = normalized_name(material.title)
            if SequenceMatcher(None, target, candidate).ratio() >= 0.80:
                suggestions.append(material.title)
    names = list(dict.fromkeys(suggestions))[:3]
    if names:
        return "没有精确匹配到该资料名。你是否指" + "、".join(f"《{name}》" for name in names) + "？请确认完整资料名后，我再读取，避免读错文件。"
    return None
