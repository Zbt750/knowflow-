"""Reconcile the single already sent Q01 against persisted actual usage.

Preserves the original ledger/results. Does not send a network/model request.
"""
import hashlib
import json
from pathlib import Path
from decimal import Decimal
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "storage/quality-audits/phase5-closeout-execution-20261015/ai-test"


def main():
    ledger_path = OUT / "provider-ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    result = json.loads((OUT / "Q01/result.json").read_text(encoding="utf-8"))
    assert len(ledger["requests"]) == 1 and ledger["requests"][0]["case_id"] == result["id"] == "Q01"
    assert result["status"] == "COMPLETED" and result["provider_requests"] == 1
    trace = result["metadata"]["generation_trace"]
    assert trace["attempt_count"] == 1 and trace["total_usage_complete"] and trace["usage_observed"]
    assert trace["model"] == "deepseek-flash" and trace["calls"][0]["output_budget"] == ledger["requests"][0]["output_limit"]
    usage = trace["calls"][0]["usage"]
    assert usage == result["metadata"]["usage"]
    assert usage["prompt_tokens"] == 551 and usage["completion_tokens"] == 3055
    record = dict(ledger["requests"][0])
    record.update(state="COMPLETED_USAGE_OBSERVED", usage=usage, finish_reason=trace["calls"][0]["finish_reason"],
        usage_evidence="Q01/result.json: metadata.generation_trace.calls[0].usage, unique recorded physical request",
        cache_usage="UNKNOWN_NOT_ZERO", reconciliation="APPEND_ONLY_ORIGINAL_LEDGER_PRESERVED")
    record["conservative_cny"] = float(Decimal(551)*Decimal("0.000002") + Decimal(3055)*Decimal("0.000008"))
    path = OUT / "q01-meter-reconciliation.json"
    assert not path.exists()
    path.write_text(json.dumps({"original_ledger_sha256":hashlib.sha256(ledger_path.read_bytes()).hexdigest(),
        "original_case_sha256":hashlib.sha256((OUT/"Q01/result.json").read_bytes()).hexdigest(),
        "request_count":1,"reconciled_record":record,"new_model_requests":0,
        "note":"Exact usage observed by production parser; initial transport recorder lacked decompression. Cache usage unavailable, so no cache discount assumed."}, ensure_ascii=False, indent=2),encoding="utf-8")
    print(json.dumps({"requests_reconciled":1,"input_tokens":551,"output_tokens":3055,"peak_uncached_cost_upper_estimate_cny":record["conservative_cny"],"new_requests":0}))


if __name__ == "__main__": main()
