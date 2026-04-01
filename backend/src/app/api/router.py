from fastapi import APIRouter

from app.api.endpoints.check_requests import router as check_requests_router

api_router = APIRouter()
api_router.include_router(check_requests_router)
