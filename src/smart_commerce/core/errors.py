import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: list[dict[str, Any]] | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or []


def _request_ids(request: Request) -> tuple[str, str]:
    request_id = getattr(request.state, "request_id", None) or "-"
    trace_id = getattr(request.state, "trace_id", None) or request_id
    return request_id, trace_id


def error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    details: list[dict[str, Any]],
) -> JSONResponse:
    request_id, trace_id = _request_ids(request)
    content = {
        "error": {
            "code": code,
            "message": message,
            "request_id": request_id,
            "trace_id": trace_id,
            "details": details,
        }
    }
    return JSONResponse(status_code=status_code, content=content)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
        return error_response(request, exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        details: list[dict[str, Any]] = []
        for error in exc.errors():
            field_parts = [str(part) for part in error.get("loc", []) if part != "body"]
            details.append({"field": ".".join(field_parts) or "body", "message": error.get("msg", "invalid value")})
        return error_response(request, 422, "VALIDATION_ERROR", "请求参数校验失败", details)

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code_map = {
            400: "BAD_REQUEST",
            401: "UNAUTHORIZED",
            403: "FORBIDDEN",
            404: "NOT_FOUND",
            405: "METHOD_NOT_ALLOWED",
            409: "CONFLICT",
            429: "TOO_MANY_REQUESTS",
        }
        message = exc.detail if isinstance(exc.detail, str) else "请求处理失败"
        return error_response(request, exc.status_code, code_map.get(exc.status_code, "HTTP_ERROR"), message, [])

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_exception path=%s", request.url.path)
        return error_response(request, 500, "INTERNAL_ERROR", "服务器内部错误", [])
