from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.chat import service
from backend.chat.call_trace import CallTrace


def prepared(question):
    hits = [SimpleNamespace(chunk_id=uuid4(), material_title=title, heading_path=(title,), content="数据库重启后保留数据。")
            for title in ("阶段说明", "部署补充")]
    prompt, mapping = service._prompt(question, hits, [], mode="user", full_document=True)
    return service.PreparedAnswer(uuid4(), prompt, mapping, None, "hybrid", generation_profile="multi_file_comparison")


@pytest.mark.parametrize("first", [4000, 8000])
def test_compact_fact_mode_preserves_reasoning_after_failed_live_trial(first):
    original = service.Provider(api_key="test", base_url="https://api.deepseek.com", model="deepseek-flash",
                                timeout=60, max_tokens=first, retry_max_tokens=8000)
    scoped = service._provider_for_answer(original, prepared("比较两份文件的共同与独有内容"))
    assert scoped._request_options() == {"reasoning_effort": "low"}
    assert original._request_options() == {"reasoning_effort": "low"}
    assert original.max_tokens == first
    assert scoped is original if first == 8000 else scoped is not original
    trace = CallTrace(scoped, transport="stream")
    record, token, started = trace.begin(1, scoped)
    trace.end(record, token, started)
    assert record["reasoning_mode"] == "low"


def test_detailed_comparison_keeps_reasoning():
    original = service.Provider(api_key="test", base_url="https://api.deepseek.com", model="deepseek-flash",
                                timeout=60, max_tokens=4000, retry_max_tokens=8000)
    scoped = service._provider_for_answer(original, prepared("详细解释共同与独有内容"))
    assert scoped._request_options() == {"reasoning_effort": "low"}


def test_other_compatible_endpoint_never_receives_deepseek_options():
    original = service.Provider(api_key="test", base_url="https://example.invalid", model="deepseek-flash",
                                timeout=60, max_tokens=4000, retry_max_tokens=8000)
    scoped = service._provider_for_answer(original, prepared("比较共同与独有内容"))
    assert scoped._request_options() == {}
