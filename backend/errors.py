from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

# 唯一错误响应契约：{"error": {"code": ..., "message": ...}}
# 前端按 code 分支，不解析 message 的自然语言文案。
SAFE_MESSAGES: dict[str, str] = {
    "database_unavailable": "database unavailable",
    "not_found": "resource not found",
    "validation_failed": "validation failed",
    "conflict": "conflicting state",
    "invalid_request": "invalid request",
    "llm_not_configured": "language model is not configured",
    "index_not_ready": "index not ready",
    "material_not_ready": "material not ready",
    "job_not_found": "job not found",
    "internal_error": "internal error",
    # 学习闭环（阶段 B）
    "knowledge_point_not_found": "knowledge point not found",
    "plan_not_found": "daily plan not found",
    "practice_item_not_found": "practice item not found",
    "question_not_found": "question not found",
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
    "generation_failed": "answer generation failed",
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
    "plan_not_found": 404,
    "practice_item_not_found": 404,
    "question_not_found": 404,
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
    "generation_failed": 503,
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
