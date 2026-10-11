"""统一错误出口：任何异常都以 {code, message, ...} JSON 返回，前端只处理一种错误形状。"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_logger

logger = get_logger(__name__)


class AppError(Exception):
    """业务错误基类：http_status / 机器可读 code / 人类可读 message。"""

    def __init__(self, http_status: int, code: str, message: str, detail: dict | None = None):
        self.http_status = http_status
        self.code = code
        self.message = message
        self.detail = detail
        super().__init__(message)


def install_error_handlers(app: FastAPI) -> None:
    def _err(status: int, body: dict) -> JSONResponse:
        return JSONResponse(status_code=status, content=body)

    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError):
        body = {"code": exc.code, "message": exc.message}
        if exc.detail:
            body["detail"] = exc.detail
        return _err(exc.http_status, body)

    # 同时接管 fastapi 与 starlette 的 HTTPException（404/405 等路由错误走 starlette 类）
    @app.exception_handler(HTTPException)
    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException):
        detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        return _err(exc.status_code, {
            "code": f"http_{exc.status_code}",
            "message": detail,
            "detail": detail,  # 兼容旧前端的 detail 字段
        })

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        errors = [
            {"loc": ".".join(str(x) for x in e.get("loc", [])), "msg": e.get("msg", "")}
            for e in exc.errors()
        ]
        return _err(422, {"code": "validation_error", "message": "请求参数校验失败", "errors": errors})

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        logger.exception("unhandled error: %s %s", request.method, request.url.path)
        return _err(500, {"code": "internal_error", "message": "服务器内部错误，请稍后重试"})
