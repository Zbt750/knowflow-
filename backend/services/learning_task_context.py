"""Lossless factoring for model-facing tool data; audit traces stay complete."""
from copy import deepcopy
import json


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def pack_records(value):
    """Lossless column view of homogeneous records, not a semantic summary.

    Repeated names and common values are encoded once. Differently shaped rows,
    missing keys, nulls and scalar types are never conflated or discarded.
    """
    if isinstance(value, dict):
        return {key: pack_records(item) for key, item in value.items()}
    if not isinstance(value, list):
        return value
    ordinary = [pack_records(item) for item in value]
    if len(value) < 3 or not all(isinstance(row, dict) for row in value):
        return ordinary
    keys = list(value[0])
    if not keys or not all(set(row) == set(keys) for row in value):
        return ordinary
    columns = {}
    for key in keys:
        items = [row[key] for row in value]
        if all(_canonical(item) == _canonical(items[0]) for item in items):
            columns[key] = {"repeat": pack_records(items[0])}
        else:
            columns[key] = {"values": pack_records(items)}
    encoded = {"$records": len(value), "columns": columns}
    return encoded if len(_canonical(encoded).encode()) < len(_canonical(ordinary).encode()) else ordinary


def expand_records(value):
    """Executable description of the model protocol for offline round-trip QA."""
    if isinstance(value, dict) and set(value) == {"$records", "columns"}:
        size = value["$records"]
        columns = {key: [expand_records(cell["repeat"]) for _ in range(size)]
                   if "repeat" in cell else expand_records(cell["values"])
                   for key, cell in value["columns"].items()}
        return [{key: items[index] for key, items in columns.items()} for index in range(size)]
    if isinstance(value, dict):
        return {key: expand_records(item) for key, item in value.items()}
    if isinstance(value, list):
        return [expand_records(item) for item in value]
    return value


def compact_tool_result(result):
    result = deepcopy(result)
    container = result.get("draft") if isinstance(result.get("draft"), dict) else result
    questions = container.get("questions")
    if not isinstance(questions, list) or not questions:
        return result
    trusts = [q.get("question_trust") for q in questions]
    if all(isinstance(t, dict) for t in trusts):
        common = {k: v for k, v in trusts[0].items() if all(k in t and _canonical(t[k]) == _canonical(v) for t in trusts)}
        if common:
            container["question_trust_defaults"] = common
            for q, trust in zip(questions, trusts):
                if "eligibility_snapshot" in q and _canonical(q["eligibility_snapshot"]) == _canonical(trust):
                    del q["eligibility_snapshot"]
                    q["eligibility_snapshot_ref"] = "question_trust"
                q["question_trust"] = {k: v for k, v in trust.items() if k not in common}
    return result


def compact_model_messages(messages):
    """Keep every distinct result; identical later results replace earlier copies."""
    output = deepcopy(messages)
    seen = {}
    for i, message in enumerate(output):
        if message.get("role") not in {"tool", "user"} or not isinstance(message.get("content"), str):
            continue
        try:
            data = json.loads(message["content"])
        except ValueError:
            continue
        if not isinstance(data, dict):
            continue
        # Equality includes all result facts, not just the tool name or scope.
        key = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if message.get("role") == "tool":
            if key in seen:
                output[seen[key]]["content"] = json.dumps({"same_result_as_tool_call_id": message["tool_call_id"]})
            seen[key] = i
            data = compact_tool_result(data)
        message["content"] = _canonical(pack_records(data))
    return output
