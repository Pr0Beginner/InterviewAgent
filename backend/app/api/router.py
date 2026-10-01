from fastapi import APIRouter

from backend.app.api.routes.health import router as health_router
from backend.app.api.routes.interviews import router as interviews_router
from backend.app.api.routes.business import router as business_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(interviews_router)
api_router.include_router(business_router)
