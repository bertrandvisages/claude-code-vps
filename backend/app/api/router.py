from fastapi import APIRouter, Depends

from app.api.dependencies import verify_api_key
from app.api.jobs import router as jobs_router
from app.api.photos import router as photos_router

api_router = APIRouter(prefix="/api/v1", dependencies=[Depends(verify_api_key)])
api_router.include_router(jobs_router)
api_router.include_router(photos_router)
