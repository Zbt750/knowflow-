"""End-to-end RAGAS evaluation for the local chat API.

This is intentionally an optional evaluation tool, not an application runtime
dependency. It exercises the real chat SSE endpoint, captures first-token and
total latency, fetches the actual per-block model evidence snapshot, evaluates
Context Precision / Context Recall / Faithfulness with RAGAS, and removes every
temporary chat session it creates.

Safety:
* Refuses to run unless the API reports APP_ENV=test.
* Uses only the test API and fixture material titles in the JSONL dataset.
* Reads the configured LLM key in memory for the judge; never prints or stores it.
* Ordinary reports retain bounded excerpts and metadata; the explicitly isolated
  synthetic v3 baseline also retains complete answer/evidence for diagnosis.

Install the isolated optional requirements, then run from the repository root:
    python -m pip install -r requirements-ragas.txt
    python scripts/run_ragas_chat_eval.py
    python scripts/run_ragas_chat_eval.py --api-base http://127.0.0.1:8001/api
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import ProxyHandler, Request, build_opener


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT / "eval" / "dataset" / "chat_ragas_v2.jsonl"
DEFAULT_API_BASE = "http://127.0.0.1:8001/api"
REQUEST_TIMEOUT_SECONDS = 180
METRIC_TIMEOUT_SECONDS = 120
LOCAL_API_OPENER = build_opener(ProxyHandler({}))


class EvalError(RuntimeError):
    """A safe-to-display evaluation error (does not carry request secrets)."""


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    mode: str
    question: str
    reference: str
    strategy: str
    answerability: str
    material_title: str | None
    required_any_groups: tuple[tuple[str, ...], ...]
    forbidden_any: tuple[str, ...]
    category: str = "legacy"
    setup_questions: tuple[str, ...] = ()


def load_cases(path: Path) -> list[EvalCase]:
    if not path.is_file():
        raise EvalError(f"评测数据集不存在：{path}")
    result: list[EvalCase] = []
    seen: set[str] = set()
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            row = json.loads(raw)
            case = EvalCase(
                case_id=str(row["id"]),
                mode=str(row["mode"]),
                question=str(row["question"]),
                reference=str(row["reference"]),
                strategy=str(row.get("strategy", "search")),
                answerability=str(row.get("answerability", "answerable")),
                material_title=(str(row["material_title"]) if row.get("material_title") else None),
                required_any_groups=tuple(
                    tuple(str(term) for term in group)
                    for group in row.get("required_any_groups", [])
                ),
                forbidden_any=tuple(str(term) for term in row.get("forbidden_any", [])),
                category=str(row.get("category", "legacy")),
                setup_questions=tuple(str(q) for q in row.get("setup_questions", [])),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise EvalError(f"数据集第 {line_no} 行字段无效：{type(exc).__name__}") from exc
        if case.case_id in seen:
            raise EvalError(f"数据集 id 重复：{case.case_id}")
        if case.mode not in {"builtin", "user"}:
            raise EvalError(f"{case.case_id}: mode 只能是 builtin 或 user")
        if case.strategy not in {"search", "overview", "scope_guard"}:
            raise EvalError(f"{case.case_id}: 未知 strategy={case.strategy}")
        if case.answerability not in {"answerable", "unanswerable", "general", "guard"}:
            raise EvalError(f"{case.case_id}: 未知 answerability={case.answerability}")
        seen.add(case.case_id)
        result.append(case)
    if not result:
        raise EvalError("评测数据集没有用例")
    return result


def api_call(api_base: str, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any] | list[dict[str, Any]]:
    payload = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {"Accept": "application/json"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    request = Request(api_base.rstrip("/") + path, data=payload, method=method, headers=headers)
    try:
        with LOCAL_API_OPENER.open(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            if response.status == 204:
                return {}
            value = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        # Do not include raw response bodies, which could echo user content.
        raise EvalError(f"API 请求失败：{method} {path} HTTP {exc.code}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise EvalError(f"API 不可用：{method} {path} ({type(exc).__name__})") from exc
    if not isinstance(value, (dict, list)):
        raise EvalError(f"API 响应结构异常：{method} {path}")
    return value


def validate_local_api_target(api_base: str) -> tuple[str, int | None]:
    """Never send test prompts/materials to an arbitrary API host."""
    parsed = urlsplit(api_base)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path.rstrip("/") != "/api"
    ):
        raise EvalError("安全停止：--api-base 必须是本机 http://localhost:<port>/api 地址")
    return parsed.hostname, parsed.port


def validate_fixture_scope(api_base: str, *, baseline_v3: bool = False) -> None:
    """Require the isolated API to contain only the two approved fixture docs."""
    approved = {
        "builtin": "高等数学核心考点讲义",
        "user": "阶段A验收笔记",
    }
    if baseline_v3:
        approved = {"builtin": ["合成数学条件讲义", "合成408机制讲义"],
                    "user": ["合成项目阶段说明", "合成部署边界补充"]}
    for source_type, expected_title in approved.items():
        result = api_call(
            api_base,
            "GET",
            "/materials?" + urlencode({"limit": 100, "source_type": source_type}),
        )
        items = result.get("items", [])
        total = result.get("total")
        titles = [str(item.get("title", "")) for item in items]
        expected = expected_title if isinstance(expected_title, list) else [expected_title]
        if total != len(items) or sorted(titles) != sorted(expected):
            raise EvalError("安全停止：隔离库资料范围与已批准的合成讲义不一致")


def collect_failed_diagnostic(api_base: str, session_id: str, stream: dict, *, include_content: bool) -> dict:
    """Recover this request only, before cleanup; never requery or score failures."""
    message_id = (stream.get("done") or {}).get("message_id") or (stream.get("meta") or {}).get("message_id")
    result = {"message_id": message_id, "stream_error": stream.get("error"), "total_ms": stream.get("total_ms")}
    if not message_id:
        return {**result, "diagnostic_status": "missing_message_id"}
    try:
        messages = api_call(api_base, "GET", f"/chat/sessions/{session_id}/messages")
        message = next(item for item in messages if item.get("message_id") == message_id)
        result.update(diagnostic_status="recovered", generation_trace=message.get("generation_trace"), status=message.get("status"))
        if include_content:
            result.update(actual_evidence=message.get("evaluation_evidence"), partial_answer=message.get("content", stream.get("answer", "")))
    except Exception as exc:
        result.update(diagnostic_status="recovery_failed", recovery_error_type=type(exc).__name__)
    return result


def has_visible_body(text: str) -> bool:
    """Approximate body latency excluding complete prefixes and Markdown headings."""
    from backend.chat.service import GENERAL_REFERENCE_PREFIX
    if GENERAL_REFERENCE_PREFIX.startswith(text) or text in ("#", "##", "###"):
        return False
    text = text.replace(GENERAL_REFERENCE_PREFIX, "")
    return any(line.strip() and not re.match(r"^\s*#{1,6}(?:\s|$)", line) for line in text.splitlines())


def stream_answer(api_base: str, session_id: str, question: str) -> dict[str, Any]:
    body = json.dumps({"question": question}, ensure_ascii=False).encode("utf-8")
    request = Request(
        api_base.rstrip("/") + f"/chat/sessions/{session_id}/answers:stream",
        data=body,
        method="POST",
        headers={"Accept": "text/event-stream", "Content-Type": "application/json"},
    )
    started = time.perf_counter()
    first_delta_ms: float | None = None
    first_useful_body_ms: float | None = None
    events: dict[str, Any] = {}
    answer_parts: list[str] = []
    current_event = "message"
    data_lines: list[str] = []

    def consume_frame() -> None:
        nonlocal first_delta_ms, first_useful_body_ms, current_event, data_lines
        if not data_lines:
            current_event = "message"
            return
        try:
            value = json.loads("\n".join(data_lines))
        except json.JSONDecodeError:
            events["parse_error"] = True
            data_lines = []
            current_event = "message"
            return
        if current_event == "delta":
            delta = str(value.get("text", ""))
            if delta and first_delta_ms is None:
                first_delta_ms = (time.perf_counter() - started) * 1000
            if value.get("replace"): answer_parts[:] = [delta]
            else: answer_parts.append(delta)
            if first_useful_body_ms is None and has_visible_body("".join(answer_parts)):
                first_useful_body_ms = (time.perf_counter() - started) * 1000
        else:
            events[current_event] = value
        data_lines = []
        current_event = "message"

    try:
        with LOCAL_API_OPENER.open(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            while True:
                raw_line = response.readline()
                if not raw_line:
                    consume_frame()
                    break
                line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                if not line:
                    consume_frame()
                elif line.startswith("event:"):
                    current_event = line[6:].strip()
                elif line.startswith("data:"):
                    data_lines.append(line[5:].lstrip())
    except HTTPError as exc:
        raise EvalError(f"聊天流请求失败：HTTP {exc.code}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise EvalError(f"聊天流中断：{type(exc).__name__}") from exc

    total_ms = (time.perf_counter() - started) * 1000
    return {
        "answer": events.get("done", {}).get("answer", "".join(answer_parts)),
        "first_delta_ms": round(first_delta_ms, 1) if first_delta_ms is not None else None,
        "first_useful_body_ms": round(first_useful_body_ms, 1) if first_useful_body_ms is not None else None,
        "total_ms": round(total_ms, 1),
        "meta": events.get("meta", {}),
        "citations": events.get("citations", {}).get("citations", []),
        "done": events.get("done", {}),
        "error": events.get("error"),
        "parse_error": events.get("parse_error", False),
    }


def chat_retrieval_size(question: str) -> tuple[int, int]:
    """Mirror build_chat_retrieval_plan for the fixed evaluation prompts."""
    value = question.casefold()
    comprehensive = (
        "有哪些", "哪几种", "几种", "多少种", "几类", "列举", "列出", "分别", "分类",
        "所有", "全部", "全面", "综合比较", "整体分析", "优缺点", "利弊", "有什么区别",
        "有什么不同", "比较", "对比", "异同", "各自的",
    )
    explanatory = (
        "为什么", "原因", "如何", "怎么", "怎样", "步骤", "流程", "方法", "原理", "机制",
        "解释", "分析", "推导", "证明", "过程", "适用条件", "条件是什么", "怎么判断",
        "如何判断", "怎么求", "如何求", "怎么使用", "如何使用",
    )
    precise = (
        "什么是", "是什么", "定义", "含义", "指什么", "什么意思", "哪个", "是谁", "什么时候",
        "何时", "哪一年", "在哪里", "多少元", "多少个", "是多少", "是否", "能否", "可以吗",
        "对吗", "正确吗", "结果是什么", "取值是多少",
    )
    if any(phrase in value for phrase in comprehensive):
        top_k = 16
    elif any(phrase in value for phrase in explanatory):
        top_k = 12
    elif any(phrase in value for phrase in precise):
        top_k = 8
    else:
        top_k = 12  # app default is explanatory when rule/LLM intent classification is unclear
    candidate_k = min(max(top_k * 3, 24), 50)
    return top_k, candidate_k


def retrieve_contexts(api_base: str, case: EvalCase) -> tuple[list[dict[str, Any]], list[str], str]:
    if case.strategy == "scope_guard":
        return [], [], "scope_guard_no_retrieval"
    if case.strategy == "overview":
        materials = api_call(
            api_base,
            "GET",
            "/materials?" + urlencode({"limit": 100, "source_type": case.mode}),
        ).get("items", [])
        matches = [item for item in materials if item.get("title") == case.material_title]
        if len(matches) != 1:
            raise EvalError(
                f"{case.case_id}: 测试库应恰有一份资料 {case.material_title!r}，实际匹配 {len(matches)} 份"
            )
        material_id = matches[0].get("id")
        document = api_call(api_base, "GET", f"/materials/{material_id}/content")
        text = str(document.get("text", ""))
        if not text.strip():
            raise EvalError(f"{case.case_id}: 测试资料正文为空")
        return (
            [{"chunk_id": None, "material_title": document.get("title"), "heading_path": [], "score": None}],
            [f"【整份资料：{document.get('title', case.material_title)}】\n{text}"],
            "full_document_content_endpoint",
        )

    top_k, candidate_k = chat_retrieval_size(case.question)
    result = api_call(
        api_base,
        "POST",
        "/materials/search",
        {
            "query": case.question,
            "top_k": top_k,
            "candidate_k": candidate_k,
            "source_types": [case.mode],
        },
    )
    hits = result.get("hits", [])
    contexts = []
    for hit in hits:
        title = str(hit.get("material_title", "未命名资料"))
        headings = hit.get("heading_path") or []
        heading = " › ".join(str(part) for part in headings)
        label = f"【资料：{title}{'｜章节：' + heading if heading else ''}】"
        contexts.append(label + "\n" + str(hit.get("content", "")))
    return hits, contexts, "materials_search_same_stack_approximation"


def normalize_answer_for_checks(answer: str) -> str:
    """Normalize common LaTeX spellings before deterministic phrase checks."""
    folded = answer.casefold()
    folded = re.sub(
        r"\\(?:[dt]?frac)\s*\{\s*([^{}]+)\s*\}\s*\{\s*([^{}]+)\s*\}",
        r"\1/\2",
        folded,
    )
    # TeX permits one-token numerator and denominator without braces (\frac12).
    folded = re.sub(r"\\(?:[dt]?frac)\s*(\d)\s*(\d)", r"\1/\2", folded)
    for latex, plain in (
        (r"\infty", "∞"),
        (r"\neq", "≠"),
        (r"\ge", "≥"),
        (r"\le", "≤"),
    ):
        folded = folded.replace(latex, plain)
    return folded


def phrase_check(case: EvalCase, answer: str, retrieval_mode: str) -> dict[str, Any]:
    folded = normalize_answer_for_checks(answer)
    compact = re.sub(r"\s+", "", folded)
    missing_groups = [
        list(group)
        for group in case.required_any_groups
        if not any(
            term.casefold() in folded
            or re.sub(r"\s+", "", term.casefold()) in compact
            for term in group
        )
    ]
    found_forbidden = [term for term in case.forbidden_any if term.casefold() in folded]
    if case.answerability == "guard":
        passed = retrieval_mode == "scope_notice" and not missing_groups and not found_forbidden
    elif case.answerability == "general":
        passed = "通用知识参考" in answer and not missing_groups and not found_forbidden
    elif case.answerability == "unanswerable":
        # A refusal may name the unsupported topic while explaining its limits;
        # term occurrence alone is not evidence of hallucination.
        refusal_cues = (
            "没有足够依据",
            "资料不足",
            "无法根据",
            "无法依据",
            "依据资料的回答",
            "资料中没有",
            "资料里没有",
            "未在资料",
            "没有相关内容",
            "没有任何",
            "不能凭空作答",
            "没法凭空作答",
            "没法回答",
            "无法回答",
            "完全没有",
        )
        has_refusal = any(cue in folded for cue in refusal_cues)
        if has_refusal:
            missing_groups = []
        else:
            missing_groups = [["明确说明资料依据不足或无法回答"]]
        passed = has_refusal
    else:
        passed = not missing_groups and not found_forbidden
    return {
        "passed": passed,
        "missing_required_groups": missing_groups,
        "out_of_scope_terms_mentioned_for_review": found_forbidden,
    }


def record_faithfulness_output(response_model, result, audit):
    """Observe existing structured judge outputs, never add or change a judge call."""
    name = response_model.__name__
    if name not in {"StatementGeneratorOutput", "NLIStatementOutput"}:
        return
    original = list(result.statements)
    statements = original[:256]
    if name == "StatementGeneratorOutput":
        audit.append({"phase": "statement_generation", "statements": [str(s)[:1200] for s in statements],
                      "truncated": len(original) > 256 or any(len(str(s)) > 1200 for s in statements)})
    else:
        audit.append({"phase": "statement_verdicts", "statements": [
            {"statement": str(s.statement)[:1200], "reason": str(s.reason)[:1200], "verdict": s.verdict}
            for s in statements
        ], "truncated": len(original) > 256 or any(len(str(s.statement)) > 1200 or len(str(s.reason)) > 1200 for s in statements)})


def faithfulness_diagnostics_complete(audit, status):
    if status != "scored" or len(audit) != 2:
        return False
    generated, judged = audit
    return (generated.get("phase") == "statement_generation"
            and judged.get("phase") == "statement_verdicts"
            and not generated.get("truncated") and not judged.get("truncated")
            and bool(generated.get("statements"))
            and generated["statements"] == [s.get("statement") for s in judged.get("statements", [])]
            and all(s.get("verdict") in (0, 1) for s in judged["statements"]))


def validate_screening_snapshot(snapshot, expected_mode):
    """Before paid judging, reject an arm whose actual evidence/config differs."""
    if expected_mode is None:
        return
    from backend.chat.context_screening import POLICY_VERSION, MIN_COSINE
    if expected_mode not in {"off", "filter"}:
        raise EvalError("筛选对照模式无效")
    diagnostic = snapshot.get("context_screening") if isinstance(snapshot, dict) else None
    if not isinstance(diagnostic, dict) or diagnostic.get("mode") != expected_mode:
        raise EvalError("实际快照筛选模式与本轮分支不一致")
    if diagnostic.get("version") != POLICY_VERSION or diagnostic.get("threshold") != MIN_COSINE:
        raise EvalError("实际快照筛选版本或门槛不一致")
    fields = ("before_count", "after_count", "removed_count", "would_remove_count")
    if any(type(diagnostic.get(k)) is not int or diagnostic[k] < 0 for k in fields):
        raise EvalError("实际快照筛选计数无效")
    before, after, removed, would_remove = (diagnostic[k] for k in fields)
    if after != len(snapshot.get("contexts", [])) or before != after + removed or would_remove > before:
        raise EvalError("实际快照片段与筛选计数不一致")
    if expected_mode == "filter":
        if diagnostic.get("applied") is not True or diagnostic.get("reason") != "eligible" or removed != would_remove:
            raise EvalError("目标未实际进入受控筛选，不可记作filter对照")
    elif diagnostic.get("applied") is not False or removed != 0 or would_remove != 0:
        raise EvalError("off分支实际发生筛选")


async def score_metrics(
    *,
    case: EvalCase,
    answer: str,
    contexts: list[str],
    scorers: dict[str, Any],
    timeout_seconds: int,
) -> dict[str, Any]:
    if case.answerability == "guard":
        return {name: {"status": "skipped", "reason": "模式越界保护不调用检索与模型"} for name in scorers}
    results: dict[str, Any] = {}
    for name, scorer in scorers.items():
        if name != "answer_relevancy" and case.answerability in {"unanswerable", "general"}:
            results[name] = {
                "status": "skipped",
                "reason": (
                    "通用知识参考不以资料为依据，资料指标不适用；另评回答相关性和要点覆盖"
                    if case.answerability == "general" else
                    "拒答是在陈述资料范围缺失；正向检索片段不能验证否定结论，改由确定性拒答检查判定"
                ),
            }
            continue
        if name != "answer_relevancy" and not contexts:
            results[name] = {"status": "skipped", "reason": "实际检索上下文为空"}
            continue
        precision_audit = getattr(getattr(scorer, "llm", None), "precision_audit", None) if name == "context_precision" else None
        if precision_audit is not None:
            precision_audit.clear()
        faithfulness_audit = getattr(getattr(scorer, "llm", None), "faithfulness_audit", None) if name == "faithfulness" else None
        if faithfulness_audit is not None:
            faithfulness_audit.clear()
        try:
            metric_args: dict[str, Any] = {"user_input": case.question}
            if name != "answer_relevancy":
                metric_args["retrieved_contexts"] = contexts
            if name in {"context_precision", "context_recall"}:
                metric_args["reference"] = case.reference
            elif name == "faithfulness":
                marker = re.search(r"(?m)^\s*#{1,6}\s*通用知识参考[^\n]*", answer)
                grounded_answer = answer[:marker.start()] if marker else answer
                if marker and not re.search(r"\[C[1-9]\d*\]", grounded_answer):
                    results[name] = {"status": "skipped", "reason": "回答只有通用知识参考，没有资料结论可计算忠实度"}
                    continue
                metric_args["response"] = grounded_answer
            elif name == "answer_relevancy":
                metric_args["response"] = answer
                audit = getattr(getattr(scorer, "llm", None), "relevancy_audit", None)
                if audit is not None:
                    audit.clear()
            result = await asyncio.wait_for(
                scorer.ascore(**metric_args),
                timeout=timeout_seconds,
            )
            raw_value = getattr(result, "value", result)
            results[name] = {
                "status": "scored",
                "value": float(raw_value) if raw_value is not None else None,
                "reason": (
                    str(getattr(result, "reason", None))[:500]
                    if getattr(result, "reason", None) is not None
                    else None
                ),
            }
        except Exception as exc:  # continue so one unsupported metric does not erase the whole run
            results[name] = {
                "status": "error",
                "error_type": type(exc).__name__,
                "message": str(exc)[:240],
            }
        if name == "answer_relevancy":
            audit = getattr(getattr(scorer, "llm", None), "relevancy_audit", None)
            if audit is not None:
                results[name]["diagnostics"] = list(audit)
        if precision_audit is not None:
            results[name]["diagnostics"] = [dict(item) for item in precision_audit]
            results[name]["diagnostic_context_count"] = len(contexts)
            results[name]["diagnostics_complete"] = len(precision_audit) == len(contexts) and results[name]["status"] == "scored"
        if faithfulness_audit is not None:
            results[name]["diagnostics"] = deepcopy(faithfulness_audit)
            results[name]["diagnostics_complete"] = faithfulness_diagnostics_complete(faithfulness_audit, results[name]["status"])
    return results


def mean_metric(rows: list[dict[str, Any]], metric: str) -> dict[str, Any]:
    values = [
        item["metrics"][metric]["value"]
        for item in rows
        if item.get("metrics", {}).get(metric, {}).get("status") == "scored"
        and item["metrics"][metric].get("value") is not None
    ]
    return {
        "n": len(values),
        "mean": round(statistics.fmean(values), 4) if values else None,
        "min": round(min(values), 4) if values else None,
    }


def precision_conflict_review(
    metrics: dict[str, Any], behavior: dict[str, Any], citation_audit: dict[str, Any]
) -> dict[str, Any]:
    """Flag a contradictory metric pattern for review, without changing scores."""
    precision = metrics.get("context_precision", {})
    recall = metrics.get("context_recall", {})
    reviewable = (
        precision.get("status") == "scored"
        and precision.get("value") == 0.0
        and precision.get("diagnostics_complete") is True
        and behavior.get("passed") is True
        and citation_audit.get("count", 0) > 0
        and citation_audit.get("all_present_in_actual_evidence") is True
    )
    full_recall = recall.get("status") == "scored" and recall.get("value") == 1.0
    # A judge may demand each individual chunk cover the whole answer. Flag
    # repeated explicit wording even when recall is partial; this is a review
    # request, not proof that the judge or retrieval is wrong.
    diagnostics = precision.get("diagnostics") or []
    completeness_reasons = sum(
        1 for row in diagnostics if isinstance(row, dict) and row.get("verdict") == 0
        and any(phrase in str(row.get("reason", "")).lower() for phrase in (
            "full answer", "all stages", "entire answer", "complete answer",
            "fully answer the question", "requires a comparison of both documents",
            "完整答案", "全部阶段", "所有阶段",
        ))
    )
    whole_answer_pattern = completeness_reasons >= 2
    flagged = reviewable and (full_recall or whole_answer_pattern)
    return {
        "required": flagged,
        "reason": ("zero_precision_with_full_recall_and_grounded_citations" if full_recall
                   else "repeated_single_chunk_completeness_requirement") if flagged else None,
        "score_adjusted": False,
    }


def make_scorers(
    settings,
    judge_model: str | None,
    judge_max_tokens: int,
) -> tuple[Any, dict[str, Any], str]:
    try:
        from openai import AsyncOpenAI
        import instructor
        from ragas.llms.base import InstructorLLM
        from ragas.metrics.collections import AnswerRelevancy, ContextPrecision, ContextRecall, Faithfulness
        from ragas.embeddings.base import BaseRagasEmbedding
    except ImportError as exc:
        raise EvalError(
            "RAGAS 评测依赖未安装；请在隔离环境运行："
            "python -m pip install -r requirements-ragas.txt"
        ) from exc

    key = os.environ.get("RAGAS_API_KEY")
    configured_key = settings.llm_api_key.get_secret_value() if settings.llm_api_key else None
    api_key = key or configured_key
    model = judge_model or os.environ.get("RAGAS_LLM_MODEL") or settings.llm_model
    base_url = os.environ.get("RAGAS_BASE_URL") or settings.llm_base_url
    if not api_key or not model or not base_url:
        raise EvalError(
            "RAGAS judge 未配置：需要模型名、OpenAI 兼容 base URL 和 API key。"
            "密钥可以通过 RAGAS_API_KEY 环境变量覆盖；脚本不会显示密钥。"
        )

    client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=90.0, max_retries=1)
    # DeepSeek reasoning/thinking endpoints reject forced tool_choice. Instructor's
    # JSON mode uses response_format=json_object instead, while preserving the
    # structured Pydantic outputs required by RAGAS.
    structured_client = instructor.from_openai(client, mode=instructor.Mode.JSON)
    class AuditedInstructorLLM(InstructorLLM):
        """Record existing judge calls without changing RAGAS scoring."""
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.relevancy_audit: list[dict[str, Any]] = []
            self.precision_audit: list[dict[str, Any]] = []
            self.faithfulness_audit: list[dict[str, Any]] = []

        async def agenerate(self, prompt, response_model):
            result = await super().agenerate(prompt, response_model)
            record_faithfulness_output(response_model, result, self.faithfulness_audit)
            if response_model.__name__ == "AnswerRelevanceOutput":
                self.relevancy_audit.append({
                    "question": str(result.question)[:1200],
                    "noncommittal": bool(result.noncommittal),
                })
            elif response_model.__name__ == "ContextPrecisionOutput":
                self.precision_audit.append({"context_index": len(self.precision_audit),
                                             "verdict": result.verdict, "reason": str(result.reason)[:1200]})
            return result

    judge_llm = AuditedInstructorLLM(
        client=structured_client,
        model=model,
        provider="openai",
        temperature=0,
        max_tokens=judge_max_tokens,
        # The evaluator needs compact structured decisions, not chain-of-thought.
        # DeepSeek thinking consumes the same output budget and caused truncation.
        extra_body={"thinking": {"type": "disabled"}},
    )
    from backend.retrieval.embedding import SentenceTransformerEmbedder

    class LocalEvaluationEmbedding(BaseRagasEmbedding):
        def __init__(self):
            self.embedder = SentenceTransformerEmbedder(settings.embedding_model, cache_dir=str(settings.model_cache_dir))

        def embed_text(self, text: str, **_kwargs) -> list[float]:
            return self.embedder.encode([text])[0]

        def embed_texts(self, texts: list[str], **_kwargs) -> list[list[float]]:
            return self.embedder.encode(texts)

        async def aembed_text(self, text: str, **_kwargs) -> list[float]:
            return await asyncio.to_thread(self.embed_text, text)

    scorers = {
        "context_precision": ContextPrecision(llm=judge_llm),
        "context_recall": ContextRecall(llm=judge_llm),
        "faithfulness": Faithfulness(llm=judge_llm),
        "answer_relevancy": AnswerRelevancy(llm=judge_llm, embeddings=LocalEvaluationEmbedding()),
    }
    provenance = (
        "judge_model_overridden_json_nonthinking"
        if judge_model or os.environ.get("RAGAS_LLM_MODEL")
        else "same_model_as_app_self_judged_json_nonthinking"
    )
    return client, scorers, provenance


async def run(args: argparse.Namespace) -> dict[str, Any]:
    api_host, api_port = validate_local_api_target(args.api_base)
    sys.path.insert(0, str(ROOT))
    try:
        from backend.config import get_settings
    except Exception as exc:
        raise EvalError(f"无法读取应用配置：{type(exc).__name__}") from exc
    settings = getattr(args, "evaluation_settings", None) or get_settings()
    # This CLI reads model configuration only and never connects to this shell's
    # database. Enforce isolation against the live API health response instead,
    # because the shell and already-running service may have different APP_ENVs.
    health = api_call(args.api_base, "GET", "/health")
    if health.get("environment") != "test" or health.get("database") != "connected":
        raise EvalError("安全停止：API 必须报告 environment=test 且 database=connected")
    if health.get("retrieval") != "ready":
        raise EvalError("隔离测试服务的 retrieval 未就绪")
    baseline_v3 = bool(getattr(args, "baseline_v3", False))
    validate_fixture_scope(args.api_base, baseline_v3=baseline_v3)

    cases = load_cases(Path(args.dataset).resolve())
    selected_case_ids = getattr(args, "selected_case_ids", None)
    if selected_case_ids is not None:
        selected = tuple(dict.fromkeys(selected_case_ids))
        if len(selected) != len(selected_case_ids) or not set(selected).issubset({case.case_id for case in cases}):
            raise EvalError("指定的选例有重复或不存在")
        cases = [case for case in cases if case.case_id in selected]
    if args.limit is not None:
        if args.limit < 1:
            raise EvalError("--limit 必须大于 0")
        cases = cases[: args.limit]
    if baseline_v3 and sum(1 + len(c.setup_questions) for c in cases) > 20:
        raise EvalError("安全停止：真实问答含多轮铺垫不得超过20次")
    question_requests = sum(1 + len(c.setup_questions) for c in cases)
    max_question_requests = getattr(args, "max_question_requests", None)
    if max_question_requests is not None and question_requests > max_question_requests:
        raise EvalError("安全停止：选例问题请求超出本轮授权上限")
    from scripts.rag_baseline_manifest import build_manifest
    manifest = build_manifest(settings, Path(args.dataset), baseline_v3)
    manifest["selected_case_ids"] = [case.case_id for case in cases]
    manifest["question_request_limit"] = max_question_requests
    manifest["planned_question_requests"] = question_requests
    judge_client, scorers, judge_provenance = make_scorers(
        settings,
        args.judge_model,
        args.judge_max_tokens,
    )
    rows: list[dict[str, Any]] = []

    try:
        for number, case in enumerate(cases, start=1):
            print(f"[{number}/{len(cases)}] {case.case_id} ({case.mode}/{case.strategy}) ...", flush=True)
            session_id: str | None = None
            search_ms: float | None = None
            hits: list[dict[str, Any]] = []
            contexts: list[str] = []
            context_source = "not_collected"
            error: str | None = None
            failure_diagnostic = None
            setup_results = []
            try:
                session = api_call(
                    args.api_base,
                    "POST",
                    "/chat/sessions",
                    {"title": f"RAGAS eval {case.case_id}", "mode": case.mode},
                )
                session_id = str(session["session_id"])
                setup_results = []
                for setup_question in case.setup_questions:
                    setup = stream_answer(args.api_base, session_id, setup_question)
                    if setup.get("error") or not setup.get("done"):
                        failure_diagnostic = collect_failed_diagnostic(args.api_base, session_id, setup, include_content=baseline_v3)
                        raise EvalError("多轮铺垫失败；不重跑该场景")
                    setup_results.append({"question": setup_question, "answer": setup["answer"], "total_ms": setup["total_ms"], "usage": setup["done"].get("usage"),
                                          "retrieval_mode": (setup.get("meta") or {}).get("retrieval_mode"),
                                          "scope_resolved": (setup.get("meta") or {}).get("retrieval_mode") not in (None, "unknown", "scope_notice")})
                stream = stream_answer(args.api_base, session_id, case.question)
                answer = str(stream["answer"])
                if stream["error"]:
                    error = f"stream_error:{stream['error'].get('code', 'unknown')}"
                elif not stream["done"]:
                    error = "stream_missing_done_event"
                meta = stream["meta"] if isinstance(stream["meta"], dict) else {}
                done = stream["done"] if isinstance(stream["done"], dict) else {}
                if error:
                    failure_diagnostic = collect_failed_diagnostic(args.api_base, session_id, stream, include_content=baseline_v3)
                    raise EvalError(error)
                messages = api_call(args.api_base, "GET", f"/chat/sessions/{session_id}/messages")
                if not isinstance(messages, list) or any(not isinstance(item, dict) for item in messages):
                    raise EvalError("消息恢复响应格式无效")
                snapshot = next((item.get("evaluation_evidence") for item in messages
                                 if item.get("message_id") == done.get("message_id")), None)
                generation_trace = next((item.get("generation_trace") for item in messages
                                         if item.get("message_id") == done.get("message_id")), None)
                from backend.chat.evidence import validate_evidence_snapshot
                try:
                    hits, contexts = validate_evidence_snapshot(snapshot, done.get("message_id"))
                except ValueError as exc:
                    raise EvalError(str(exc)) from exc
                validate_screening_snapshot(snapshot, getattr(args, "expected_context_screening", None))
                context_source = "actual-model-evidence-v2"
                search_ms = None  # 不把读取快照/生成耗时伪装成独立检索耗时。
                retrieval_mode = str(meta.get("retrieval_mode", "unknown"))
                behavior = phrase_check(case, answer, retrieval_mode)
                citations = stream["citations"] if isinstance(stream["citations"], list) else []
                hit_ids = {str(hit.get("chunk_id")) for hit in hits if hit.get("chunk_id")}
                cited_ids = [str(card.get("chunk_id")) for card in citations if card.get("chunk_id")]
                citation_audit = {
                    "count": len(citations),
                    "all_present_in_actual_evidence": (
                        all(chunk_id in hit_ids for chunk_id in cited_ids) if hit_ids else None
                    ),
                    "unmatched_cited_chunk_ids": (
                        [chunk_id for chunk_id in cited_ids if chunk_id not in hit_ids] if hit_ids else []
                    ),
                }
                metrics = await score_metrics(
                    case=case,
                    answer=answer,
                    contexts=contexts,
                    scorers=scorers,
                    timeout_seconds=args.metric_timeout,
                )
                precision_review = precision_conflict_review(metrics, behavior, citation_audit)
                row = {
                    "case_id": case.case_id,
                    "category": case.category,
                    "setup_results": setup_results,
                    "setup_scope_resolved": all(item["scope_resolved"] for item in setup_results),
                    **({"answer": answer, "actual_evidence": snapshot, "manual_review": {"status": "pending"}} if baseline_v3 else {}),
                    "mode": case.mode,
                    "strategy": case.strategy,
                    "answerability": case.answerability,
                    "question": case.question,
                    "answer_excerpt": answer[:1600],
                    "answer_chars": len(answer),
                    "retrieval_mode": retrieval_mode,
                    "answer_source": done.get("answer_source"),
                    "retrieval_context_source": context_source,
                    "retrieval_context_count": len(contexts),
                    "server_retrieved_count": meta.get("retrieved_count"),
                    "retrieved_context_chars": sum(len(text) for text in contexts),
                    "retrieved_headings": [
                        {
                            "material_title": hit.get("material_title"),
                            "heading_path": hit.get("heading_path", []),
                            "score": hit.get("score"),
                            "chunk_id": hit.get("chunk_id"),
                        }
                        for hit in hits
                    ],
                    "citation_audit": citation_audit,
                    "precision_conflict_review": precision_review,
                    "search_latency_ms": search_ms,
                    "first_delta_ms": stream["first_delta_ms"],
                    "first_useful_body_ms": stream.get("first_useful_body_ms"),
                    "total_latency_ms": stream["total_ms"],
                    "server_response_duration_ms": done.get("response_duration_ms"),
                    "token_usage": done.get("usage"),
                    "token_usage_observed": done.get("usage") is not None,
                    "generation_trace": generation_trace,
                    "behavior_check": behavior,
                    "metrics": metrics,
                    "stream_error": error,
                    "sse_parse_error": stream["parse_error"],
                }
                rows.append(row)
                precision = metrics.get("context_precision", {}).get("value")
                faithfulness = metrics.get("faithfulness", {}).get("value")
                print(
                    f"  latency={stream['total_ms']:.0f}ms; contexts={len(contexts)}; "
                    f"context_precision={precision}; faithfulness={faithfulness}; "
                    f"behavior={'PASS' if behavior['passed'] else 'FAIL'}",
                    flush=True,
                )
            except Exception as exc:
                rows.append(
                    {
                        "case_id": case.case_id,
                        "category": case.category,
                        "mode": case.mode,
                        "question": case.question,
                        "error_type": type(exc).__name__,
                        "error": str(exc)[:300],
                        "search_latency_ms": search_ms,
                        "retrieval_context_source": context_source,
                        "failure_diagnostic": failure_diagnostic,
                        "setup_results": setup_results,
                    }
                )
                print(f"  ERROR {type(exc).__name__}: {str(exc)[:160]}", flush=True)
            finally:
                if session_id is not None:
                    try:
                        api_call(args.api_base, "DELETE", f"/chat/sessions/{session_id}")
                    except Exception as exc:
                        rows[-1]["session_cleanup_error"] = type(exc).__name__
                checkpoint = getattr(args, "checkpoint", None)
                if checkpoint:
                    checkpoint = Path(checkpoint)
                    checkpoint.parent.mkdir(parents=True, exist_ok=True)
                    checkpoint.write_text(json.dumps({"status": "in_progress", "evaluation_configuration": manifest, "cases": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    finally:
        await judge_client.close()

    metric_names = ("context_precision", "context_recall", "faithfulness", "answer_relevancy")
    scored = [row for row in rows if "metrics" in row]
    answerable = [row for row in scored if row.get("answerability") == "answerable"]
    unanswerable = [row for row in scored if row.get("answerability") == "unanswerable"]
    general = [row for row in scored if row.get("answerability") == "general"]
    summary = {
        "case_count": len(rows),
        "case_errors": sum("error_type" in row for row in rows),
        "metric_errors": sum(
            metric.get("status") == "error"
            for row in scored
            for metric in row.get("metrics", {}).values()
        ),
        "behavior_pass_rate": round(
            sum(bool(row.get("behavior_check", {}).get("passed")) for row in scored)
            / len(scored),
            4,
        ) if scored else None,
        "unanswerable_case_count": len(unanswerable),
        "unanswerable_refusal_pass_rate": round(
            sum(bool(row.get("behavior_check", {}).get("passed")) for row in unanswerable)
            / len(unanswerable),
            4,
        ) if unanswerable else None,
        "metrics_all_scored_cases": {name: mean_metric(scored, name) for name in metric_names},
        "metrics_answerable_cases": {name: mean_metric(answerable, name) for name in metric_names},
        "metrics_general_reference_cases": {name: mean_metric(general, name) for name in metric_names},
        "general_reference_pass_rate": round(sum(bool(row.get("behavior_check", {}).get("passed")) for row in general) / len(general), 4) if general else None,
        "latency_ms": {
            key: {
                "n": len(values),
                "mean": round(statistics.fmean(values), 1) if values else None,
                "median": round(statistics.median(values), 1) if values else None,
                "max": round(max(values), 1) if values else None,
            }
            for key, values in {
                "first_delta": [row["first_delta_ms"] for row in scored if row.get("first_delta_ms") is not None],
                "total": [row["total_latency_ms"] for row in scored if row.get("total_latency_ms") is not None],
                "retrieval": [row["search_latency_ms"] for row in scored if row.get("search_latency_ms") is not None],
            }.items()
        },
        "token_usage_observed_cases": sum(bool(row.get("token_usage_observed")) for row in scored),
        "token_usage_unobserved_cases": sum(
            row.get("token_usage_observed") is False for row in scored
        ),
    }
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "api_host": api_host,
        "api_port": api_port,
        "api_environment": "test",
        "judge_model": args.judge_model or settings.llm_model,
        "judge_max_tokens": args.judge_max_tokens,
        "judge_provenance": judge_provenance,
        "dataset": str(Path(args.dataset).resolve()),
        "evaluation_configuration": manifest,
        "scenario_summary": {category: {
            "n": sum(row.get("category") == category for row in rows),
            "errors": sum("error_type" in row for row in rows if row.get("category") == category),
            "metrics": {name: mean_metric([row for row in rows if row.get("category") == category and "metrics" in row], name) for name in metric_names},
        } for category in sorted({row.get("category", "legacy") for row in rows})},
        "summary": summary,
        "cases": rows,
    }


def run_scope_guard_only(args: argparse.Namespace) -> dict[str, Any]:
    """Run the cross-mode guard through the local app API, without a RAGAS judge."""
    api_host, api_port = validate_local_api_target(args.api_base)
    health = api_call(args.api_base, "GET", "/health")
    if health.get("environment") != "test" or health.get("database") != "connected":
        raise EvalError("安全停止：API 必须报告 environment=test 且 database=connected")
    if health.get("retrieval") != "ready":
        raise EvalError("隔离测试服务的 retrieval 未就绪")
    validate_fixture_scope(args.api_base)
    cases = load_cases(Path(args.dataset).resolve())
    case = next((item for item in cases if item.strategy == "scope_guard"), None)
    if case is None:
        raise EvalError("数据集没有 scope_guard 用例")

    session_id: str | None = None
    try:
        session = api_call(
            args.api_base,
            "POST",
            "/chat/sessions",
            {"title": f"RAGAS local scope guard {case.case_id}", "mode": case.mode},
        )
        session_id = str(session["session_id"])
        stream = stream_answer(args.api_base, session_id, case.question)
    finally:
        cleanup_error = None
        if session_id is not None:
            try:
                api_call(args.api_base, "DELETE", f"/chat/sessions/{session_id}")
            except Exception as exc:
                cleanup_error = type(exc).__name__

    meta = stream.get("meta") if isinstance(stream.get("meta"), dict) else {}
    done = stream.get("done") if isinstance(stream.get("done"), dict) else {}
    retrieval_mode = str(meta.get("retrieval_mode", "unknown"))
    behavior = phrase_check(case, str(stream.get("answer", "")), retrieval_mode)
    row = {
        "case_id": case.case_id,
        "question": case.question,
        "mode": case.mode,
        "expected_retrieval_mode": "scope_notice",
        "retrieval_mode": retrieval_mode,
        "behavior_check": behavior,
        "application_llm_invoked": retrieval_mode != "scope_notice",
        "ragas_judge_invoked": False,
        "answer_excerpt": str(stream.get("answer", ""))[:800],
        "first_delta_ms": stream.get("first_delta_ms"),
        "total_latency_ms": stream.get("total_ms"),
        "stream_error": stream.get("error"),
        "token_usage": done.get("usage"),
        "session_cleanup_error": cleanup_error,
    }
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "api_host": api_host,
        "api_port": api_port,
        "api_environment": "test",
        "test_type": "local_scope_guard_only_no_ragas_judge",
        "summary": {
            "case_count": 1,
            "passed": behavior["passed"] and not stream.get("error"),
            "application_llm_invoked": row["application_llm_invoked"],
            "ragas_judge_invoked": False,
        },
        "cases": [row],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="考研知识库问答 RAGAS 端到端评测")
    parser.add_argument("--api-base", default=os.environ.get("KAOYAN_API_BASE", DEFAULT_API_BASE))
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET))
    parser.add_argument("--limit", type=int, default=None, help="只跑数据集前 N 题；默认全部")
    parser.add_argument("--judge-model", default=None, help="覆盖 RAGAS 评估模型名，不打印密钥")
    parser.add_argument("--judge-max-tokens", type=int, default=8000, help="评估模型输出上限；推理模型需留出思考空间")
    parser.add_argument("--metric-timeout", type=int, default=METRIC_TIMEOUT_SECONDS)
    parser.add_argument("--scope-guard-only", action="store_true", help="仅走本机 API 验证跨模式保护，不调用 RAGAS 裁判")
    parser.add_argument("--output", default=None, help="报告 JSON 路径；默认生成 eval/reports 下的带时间戳文件")
    args = parser.parse_args()

    try:
        report = run_scope_guard_only(args) if args.scope_guard_only else asyncio.run(run(args))
    except EvalError as exc:
        print(f"评测未运行：{exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("评测已由用户中断；已完成用例的临时会话会逐题清理。", file=sys.stderr)
        return 130

    output = (
        Path(args.output).resolve()
        if args.output
        else ROOT
        / "eval"
        / "reports"
        / f"{'scope_guard' if args.scope_guard_only else 'chat_ragas'}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("\n汇总：")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"评测报告：{output}")
    if report["summary"]["case_errors"] or report["summary"]["metric_errors"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
