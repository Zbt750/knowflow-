"""Offline budget instrumentation checks, NOT AI quality evaluation results."""
import json
from pathlib import Path
import unittest
import asyncio
import gzip
from uuid import uuid4
import httpx
from scripts.phase5_eval_meter import Meter, BudgetStop


class MeterTests(unittest.TestCase):
    def setUp(self):
        self.temp = Path(__file__).resolve().parents[2] / "storage/quality-audits/phase5-closeout-execution-20261015/meter-unit" / uuid4().hex
        self.temp.mkdir(parents=True)
        self.m = Meter(self.temp)
        self.m.case_id = "Q-unit-only"

    def tearDown(self):
        pass  # Preserve isolated unit evidence; never delete shared audit directories.

    def request(self, **extra):
        return httpx.Request("POST", "https://api.deepseek.com/chat/completions", headers={"Authorization": "Bearer UNIT_SECRET_NOT_TO_LOG"}, json={"model": "deepseek-flash", "max_tokens": 4000, "messages": [{"role": "user", "content": "unit-only"}], **extra})

    def test_reserved_before_send_and_no_credentials(self):
        r = self.m.begin(self.request())
        self.assertEqual(len(self.m.records), 1)
        self.assertEqual(r["state"], "RESERVED_BEFORE_SEND")
        self.assertNotIn("UNIT_SECRET", (self.temp/"provider-ledger.json").read_text())

    def test_all_output_limits_enforced(self):
        with self.assertRaises(BudgetStop):
            self.m.begin(self.request(max_tokens=8001))
        self.assertEqual(self.m.records, [])
        self.assertEqual(self.m.stop_reason, "single_request_token_bound")

    def test_large_input_blocked_without_call(self):
        with self.assertRaises(BudgetStop):
            self.m.begin(self.request(messages=[{"role":"user", "content":"x"*64000}]))
        self.assertEqual(self.m.stop_reason, "single_request_token_bound")

    def test_model_not_silently_switched(self):
        with self.assertRaises(BudgetStop):
            self.m.begin(self.request(model="other"))
        self.assertEqual(self.m.stop_reason, "unexpected_model_or_unscoped_request")

    def test_nonallowlisted_remote_destination_stops_before_send(self):
        request = httpx.Request("POST", "https://example.invalid/chat/completions", json={"model":"deepseek-flash"})
        with self.assertRaises(BudgetStop):
            self.m.begin(request)
        self.assertEqual(self.m.stop_reason, "nonallowlisted_network_destination")
        self.assertEqual(self.m.records, [])

    def test_unknown_usage_stops_retry(self):
        r = self.m.begin(self.request())
        self.m.finish(r, b'{"choices":[]}', 200)
        with self.assertRaises(BudgetStop):
            self.m.begin(self.request())
        self.assertEqual(len(self.m.records), 1)
        self.assertGreater(r["conservative_cny"], 0)

    def test_raw_sse_usage_cache_and_finish_observed(self):
        r = self.m.begin(self.request())
        self.m.finish(r, b'data: {"choices":[{"finish_reason":"stop"}]}\n\ndata: {"usage":{"prompt_tokens":100,"completion_tokens":20,"prompt_cache_hit_tokens":80}}\n\ndata: [DONE]\n', 200)
        self.assertEqual(r["finish_reason"], "stop")
        self.assertEqual(r["usage"]["prompt_cache_hit_tokens"], 80)
        self.assertEqual(self.m.summary()["input_tokens"], 100)
        self.assertAlmostEqual(r["conservative_cny"], .00036)
        self.assertLess(r["peak_cache_aware_estimate_cny"], r["conservative_cny"])

    def test_300_physical_request_ceiling(self):
        self.m.records = [{"state":"COMPLETED_USAGE_OBSERVED", "usage":{}, "conservative_cny":0} for _ in range(300)]
        with self.assertRaises(BudgetStop):
            self.m.begin(self.request())

    def test_new_retest_160_request_ceiling_is_independent(self):
        self.m = Meter(self.temp, max_requests=160)
        self.m.case_id = "Q-unit-only"
        self.m.records = [{"state":"COMPLETED_USAGE_OBSERVED", "usage":{}, "conservative_cny":0} for _ in range(160)]
        with self.assertRaises(BudgetStop):
            self.m.begin(self.request())
        self.assertEqual(len(self.m.records),160)

    def test_final_user_20_physical_requests_cannot_inherit_old_allowance(self):
        self.m = Meter(self.temp, max_requests=20, max_input_tokens=300000,
                       max_output_tokens=80000, stop_cny="1.50")
        self.m.case_id = "A-offline-only"
        self.m.records = [{"state":"COMPLETED_USAGE_OBSERVED", "usage":{}, "conservative_cny":0} for _ in range(20)]
        with self.assertRaises(BudgetStop):
            self.m.begin(self.request())
        self.assertEqual(len(self.m.records), 20)

    def test_tighter_input_output_and_money_reservations_stop_before_send(self):
        for limits in ({"max_input_tokens":100}, {"max_output_tokens":100}, {"stop_cny":"0.01"}):
            meter = Meter(self.temp, max_requests=20, **limits)
            meter.case_id = "Q-offline-only"
            with self.assertRaises(BudgetStop):
                meter.begin(self.request())
            self.assertEqual(meter.records, [])

    def test_current_peak_price_override_is_recorded_and_used_conservatively(self):
        meter = Meter(self.temp, max_requests=20, max_input_tokens=300000, max_output_tokens=80000,
                      stop_cny="1.50", input_cny_per_million="2.10",
                      output_cny_per_million="8.10", cache_hit_cny_per_million="0.041")
        meter.case_id = "QA-price-test"
        record = meter.begin(self.request())
        meter.finish(record, b'{"usage":{"prompt_tokens":100,"completion_tokens":20},"choices":[{"finish_reason":"stop"}]}', 200)
        self.assertAlmostEqual(record["conservative_cny"], .000372)
        ledger = json.loads((self.temp / "provider-ledger.json").read_text(encoding="utf-8"))
        self.assertAlmostEqual(float(ledger["conservative_peak_prices_cny_per_million"]["output"]), 8.10)

    def test_invalid_budget_configuration_is_rejected(self):
        for limits in ({"max_requests":True}, {"max_input_tokens":0}, {"max_output_tokens":-1},
                       {"stop_cny":"NaN"}, {"stop_cny":"Infinity"}, {"stop_cny":"0"}):
            with self.assertRaises(ValueError):
                Meter(self.temp, **limits)

    def test_sync_transport_is_observed_not_replaced(self):
        transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"usage":{"prompt_tokens":100,"completion_tokens":10},"choices":[{"finish_reason":"stop"}]}))
        self.m.install()
        try:
            with httpx.Client(transport=transport) as client:
                client.send(self.request())
            self.assertEqual(self.m.summary()["actual_requests"], 1)
            self.assertEqual(self.m.records[0]["state"], "COMPLETED_USAGE_OBSERVED")
        finally:
            self.m.uninstall()

    def test_async_sse_transport_captures_final_usage(self):
        class SyntheticUnitStream(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b'data: {"choices":[{"delta":{"content":"unit"},"finish_reason":"stop"}]}\n\n'
                yield b'data: {"choices":[],"usage":{"prompt_tokens":100,"completion_tokens":10}}\n\ndata: [DONE]\n\n'
        async def check():
            transport = httpx.MockTransport(lambda request: httpx.Response(200, stream=SyntheticUnitStream()))
            async with httpx.AsyncClient(transport=transport) as client:
                response = await client.send(self.request(), stream=True)
                data = b"".join([chunk async for chunk in response.aiter_bytes()])
                await response.aclose()
                self.assertIn(b'"content":"unit"', data)
        self.m.install()
        try:
            asyncio.run(check())
            self.assertEqual(self.m.records[0]["usage"]["completion_tokens"], 10)
            self.assertEqual(self.m.summary()["usage_missing_requests"], 0)
        finally:
            self.m.uninstall()

    def test_compressed_provider_usage_is_decoded(self):
        raw = b'data: {"usage":{"prompt_tokens":551,"completion_tokens":3055},"choices":[{"finish_reason":"stop"}]}\n\ndata: [DONE]\n'
        r = self.m.begin(self.request())
        self.m.finish(r, gzip.compress(raw), 200, encoding="gzip")
        self.assertEqual(r["usage"]["prompt_tokens"], 551)
        self.assertEqual(r["finish_reason"], "stop")
        self.assertIn("raw_response_base64", r)
        self.assertIsNone(self.m.stop_reason)

    def test_gzip_sse_closed_after_done_before_footer(self):
        raw = b'data: {"usage":{"prompt_tokens":542,"completion_tokens":1285},"choices":[{"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
        compressor = __import__('zlib').compressobj(wbits=31)
        unfinished = compressor.compress(raw) + compressor.flush(__import__('zlib').Z_SYNC_FLUSH)
        r = self.m.begin(self.request())
        self.m.finish(r, unfinished, 200, encoding="gzip")
        self.assertEqual(r["usage"]["completion_tokens"], 1285)
        self.assertIsNone(self.m.stop_reason)

    def test_requested_4000_overshoot_still_within_authorized_8000_reservation(self):
        r = self.m.begin(self.request())
        self.assertEqual(r["output_limit"],4000)
        self.assertEqual(r["output_reservation"],8000)
        self.m.finish(r,b'{"usage":{"prompt_tokens":544,"completion_tokens":4014}}',200)
        self.assertEqual(r["requested_output_limit_overshoot"],14)
        self.assertIsNone(self.m.stop_reason)

    def test_absolute_authorized_output_overrun_stops(self):
        r = self.m.begin(self.request())
        self.m.finish(r,b'{"usage":{"prompt_tokens":544,"completion_tokens":8001}}',200)
        self.assertEqual(self.m.stop_reason,"observed_tokens_exceeded_reservation")


if __name__ == "__main__":
    unittest.main()
