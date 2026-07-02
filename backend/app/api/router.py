from fastapi import APIRouter, Depends

from app.api.dependencies import verify_api_key
from app.api.assemble import router as assemble_router
from app.api.grade import router as grade_router
from app.api.packshot import router as packshot_router

api_router = APIRouter(prefix="/api/v1", dependencies=[Depends(verify_api_key)])
api_router.include_router(assemble_router)
api_router.include_router(grade_router)
api_router.include_router(packshot_router)
