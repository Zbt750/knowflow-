"""受控评测快照：从最终 prompt 读取，不重新检索或重新拼装原文。"""
from hashlib import sha256


def build_evidence_blocks(hits):
    """在提示词构造边界生成片段，正文中的伪引用不会成为分割标记。"""
    blocks = []
    for i, hit in enumerate(hits, 1):
        title = getattr(hit, "material_title", "") or "未命名资料"
        headings = list(getattr(hit, "heading_path", ()) or ())
        context = f"[C{i}] 【资料：{title}{'｜章节：' + ' › '.join(headings) if headings else ''}】\n{hit.content}"
        blocks.append({"label": f"C{i}", "chunk_id": str(hit.chunk_id),
                       "material_title": title, "heading_path": headings,
                       "context": context})
    return tuple(blocks)


def evidence_snapshot(prepared):
    # _prompt 把当前轮证据放在最后一个问题之前；历史中的同名标记不算证据。
    prompt = prepared.prompt
    evidence = ""
    if len(prompt) >= 2:
        candidate = prompt[-2]
        prefix = "【资料证据】\n"
        if candidate.get("role") == "user" and candidate.get("content", "").startswith(prefix):
            evidence = candidate["content"][len(prefix):]
    blocks = [dict(block, heading_path=list(block["heading_path"]))
              for block in getattr(prepared, "evidence_blocks", ())]
    contexts = [block["context"] for block in blocks]
    citations = {label: str(chunk) for label, chunk in prepared.citation_map.items()}
    if "\n\n".join(contexts) != evidence or {b["label"]: b["chunk_id"] for b in blocks} != citations:
        raise ValueError("实际证据块与最终提示词不一致")
    return {
        "version": "actual-model-evidence-v2",
        "request_id": str(prepared.assistant_id),
        "model_called": bool(prompt),
        "contexts": contexts,
        "blocks": blocks,
        "evidence_sha256": sha256(evidence.encode("utf-8")).hexdigest(),
        "citations": citations,
        "retrieval_query_context": dict(getattr(prepared, "retrieval_query_context", None) or {}),
        "context_screening": dict(getattr(prepared, "context_screening", None) or {}),
    }


def validate_evidence_snapshot(snapshot, message_id):
    """评分前拒绝旧版、错轮次、缺片段、乱序和被修改的快照。"""
    if not isinstance(snapshot, dict) or snapshot.get("version") != "actual-model-evidence-v2":
        raise ValueError("缺少本轮逐片段实际证据快照")
    if not message_id or snapshot.get("request_id") != message_id:
        raise ValueError("实际证据快照消息标识不一致")
    contexts, blocks, citations = (snapshot.get(key) for key in ("contexts", "blocks", "citations"))
    if not isinstance(contexts, list) or any(not isinstance(c, str) for c in contexts):
        raise ValueError("实际证据上下文格式无效")
    if not isinstance(blocks, list) or any(not isinstance(b, dict) for b in blocks) or not isinstance(citations, dict):
        raise ValueError("实际证据块格式无效")
    labels = [f"C{i}" for i in range(1, len(blocks) + 1)]
    if ([b.get("context") for b in blocks] != contexts
            or [b.get("label") for b in blocks] != labels
            or any(not isinstance(b.get("chunk_id"), str) or not b["chunk_id"] for b in blocks)
            or {b.get("label"): b.get("chunk_id") for b in blocks} != citations):
        raise ValueError("实际证据块与来源映射不一致")
    if sha256("\n\n".join(contexts).encode("utf-8")).hexdigest() != snapshot.get("evidence_sha256"):
        raise ValueError("实际证据快照校验和不一致")
    return blocks, contexts
