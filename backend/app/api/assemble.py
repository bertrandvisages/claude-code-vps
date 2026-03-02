import asyncio
import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.job import Job
from app.schemas.assemble import AssembleRequest, AssembleResponse, JobStatusResponse
from app.services.job_logger import subscribe, unsubscribe, format_sse
from app.workers.pipeline import run_assembly

logger = logging.getLogger("uvicorn.error")

router = APIRouter()


@router.post("/assemble", response_model=AssembleResponse, status_code=202)
async def assemble(
    data: AssembleRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Reçoit un JSON de montage et lance l'assemblage en tâche de fond."""
    job_id = str(uuid.uuid4())

    job = Job(id=job_id, status="processing")
    db.add(job)
    await db.commit()

    logger.info(f"Job {job_id} created — hotel_id={data.hotel_id}, {len(data.clips)} clips, launching pipeline")
    background_tasks.add_task(run_assembly, job_id, data)

    return AssembleResponse(job_id=job_id, status="processing")


@router.get("/jobs/{job_id}/status", response_model=JobStatusResponse)
async def job_status(job_id: str, db: AsyncSession = Depends(get_db)):
    """Retourne le statut d'un job."""
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return JobStatusResponse(
        job_id=job.id,
        status=job.status,
        output_url=job.output_url,
        error_message=job.error_message,
    )


@router.get("/jobs/{job_id}/logs")
async def stream_logs(job_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    """Stream SSE des logs du pipeline en temps réel."""
    result = await db.execute(select(Job).where(Job.id == job_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Job not found")

    queue = subscribe(job_id)

    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    entry = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield format_sse(entry)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            unsubscribe(job_id, queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
