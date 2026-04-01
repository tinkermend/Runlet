from fastapi import APIRouter

from app.api.endpoints.check_requests import router as check_requests_router
from app.api.endpoints.page_checks import router as page_checks_router

api_router = APIRouter()
api_router.include_router(check_requests_router)
api_router.include_router(page_checks_router)
