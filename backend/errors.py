from __future__ import annotations

import logging
import math
import re
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class ValidationDetail(BaseModel):
    field: str
    code: str
    message: str


class ErrorBody(BaseModel):
    code: str
    message: str
    details: list[ValidationDetail] | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody

# 唯一错误响应契约：{"error": {"code": ..., "message": ...}}
# 前端按 code 分支，不解析 message 的自然语言文案。
SAFE_MESSAGES: dict[str, str] = {
    "vision_not_configured": "请在设置中配置视觉模型或启用复用问答配置",
    "vision_image_invalid": "请使用5MB以内、边长不超过4096像素的有效静态JPEG、PNG或WebP图片",
    "vision_consent_required": "请确认将这张图片发送到所配置的视觉模型",
    "vision_busy": "图片识别正在进行，请稍后重试",
    "vision_output_incomplete": "识别未完整返回，请换用更清晰或范围更小的图片；未自动重试",
    "answer_attempt_conflict": "作答记录已更新，请刷新后再试",
    "answer_retry_not_allowed": "这次作答已判对，请在后续练习中复测",
    "answer_question_changed": "题目或标准答案已更新，请重新安排这道题",
    "answer_attempt_limit": "本题本次练习的尝试次数已达上限，请稍后另行复测",
    "process_review_busy": "过程审阅正在进行，请稍后查看结果或重试",
    "learning_task_not_found": "学习任务不存在",
    "learning_task_conflict": "任务状态或题库已变化，请刷新检查，或重新安排学习",
    "learning_task_busy": "已有学习任务正在执行，请稍后重试",
    "learning_task_failed": "学习安排未完成，可修改目标后重试",
    "database_unavailable": "database unavailable",
    "not_found": "resource not found",
    "validation_failed": "validation failed",
    "conflict": "conflicting state",
    "idempotency_key_conflict": "submission key is already used for a different request",
    "invalid_request": "invalid request",
    "llm_not_configured": "language model is not configured",
    "index_not_ready": "index not ready",
    "material_not_ready": "material not ready",
    "job_not_found": "job not found",
    "internal_error": "internal error",
    # 学习闭环（阶段 B）
    "knowledge_point_not_found": "knowledge point not found",
    "knowledge_lesson_not_found": "knowledge lesson not found",
    "plan_not_found": "daily plan not found",
    "practice_item_not_found": "practice item not found",
    "question_not_found": "question not found",
    "external_exam_has_no_embedded_answer": "external exam references do not contain embedded stems or answers",
    "plan_already_generated": "daily plan already generated for this study date",
    "plan_not_active": "daily plan is not active",
    "node_not_assessable": "only a leaf node with is_assessable can be assessed",
    "kp_state_not_found": "knowledge point state not found",
    "practice_item_already_assessed": "practice item already assessed",
    "question_pool_incomplete": "selected leaf question pool does not satisfy its mastery policy",
    "no_assessable_leaf_selected": "no assessable leaf selected",
    "duplicate_question_stem": "duplicate question stem in the same knowledge point",
    # 资料摄取与检索（阶段 C）
    "material_not_found": "material not found",
    "unsupported_type": "only .md, .txt, .docx and text-layer .pdf are supported",
    "file_too_large": "uploaded file is too large",
    "empty_file": "uploaded file is empty",
    "document_decode_failed": "document encoding is not supported",
    "scanned_pdf": "pdf has no text layer; OCR is not supported",
    "document_parse_failed": "document could not be parsed",
    "document_content_too_large": "文档展开后的内容超过处理上限，请拆分后上传",
    "document_parse_timeout": "文档解析超时，请拆分或另存后重试",
    "unsafe_storage_path": "stored path is outside the materials root",
    "material_file_not_found": "material file is missing on disk",
    "no_chunk_to_index": "material produced no chunk",
    "index_version_has_no_chunk": "index version has no chunk",
    "embedding_unavailable": "embedding model is unavailable",
    "embedding_dimension_mismatch": "embedding dimension mismatch",
    "retrieval_unavailable": "retrieval backend is unavailable",
    "empty_query": "query must not be empty",
    "job_failed": "document job failed",
    "chat_session_not_found": "chat session not found",
    "matched_kp_not_found": "no attributable answer exists in this chat session",
    "retrieval_failed": "retrieval failed",
    "retrieval_timeout": "retrieval timed out",
    "retrieval_busy": "retrieval is busy; retry shortly",
    "instance_lock_lost": "backend lost its database ownership lock and is unavailable",
    "generation_failed": "answer generation failed",
    "answer_truncated": "answer stopped at the model output limit",
    "forbidden": "access forbidden",
    "unauthorized": "authentication required",
    "method_not_allowed": "method not allowed",
    "http_error": "request failed",
    "settings_local_only": "model settings are only available on this computer in development mode",
    "settings_token_invalid": "settings authorization expired; refresh and retry",
    "settings_storage_failed": "model settings could not be stored",
}

# 错误码对应的默认 HTTP 状态码。
STATUS_BY_CODE: dict[str, int] = {
    "database_unavailable": 503,
    "not_found": 404,
    "job_not_found": 404,
    "validation_failed": 422,
    "conflict": 409,
    "invalid_request": 400,
    "llm_not_configured": 503,
    "index_not_ready": 409,
    "material_not_ready": 409,
    "internal_error": 500,
    # 学习闭环（阶段 B）
    "knowledge_point_not_found": 404,
    "knowledge_lesson_not_found": 404,
    "plan_not_found": 404,
    "practice_item_not_found": 404,
    "question_not_found": 404,
    "external_exam_has_no_embedded_answer": 409,
    "plan_already_generated": 409,
    "plan_not_active": 409,
    "node_not_assessable": 409,
    "kp_state_not_found": 409,
    "practice_item_already_assessed": 409,
    "question_pool_incomplete": 409,
    "no_assessable_leaf_selected": 422,
    "duplicate_question_stem": 409,
    # 资料摄取与检索（阶段 C）
    "material_not_found": 404,
    "unsupported_type": 422,
    "file_too_large": 413,
    "empty_file": 422,
    "document_decode_failed": 422,
    "scanned_pdf": 422,
    "document_parse_failed": 422,
    "document_content_too_large": 413,
    "document_parse_timeout": 422,
    "unsafe_storage_path": 500,
    "material_file_not_found": 500,
    "no_chunk_to_index": 422,
    "index_version_has_no_chunk": 500,
    # 模型不可用是可用性问题，不是用户的错，用 503 让前端提示「稍后重试」。
    "embedding_unavailable": 503,
    "embedding_dimension_mismatch": 500,
    "retrieval_unavailable": 503,
    "empty_query": 422,
    "job_failed": 409,
    "chat_session_not_found": 404,
    "matched_kp_not_found": 409,
    "retrieval_failed": 503,
    "retrieval_timeout": 504,
    "retrieval_busy": 503,
    "process_review_busy": 503,
    "instance_lock_lost": 503,
    "generation_failed": 503,
    "answer_truncated": 503,
    "forbidden": 403,
    "unauthorized": 401,
    "method_not_allowed": 405,
    "http_error": 400,
    "settings_local_only": 403,
    "settings_token_invalid": 403,
    "settings_storage_failed": 503,
    "vision_not_configured": 503,
    "vision_image_invalid": 422,
    "vision_consent_required": 403,
    "vision_busy": 503,
    "vision_output_incomplete": 503,
}


class AppError(Exception):
    """业务可预期错误；消息只允许来自 SAFE_MESSAGES，避免泄露内部细节。"""

    def __init__(
        self,
        code: str,
        *,
        status_code: int | None = None,
        detail: str | None = None,
        retryable: bool | None = None,
    ) -> None:
        # status_code 只允许整数。若允许字符串，把「消息」误传成第二个位置参数
        # 就会一路传到 JSONResponse 才炸，表现为一个毫无线索的 500。
        if status_code is not None and not isinstance(status_code, int):
            raise TypeError(
                f"AppError 的 status_code 必须是 int，收到 {type(status_code).__name__}；"
                "消息请用 detail= 关键字参数传入"
            )
        # 未知错误码统一降级为 internal_error，防止把任意文本回传给浏览器。
        self.code = code if code in SAFE_MESSAGES else "internal_error"
        self.status_code = status_code if status_code is not None else STATUS_BY_CODE.get(self.code, 500)
        self.detail = detail
        # 是否值得**原样再试一次**。
        #
        # 为什么要显式表达而不是事后猜：问答层需要区分
        # 「外部服务瞬时抽风（限流、502/503、超时）」与「确定性失败（参数错、鉴权错）」。
        # 前者重试一次往往就好，后者重试只是浪费用户时间。
        # 默认 None 表示调用方没表态，由具体位置自行决定。
        self.retryable = retryable
        super().__init__(self.code)

    @property
    def message(self) -> str:
        return SAFE_MESSAGES[self.code]

    def to_payload(self) -> dict[str, Any]:
        return {"error": {"code": self.code, "message": self.message}}


async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    """把 AppError 转成统一错误 JSON。"""
    if exc.status_code >= 500:
        # 服务端错误才记日志；detail 只进日志，绝不进响应体。
        logger.warning("app error %s: %s", exc.code, exc.detail or "")
    return JSONResponse(status_code=exc.status_code, content=exc.to_payload())


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(HTTPException, http_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unexpected_error_handler)


def validation_details(exc: RequestValidationError) -> list[dict[str, str]]:
    """Only return field/rule metadata; never echo input, raw msg or exception ctx."""
    messages = {
        "missing": "不能为空", "uuid_parsing": "应为有效的 UUID",
        "int_parsing": "应为整数", "int_type": "应为整数",
        "float_parsing": "应为数字", "bool_parsing": "应为布尔值",
        "string_type": "应为文本", "json_invalid": "JSON 格式不正确",
        "value_error": "格式或取值不符合要求", "extra_forbidden": "不支持此参数",
    }
    bounds = {
        "greater_than_equal": ("ge", "应大于或等于 {}"),
        "less_than_equal": ("le", "应小于或等于 {}"),
        "greater_than": ("gt", "应大于 {}"), "less_than": ("lt", "应小于 {}"),
        "string_too_long": ("max_length", "最多 {} 个字符"),
        "string_too_short": ("min_length", "至少 {} 个字符"),
    }
    details = []
    for error in exc.errors()[:20]:
        location = []
        for part in error.get("loc", ())[:8]:
            token = str(part)
            location.append(token if re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]{0,63}|\d{1,6}", token) else "field")
        kind = error.get("type", "validation_failed")
        message = messages.get(kind, "不符合要求")
        if kind in bounds:
            key, template = bounds[kind]
            bound = error.get("ctx", {}).get(key)
            if type(bound) in (int, float) and math.isfinite(bound) and abs(bound) < 1e12:
                message = template.format(bound)
        details.append({"field": ".".join(location), "code": kind if kind in messages or kind in bounds else "validation_failed", "message": message})
    return details


async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    payload = AppError("validation_failed").to_payload()
    payload["error"]["details"] = validation_details(exc)
    return JSONResponse(status_code=422, content=payload)


async def http_error_handler(_: Request, exc: HTTPException) -> JSONResponse:
    code = {400: "invalid_request", 401: "unauthorized", 403: "forbidden", 404: "not_found", 405: "method_not_allowed", 409: "conflict", 422: "validation_failed"}.get(exc.status_code, "internal_error" if exc.status_code >= 500 else "http_error")
    headers = {key: value for key, value in (exc.headers or {}).items() if key.lower() in {"allow", "retry-after", "www-authenticate"}}
    return JSONResponse(status_code=exc.status_code, content=AppError(code).to_payload(), headers=headers)


async def unexpected_error_handler(_: Request, exc: Exception) -> JSONResponse:
    logger.error("unexpected API error: %s", type(exc).__name__)
    return JSONResponse(status_code=500, content=AppError("internal_error").to_payload())
