from scripts.analyze_chat_generation_reports import summarize_cases


def test_generation_report_distinguishes_output_limit_from_other_retry():
    cases = [
        {
            "question": "private question must not be included in summary",
            "total_latency_ms": 42000,
            "first_useful_body_ms": 39000,
            "generation_trace": {
                "calls": [
                    {"status": "failed", "finish_reason": "length", "error_code": "answer_truncated"},
                    {"status": "completed", "finish_reason": "stop"},
                ],
                "observed_usage": {"total_tokens": 12000},
                "total_usage_complete": True,
            },
        },
        {
            "total_latency_ms": 6000,
            "first_useful_body_ms": 4000,
            "generation_trace": {
                "calls": [
                    {"status": "failed", "error_code": "generation_failed"},
                    {"status": "completed", "finish_reason": "stop"},
                ],
                "observed_usage": {"total_tokens": 2000},
                "total_usage_complete": False,
            },
        },
        {"total_latency_ms": 1000},
    ]

    summary = summarize_cases(cases)

    assert summary["cases"] == 3
    assert summary["traced_cases"] == 2
    assert summary["untraced_cases"] == 1
    assert summary["retried_cases"] == 2
    assert summary["completed_answer_cases"] == 2
    assert summary["failed_answer_cases"] == 0
    assert summary["output_limit_cases"] == 1
    assert summary["failed_attempt_cases"] == 2
    assert summary["observed_total_tokens_complete_cases"] == 12000
    assert summary["complete_usage_cases"] == 1
    assert summary["partial_usage_cases"] == 1
    assert summary["total_latency"] == {"n": 2, "median_ms": 24000.0, "max_ms": 42000.0}
    assert summary["first_useful_body"] == {"n": 2, "median_ms": 21500.0, "max_ms": 39000.0}
    assert "private question" not in str(summary)


def test_generation_report_empty_case_list_has_no_fake_zero_latency():
    summary = summarize_cases([])
    assert summary["traced_cases"] == 0
    assert summary["total_latency"] == {"n": 0, "median_ms": None, "max_ms": None}


def test_generation_report_includes_recovered_failed_answer_trace():
    summary = summarize_cases([{
        "error_type": "EvalError",
        "failure_diagnostic": {
            "total_ms": 2500,
            "generation_trace": {
                "calls": [
                    {"status": "failed", "error_code": "generation_failed"},
                    {"status": "failed", "error_code": "generation_failed"},
                ],
                "observed_usage": None,
                "total_usage_complete": False,
            },
        },
    }])
    assert summary["traced_cases"] == 1
    assert summary["retried_cases"] == 1
    assert summary["completed_answer_cases"] == 0
    assert summary["failed_answer_cases"] == 1
    assert summary["output_limit_cases"] == 0
    assert summary["failed_attempt_cases"] == 1
    assert summary["total_latency"] == {"n": 1, "median_ms": 2500.0, "max_ms": 2500.0}
