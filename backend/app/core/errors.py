"""统一错误响应格式 - 所有 API 端点应返回一致的错误结构"""
from fastapi import HTTPException, status


class AppError(Exception):
    """应用层异常基类，携带业务码和状态码"""

    def __init__(self, code: str, message: str, http_status: int = 400, detail=None):
        self.code = code          # 业务错误码，如 "QUOTA_EXCEEDED"
        self.message = message    # 用户友好消息
        self.http_status = http_status
        self.detail = detail      # 额外详情（可选）
        super().__init__(message)


def error_response(code: str, message: str, http_status: int = 400, detail=None) -> dict:
    """构建统一错误响应字典"""
    result = {
        "error": message,
        "code": code,
    }
    if detail is not None:
        result["detail"] = detail
    return result


# ════════════════════════════════════════════════════════
# 预定义业务错误码
# ════════════════════════════════════════════════════════

ERROR_QUOTA_EXCEEDED = "QUOTA_EXCEEDED"
ERROR_LLM_UNAVAILABLE = "LLM_UNAVAILABLE"
ERROR_AUTH_REQUIRED = "AUTH_REQUIRED"
ERROR_TOKEN_EXPIRED = "TOKEN_EXPIRED"
ERROR_FORBIDDEN = "FORBIDDEN"
ERROR_NOT_FOUND = "NOT_FOUND"
ERROR_DATA_SOURCE_TIMEOUT = "DATA_SOURCE_TIMEOUT"
ERROR_INVALID_PARAMS = "INVALID_PARAMS"
ERROR_INTERNAL = "INTERNAL_ERROR"

