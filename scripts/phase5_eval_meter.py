"""Process-local accounting of actual Provider HTTP requests, never fake answers."""
import json
import threading
import time
import base64
import gzip
import zlib
from decimal import Decimal
from pathlib import Path
import httpx


class BudgetStop(RuntimeError):
    def __init__(self, reason, *, diagnostic=None):
        super().__init__(reason)
        self.reason = reason
        self.diagnostic = diagnostic


class Meter:
    def __init__(self, output: Path, *, max_requests: int = 300,
                 max_input_tokens: int = 1000000, max_output_tokens: int = 240000,
                 stop_cny: str = "4.50", input_cny_per_million: str = "2.00",
                 output_cny_per_million: str = "8.00", cache_hit_cny_per_million: str = "0.040"):
        if type(max_requests) is not int or not 0 < max_requests <= 300:
            raise ValueError("invalid_request_limit")
        if (type(max_input_tokens) is not int or not 0 < max_input_tokens <= 1000000
                or type(max_output_tokens) is not int or not 0 < max_output_tokens <= 240000):
            raise ValueError("invalid_token_limit")
        threshold = Decimal(str(stop_cny))
        if not threshold.is_finite() or not 0 < threshold <= Decimal("4.50"):
            raise ValueError("invalid_cost_limit")
        self.input_cost_per_token = Decimal(str(input_cny_per_million)) / Decimal(1000000)
        self.output_cost_per_token = Decimal(str(output_cny_per_million)) / Decimal(1000000)
        self.cache_hit_cost_per_token = Decimal(str(cache_hit_cny_per_million)) / Decimal(1000000)
        if any(not rate.is_finite() or rate <= 0 for rate in (
                self.input_cost_per_token, self.output_cost_per_token, self.cache_hit_cost_per_token)):
            raise ValueError("invalid_price_rate")
        self.output = output
        self.max_requests = max_requests
        self.max_input_tokens = max_input_tokens
        self.max_output_tokens = max_output_tokens
        self.stop_cny = threshold
        self.lock = threading.RLock()
        self.case_id = None
        self.records = []
        self.stop_reason = None
        self.original_sync = httpx.Client.send
        self.original_async = httpx.AsyncClient.send

    def flush(self):
        (self.output / "provider-ledger.json").write_text(json.dumps({"stop_reason": self.stop_reason,
            "limits": {"max_requests": self.max_requests, "max_input_tokens": self.max_input_tokens,
                       "max_output_tokens": self.max_output_tokens, "software_stop_cny": str(self.stop_cny)},
            "conservative_peak_prices_cny_per_million": {
                "uncached_input": str(self.input_cost_per_token * Decimal(1000000)),
                "output": str(self.output_cost_per_token * Decimal(1000000)),
                "cache_hit_input": str(self.cache_hit_cost_per_token * Decimal(1000000)),
            },
            "requests": self.records, "summary": self.summary()}, ensure_ascii=False, indent=2), encoding="utf-8")

    def summary(self):
        return {"actual_requests": len(self.records), "input_tokens": sum(r.get("usage", {}).get("prompt_tokens", 0) for r in self.records),
                "output_tokens": sum(r.get("usage", {}).get("completion_tokens", 0) for r in self.records),
                "peak_uncached_cost_upper_estimate_cny": float(sum(Decimal(str(r["conservative_cny"])) for r in self.records)),
                "usage_missing_requests": sum(r["state"] != "COMPLETED_USAGE_OBSERVED" for r in self.records), "supplier_invoice_confirmed": False}

    def stop_before_send(self, reason):
        self.stop_reason = reason
        self.flush()
        raise BudgetStop(reason)

    def begin(self, request):
        if request.url.host != "api.deepseek.com":
            if request.url.host in {"127.0.0.1", "localhost", "testserver"}:
                return None
            self.stop_before_send("nonallowlisted_network_destination")
        with self.lock:
            if self.stop_reason:
                raise BudgetStop(self.stop_reason)
            if request.url.scheme != "https" or request.url.path != "/chat/completions" or request.method != "POST":
                self.stop_before_send("provider_request_shape_violation")
            try:
                payload = json.loads(request.content)
                requested_output = int(payload["max_tokens"])
            except (ValueError, TypeError, KeyError):
                self.stop_before_send("provider_request_payload_invalid")
            if payload.get("model") != "deepseek-flash" or not self.case_id:
                self.stop_before_send("unexpected_model_or_unscoped_request")
            raw = request.content
            reserve_input = len(raw) + 2048
            # Provider billing may slightly exceed max_tokens (observed 4014
            # for a requested 4000). Reserve the ALREADY APPROVED absolute
            # per-request 8000, without raising any production request limit.
            reserve_output = 8000
            if reserve_input > 64000 or not 0 < requested_output <= 8000:
                self.stop_before_send("single_request_token_bound")
            summary = self.summary()
            cost = reserve_input * self.input_cost_per_token + reserve_output * self.output_cost_per_token
            if (len(self.records) >= self.max_requests or summary["input_tokens"] + reserve_input > self.max_input_tokens
                    or summary["output_tokens"] + reserve_output > self.max_output_tokens
                    or Decimal(str(summary["peak_uncached_cost_upper_estimate_cny"])) + cost > self.stop_cny):
                self.stop_reason = "authorized_budget_stop"
                self.flush()
                raise BudgetStop(self.stop_reason)
            # Serial execution: a preceding physical request must be accounted first.
            if any(r["state"] != "COMPLETED_USAGE_OBSERVED" for r in self.records):
                self.stop_before_send("prior_usage_unobserved")
            record = {"number": len(self.records)+1, "case_id": self.case_id, "state": "RESERVED_BEFORE_SEND",
                      "request_model": payload["model"], "request": payload, "request_bytes": len(raw),
                      "input_reservation": reserve_input, "output_limit": requested_output,
                      "output_reservation": reserve_output, "conservative_cny": float(cost),
                      "stage": "classifier" if requested_output == 48 else "agent" if self.case_id.startswith(("A", "USER-A")) else "qa",
                      "started_monotonic": time.monotonic()}
            self.records.append(record)
            self.flush()
            return record

    def finish(self, record, data=b"", status=None, error=None, encoding=None):
        if record is None or record.get("finished"):
            return
        with self.lock:
            record["finished"] = True
            record["latency_seconds"] = round(time.monotonic()-record.pop("started_monotonic"), 3)
            record["http_status"] = status
            record["content_encoding"] = encoding
            if encoding and encoding.lower() != "identity":
                record["raw_response_base64"] = base64.b64encode(data).decode("ascii")
                try:
                    for kind in reversed(encoding.lower().split(",")):
                        kind = kind.strip()
                        # SSE consumers may close after [DONE], before the gzip
                        # footer. Streaming decompression must not demand EOF.
                        if kind == "gzip": data = zlib.decompressobj(16+zlib.MAX_WBITS).decompress(data)
                        elif kind == "deflate": data = zlib.decompressobj().decompress(data)
                        elif kind == "br":
                            import brotli
                            data = brotli.decompress(data)
                        elif kind == "zstd":
                            import zstandard
                            data = zstandard.ZstdDecompressor().decompress(data)
                        else: raise ValueError("unsupported_content_encoding")
                except Exception as exc:
                    record["decode_error"] = type(exc).__name__
            record["response_text"] = data.decode("utf-8", errors="replace")
            payloads = []
            try:
                payloads = [json.loads(record["response_text"])]
            except (ValueError, TypeError):
                for line in record["response_text"].splitlines():
                    if line.startswith("data:") and line[5:].strip() not in {"", "[DONE]"}:
                        try:
                            payloads.append(json.loads(line[5:]))
                        except ValueError:
                            pass
            for payload in payloads:
                if not isinstance(payload, dict):
                    continue
                if payload.get("usage"):
                    record["usage"] = payload["usage"]
                if payload.get("model"):
                    record["response_model"] = payload["model"]
                for choice in payload.get("choices", []):
                    if choice.get("finish_reason"):
                        record["finish_reason"] = choice["finish_reason"]
            usage = record.get("usage", {})
            if isinstance(usage.get("prompt_tokens"), int) and isinstance(usage.get("completion_tokens"), int):
                i, o = usage["prompt_tokens"], usage["completion_tokens"]
                record["conservative_cny"] = float(Decimal(i)*self.input_cost_per_token + Decimal(o)*self.output_cost_per_token)
                hit = usage.get("prompt_cache_hit_tokens", 0)
                record["peak_cache_aware_estimate_cny"] = float(
                    Decimal(max(i-hit, 0))*self.input_cost_per_token
                    + Decimal(hit)*self.cache_hit_cost_per_token
                    + Decimal(o)*self.output_cost_per_token)
                record["state"] = "COMPLETED_USAGE_OBSERVED"
                if o > record["output_limit"]:
                    record["requested_output_limit_overshoot"] = o-record["output_limit"]
                if i > record["input_reservation"] or o > record.get("output_reservation",record["output_limit"]):
                    self.stop_reason = "observed_tokens_exceeded_reservation"
            else:
                record["state"] = "ACTUAL_USAGE_UNKNOWN_RESERVATION_RETAINED"
                self.stop_reason = "usage_not_returned_stop_for_reconciliation"
            if status in {401, 403}:
                self.stop_reason = "authentication_error"
            if error:
                record["error_type"] = type(error).__name__
            completed = self._provider_error_records()
            if len(completed) >= 2 and all((r.get("http_status") or 599) >= 400 for r in completed[-2:]):
                self.stop_reason = "two_consecutive_provider_errors"
            self.flush()

    def _provider_error_records(self):
        return self.records

    def install(self):
        meter = self
        def sync_send(client, request, *args, **kwargs):
            record = meter.begin(request)
            try:
                response = meter.original_sync(client, request, *args, **kwargs)
                if record:
                    meter.finish(record, response.read(), response.status_code)
                return response
            except BaseException as exc:
                meter.finish(record, error=exc)
                raise
        class Stream(httpx.AsyncByteStream):
            def __init__(self, original, record, status, encoding):
                self.original, self.record, self.status, self.encoding = original, record, status, encoding
                self.data = bytearray()
            async def __aiter__(self):
                try:
                    async for chunk in self.original:
                        self.data.extend(chunk)
                        yield chunk
                finally:
                    meter.finish(self.record, bytes(self.data), self.status, encoding=self.encoding)
            async def aclose(self):
                await self.original.aclose()
                meter.finish(self.record, bytes(self.data), self.status, encoding=self.encoding)
        async def async_send(client, request, *args, **kwargs):
            record = meter.begin(request)
            try:
                response = await meter.original_async(client, request, *args, **kwargs)
                if record:
                    if kwargs.get("stream"):
                        response.stream = Stream(response.stream, record, response.status_code, response.headers.get("content-encoding"))
                    else:
                        meter.finish(record, await response.aread(), response.status_code)
                return response
            except BaseException as exc:
                meter.finish(record, error=exc)
                raise
        httpx.Client.send = sync_send
        httpx.AsyncClient.send = async_send

    def uninstall(self):
        httpx.Client.send = self.original_sync
        httpx.AsyncClient.send = self.original_async
