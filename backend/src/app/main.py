from fastapi import FastAPI

from app.api.router import api_router
from app.api.endpoints.console_auth import router as console_auth_router


def create_app() -> FastAPI:
    app = FastAPI(title="AI Playwright Platform")

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(api_router, prefix="/api/v1")
    app.include_router(console_auth_router, prefix="/api/console")
    return app
