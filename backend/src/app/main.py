from __future__ import annotations

import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.router import api_router
from app.api.endpoints.console_auth import router as console_auth_router
from app.api.endpoints.console_portal import router as console_portal_router
from app.api.endpoints.console_results import router as console_results_router
from app.api.endpoints.console_tasks import router as console_tasks_router
from app.api.endpoints.console_assets import router as console_assets_router
from app.config.settings import settings
from app.infrastructure.logging import request_id_ctx


logger = logging.getLogger("runlet")


# ---------------------------------------------------------------------------
# 域级业务异常 —— 只有这几个异常会被自动转为 422 / 400。
# 其他 ValueError 等标准异常不上浮到 handler，便于调试。
# ---------------------------------------------------------------------------

class BusinessRuleError(ValueError):
    """服务层业务规则校验失败时抛出。"""


def create_app() -> FastAPI:
    from app.infrastructure.logging import setup_logging

    setup_logging(
        level=settings.log_level,
        json_output=settings.json_logs,
    )

    app = FastAPI(title="AI Playwright Platform")

    # ── 全局异常处理器 ─────────────────────────────────────────────────
    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        rid = request_id_ctx.get("-")
        logger.exception(
            "[%s] unhandled %s in %s %s",
            rid,
            type(exc).__name__,
            request.method,
            request.url.path,
        )
        return JSONResponse(
            status_code=500,
            content={
                "detail": "internal server error",
                "error_type": type(exc).__name__,
                "request_id": rid,
            },
        )

    @app.exception_handler(BusinessRuleError)
    async def _business_rule(request: Request, exc: BusinessRuleError) -> JSONResponse:
        rid = request_id_ctx.get("-")
        logger.warning("[%s] BusinessRuleError in %s %s: %s", rid, request.method, request.url.path, exc)
        return JSONResponse(
            status_code=422,
            content={
                "detail": str(exc),
                "error_type": "BusinessRuleError",
                "request_id": rid,
            },
        )

    # ── 纯 ASGI 中间件（避免 BaseHTTPMiddleware 的流式/内存问题）──
    @app.middleware("http")
    async def _timing_and_rid(request: Request, call_next):
        rid = request.headers.get("X-Request-ID", uuid.uuid4().hex[:12])
        token = request_id_ctx.set(rid)
        t0 = time.monotonic()
        try:
            response = await call_next(request)
        finally:
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            request_id_ctx.reset(token)
            response.headers["X-Request-ID"] = rid
            logger.info(
                "%s %s -> %s (%dms)",
                request.method,
                request.url.path,
                response.status_code,
                elapsed_ms,
            )
        return response

    # ── 路由 ─────────────────────────────────────────────────
    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(api_router, prefix="/api/v1")
    app.include_router(console_auth_router, prefix="/api/console")
    app.include_router(console_portal_router, prefix="/api/console")
    app.include_router(console_results_router, prefix="/api/console")
    app.include_router(console_tasks_router, prefix="/api/console")
    app.include_router(console_assets_router, prefix="/api/console")
    return app
