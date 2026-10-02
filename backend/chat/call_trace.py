"""请求级生成记录；不保存问题、资料、推理草稿或模型凭据。"""
from contextvars import ContextVar
import re
from time import perf_counter

PROMPT_VERSION = "chat-evidence-v8"
ACTIVE_ATTEMPT = ContextVar("chat_generation_attempt", default=None)


def safe_failure_reason(detail):
    """Keep only allowlisted categories, never upstream bodies or credentials."""
    if not isinstance(detail, str):
        return "unknown"
    status = re.fullmatch(r"(?:stream|complete):http_(\d{3})", detail)
    if status:
        return "http_" + status.group(1)
    network = re.fullmatch(r"(?:stream|complete):(ConnectError|ReadTimeout|ConnectTimeout|RemoteProtocolError|ReadError|PoolTimeout)", detail)
    if network:
        return "network_" + network.group(1)
    if detail == "stream:total_timeout":
        return "total_timeout"
    if detail == "provider returned an empty answer":
        return "empty_answer"
    if detail.startswith(("stream:finish_reason:length", "complete:finish_reason:length")):
        return "output_limit"
    return "unknown"


def clean_usage(value):
    if not isinstance(value, dict):
        return None
    result = {key: value[key] for key in ("prompt_tokens", "completion_tokens", "total_tokens")
              if isinstance(value.get(key), int) and not isinstance(value[key], bool) and value[key] >= 0}
    return result or None


def observe_payload(payload):
    record = ACTIVE_ATTEMPT.get()
    if record is None or not isinstance(payload, dict):
        return
    usage = clean_usage(payload.get("usage"))
    if usage is not None:
        record["usage"] = usage
    choices = payload.get("choices") or []
    if choices and isinstance(choices[0], dict):
        reason = choices[0].get("finish_reason")
        if reason is not None:
            record["finish_reason"] = reason if isinstance(reason, str) and reason in {"stop", "length", "content_filter", "tool_calls", "function_call"} else "unknown"


class CallTrace:
    def __init__(self, provider, *, transport):
        self.model = getattr(provider, "model", None)
        self.transport = transport
        self.calls = []

    def begin(self, attempt, provider):
        record = {"attempt": attempt, "status": "interrupted", "usage": None,
                  "finish_reason": None, "error_code": None, "output_budget": None}
        if hasattr(provider, "max_tokens"):
            record["output_budget"] = provider._token_budget(attempt)
        self.calls.append(record)
        return record, ACTIVE_ATTEMPT.set(record), perf_counter()

    def end(self, record, token, started):
        record["duration_ms"] = max(0, round((perf_counter() - started) * 1000))
        ACTIVE_ATTEMPT.reset(token)

    def summary(self, request_id):
        calls = [dict(record, usage=dict(record["usage"]) if record["usage"] else None) for record in self.calls]
        observed = [call["usage"] for call in calls if call["usage"] is not None]
        totals = {key: sum(usage.get(key, 0) for usage in observed)
                  for key in ("prompt_tokens", "completion_tokens", "total_tokens")
                  if any(key in usage for usage in observed)}
        return {"request_id": str(request_id), "scope": "answer_generation_only",
                "model": self.model, "prompt_version": PROMPT_VERSION, "transport": self.transport,
                "calls": calls, "attempt_count": len(calls), "retry_count": max(0, len(calls) - 1),
                "observed_usage": totals or None, "usage_observed": bool(observed),
                "total_usage_complete": bool(calls) and all(call["usage"] and "total_tokens" in call["usage"] for call in calls)}

    def final_usage(self):
        return self.calls[-1]["usage"] if self.calls else None
