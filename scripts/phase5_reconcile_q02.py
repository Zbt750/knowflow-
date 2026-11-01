"""Recover actual Q02 usage from preserved gzip SSE, no network calls."""
import base64
import hashlib
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.phase5_eval_meter import Meter
OUT = ROOT / "storage/quality-audits/phase5-closeout-execution-20261015/ai-test"


def main():
    source = OUT/"continuation-v2/provider-ledger.json"
    ledger = json.loads(source.read_text(encoding="utf-8"))
    assert len(ledger["requests"]) == 2
    record = dict(ledger["requests"][1])
    assert record["case_id"] == "Q02"
    raw = base64.b64decode(record["raw_response_base64"])
    scratch = OUT/"q02-reconciliation-evidence"
    assert not scratch.exists(); scratch.mkdir()
    meter = Meter(scratch)
    record.pop("finished",None)
    record["started_monotonic"] = __import__('time').monotonic()
    meter.records = [record]
    meter.finish(record,raw,200,encoding=record["content_encoding"])
    result = json.loads((OUT/"continuation-v2/Q02/result.json").read_text(encoding="utf-8"))
    assert record["usage"]["prompt_tokens"] == result["metadata"]["usage"]["prompt_tokens"] == 542
    assert record["usage"]["completion_tokens"] == result["metadata"]["usage"]["completion_tokens"] == 1285
    assert meter.stop_reason is None
    record["latency_seconds"] = ledger["requests"][1]["latency_seconds"]
    record["reconciliation"] = "ORIGINAL_BASE64_GZIP_STREAM_DECODED_ORIGINAL_FILE_UNCHANGED"
    path = OUT/"q02-meter-reconciliation.json"
    assert not path.exists()
    path.write_text(json.dumps({"original_ledger_sha256":hashlib.sha256(source.read_bytes()).hexdigest(),
        "reconciled_records":[ledger["requests"][0],record],"new_requests":0},ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"requests_reconciled_total":2,"Q02_usage":record["usage"],"new_requests":0}))


if __name__ == "__main__": main()
