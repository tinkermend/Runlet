from fastapi import FastAPI

from app.api.router import api_router
from app.api.endpoints.console_auth import router as console_auth_router
from app.api.endpoints.console_portal import router as console_portal_router
from app.api.endpoints.console_results import router as console_results_router
from app.api.endpoints.console_tasks import router as console_tasks_router
from app.api.endpoints.console_assets import router as console_assets_router
from app.config.settings import settings


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name)

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
