from fastapi import APIRouter, Depends

from app.api.dependencies import verify_api_key
from app.api.assemble import router as assemble_router

api_router = APIRouter(prefix="/api/v1", dependencies=[Depends(verify_api_key)])
api_router.include_router(assemble_router)
