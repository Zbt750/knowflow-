from backend.services.learning_assistant_service import _personal_generation_preflight_failure_message


def test_daily_personal_generation_limit_does_not_promise_an_immediate_retry():
    message = _personal_generation_preflight_failure_message("personal_generation_daily_limit")

    assert "已达到本地调用上限" in message
    assert "没有调用模型或保存题目" in message
    assert "请明天再试" in message
    assert "可修复原因后重试" not in message


def test_other_preflight_errors_keep_their_repair_guidance():
    message = _personal_generation_preflight_failure_message("personal_generation_storage_forbidden")

    assert "没有调用模型或写入题目" in message
    assert "权限恢复后可以重新尝试" in message
