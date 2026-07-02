"""Endpoint leger : ajoute un packshot en fin d'une video existante SANS
recompresser le film (concat -c copy). Synchrone (quelques secondes) : on
n'occupe pas le semaphore lourd des assemblages complets."""

import logging
import shutil
import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from app.services.packshot_append import append_packshot
from app.services.supabase import upload_to_supabase

logger = logging.getLogger("uvicorn.error")

router = APIRouter()


class AppendPackshotRequest(BaseModel):
    video_url: str
    packshot_url: str
    # Prefixe/nom de fichier de sortie cote Supabase (l'appelant migrera ensuite
    # vers B2 s'il le souhaite). Optionnel.
    output_name: str | None = None


class AppendPackshotResponse(BaseModel):
    output_url: str


@router.post("/append-packshot", response_model=AppendPackshotResponse)
async def append_packshot_endpoint(
    data: AppendPackshotRequest,
    background_tasks: BackgroundTasks,
):
    work_dir = Path(tempfile.mkdtemp(prefix="append-packshot-"))
    background_tasks.add_task(shutil.rmtree, work_dir, ignore_errors=True)
    try:
        out = await append_packshot(data.video_url, data.packshot_url, work_dir)
        name = data.output_name or f"{uuid.uuid4().hex[:12]}"
        storage_path = f"packshot-append/{name}.mp4"
        url = await upload_to_supabase(out, storage_path)
        return AppendPackshotResponse(output_url=url)
    except Exception as exc:
        logger.exception(f"append-packshot failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc)[:500])
