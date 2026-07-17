"""Endpoints packshot : ajout (/append-packshot) et retrait (/strip-packshot)
d'un packshot en fin de video, SANS recompresser le film (-c copy).
ASYNCHRONES (comme /assemble) : le film peut peser plusieurs Go -> on rend un
job_id immediatement et le travail (download + ffmpeg + upload B2 streaming)
tourne en tache de fond. Le statut se suit via GET /jobs/{id}/status."""

import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.job import Job
from app.workers.append_packshot_worker import run_append_packshot
from app.workers.strip_packshot_worker import run_strip_packshot

logger = logging.getLogger("uvicorn.error")

router = APIRouter()


class AppendPackshotRequest(BaseModel):
    video_url: str
    packshot_url: str
    # Stem du fichier de sortie (sans extension) ; la cle B2 sera
    # videos/{output_name}.mp4. Fourni par app-vod (deja slugifie).
    output_name: str


class AppendPackshotResponse(BaseModel):
    job_id: str
    status: str


@router.post("/append-packshot", response_model=AppendPackshotResponse, status_code=202)
async def append_packshot_endpoint(
    data: AppendPackshotRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    job_id = str(uuid.uuid4())
    job = Job(id=job_id, status="queued")
    db.add(job)
    await db.commit()

    output_key = f"videos/{data.output_name}.mp4"
    logger.info(f"append-packshot job {job_id} created -> {output_key}")
    background_tasks.add_task(
        run_append_packshot, job_id, data.video_url, data.packshot_url, output_key
    )
    return AppendPackshotResponse(job_id=job_id, status="queued")


class StripPackshotRequest(BaseModel):
    # Film AVEC packshot.
    video_url: str
    # Packshot qui a ete concatene : sert a mesurer combien couper.
    packshot_url: str
    # Stem du fichier de sortie (sans extension) ; la cle B2 sera
    # videos/{output_name}.mp4. Fourni par app-vod (deja slugifie).
    output_name: str


@router.post("/strip-packshot", response_model=AppendPackshotResponse, status_code=202)
async def strip_packshot_endpoint(
    data: StripPackshotRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Retire le packshot de la fin d'un film (master YouTube)."""
    job_id = str(uuid.uuid4())
    job = Job(id=job_id, status="queued")
    db.add(job)
    await db.commit()

    output_key = f"videos/{data.output_name}.mp4"
    logger.info(f"strip-packshot job {job_id} created -> {output_key}")
    background_tasks.add_task(
        run_strip_packshot, job_id, data.video_url, data.packshot_url, output_key
    )
    return AppendPackshotResponse(job_id=job_id, status="queued")
