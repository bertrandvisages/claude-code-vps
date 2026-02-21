import asyncio
import logging
import os
from pathlib import Path

import aiofiles
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, UploadFile, File
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.job import Job
from app.models.photo import Photo
from app.schemas.job import JobCreate, JobResponse, JobApproval, CostEstimate, MontageSegment
from app.schemas.photo import PhotoAnalysisResponse
from app.services.cost_estimator import estimate_job_cost
from app.services.job_logger import subscribe, unsubscribe, format_sse
from app.workers.video_pipeline import process_job

logger = logging.getLogger("uvicorn.error")

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("/", response_model=JobResponse, status_code=201)
async def create_job(data: JobCreate, db: AsyncSession = Depends(get_db)):
    logger.info(f"POST /jobs — creating job: title={data.title!r}, music={data.include_music}, music_prompt={data.music_prompt!r}")
    try:
        job = Job(
            title=data.title,
            description=data.description,
            webhook_url=data.webhook_url,
            voiceover_text=data.voiceover_text,
            music_prompt=data.music_prompt,
            include_music=data.include_music,
            transition_type=data.transition_type,
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
        logger.info(f"Job created: id={job.id}, status={job.status}")
        return await _job_to_response(db, job)
    except Exception as exc:
        logger.exception(f"Job creation failed: {exc}")
        raise


@router.get("/", response_model=list[JobResponse])
async def list_jobs(status: str | None = None, db: AsyncSession = Depends(get_db)):
    query = select(Job).order_by(Job.created_at.desc())
    if status:
        query = query.where(Job.status == status)
    result = await db.execute(query)
    jobs = result.scalars().all()
    return [await _job_to_response(db, job) for job in jobs]


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(job_id: str, db: AsyncSession = Depends(get_db)):
    job = await _get_job_or_404(db, job_id)
    return await _job_to_response(db, job)


@router.delete("/{job_id}", status_code=204)
async def delete_job(job_id: str, db: AsyncSession = Depends(get_db)):
    job = await _get_job_or_404(db, job_id)
    await db.delete(job)
    await db.commit()


@router.post("/{job_id}/estimate", response_model=CostEstimate)
async def estimate_job(job_id: str, db: AsyncSession = Depends(get_db)):
    job = await _get_job_or_404(db, job_id)
    if job.status != "pending":
        raise HTTPException(status_code=400, detail=f"Can only estimate jobs in 'pending' status (current: {job.status})")

    count_result = await db.execute(select(func.count()).where(Photo.job_id == job.id))
    photo_count = count_result.scalar() or 0
    if photo_count == 0:
        raise HTTPException(status_code=400, detail="No photos uploaded for this job")

    voiceover_chars = len(job.voiceover_text) if job.voiceover_text else 0
    estimate = estimate_job_cost(photo_count, voiceover_chars, job.include_music)

    job.status = "awaiting_approval"
    job.estimated_cost = estimate["total"]
    await db.commit()
    await db.refresh(job)

    return {
        "job_id": job.id,
        "photo_count": photo_count,
        "voiceover_chars": voiceover_chars,
        "include_music": job.include_music,
        **estimate,
    }


@router.post("/{job_id}/approve", response_model=JobResponse)
async def approve_job(job_id: str, data: JobApproval, db: AsyncSession = Depends(get_db)):
    job = await _get_job_or_404(db, job_id)
    if job.status != "awaiting_approval":
        raise HTTPException(status_code=400, detail=f"Job is not awaiting approval (current: {job.status})")
    job.status = "processing" if data.approved else "failed"
    if not data.approved:
        job.error_message = "Job rejected by user"
    await db.commit()
    await db.refresh(job)
    return await _job_to_response(db, job)


@router.post("/{job_id}/process", response_model=JobResponse)
async def start_processing(
    job_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    job = await _get_job_or_404(db, job_id)
    if job.status != "processing":
        raise HTTPException(
            status_code=400,
            detail=f"Job must be in 'processing' status to start (current: {job.status})",
        )
    background_tasks.add_task(process_job, job_id)
    return await _job_to_response(db, job)


@router.get("/{job_id}/logs")
async def stream_logs(job_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    """Stream des logs du pipeline en temps réel via Server-Sent Events."""
    await _get_job_or_404(db, job_id)

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


UPLOAD_DIR = Path("uploads")
ALLOWED_AUDIO_EXTENSIONS = {".mp3", ".wav"}
MAX_AUDIO_SIZE = 50 * 1024 * 1024  # 50 Mo


@router.post("/{job_id}/music", response_model=JobResponse, status_code=201)
async def upload_music(
    job_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Upload un fichier audio comme musique de fond pour le job."""
    job = await _get_job_or_404(db, job_id)
    if job.status not in ("pending",):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot upload music to job in status '{job.status}'",
        )

    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_AUDIO_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"File type '{ext}' not allowed. Use: {ALLOWED_AUDIO_EXTENSIONS}",
        )

    content = await file.read()
    if len(content) > MAX_AUDIO_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"File too large (max {MAX_AUDIO_SIZE // 1024 // 1024} Mo)",
        )

    # Supprimer l'ancien fichier custom s'il existe
    if job.custom_music_path and os.path.exists(job.custom_music_path):
        os.remove(job.custom_music_path)

    job_dir = UPLOAD_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    file_path = job_dir / f"music{ext}"

    async with aiofiles.open(file_path, "wb") as f:
        await f.write(content)

    job.custom_music_path = str(file_path)
    job.include_music = True
    await db.commit()
    await db.refresh(job)
    return await _job_to_response(db, job)


@router.delete("/{job_id}/music", status_code=204)
async def delete_music(job_id: str, db: AsyncSession = Depends(get_db)):
    """Supprime le fichier musique custom du job."""
    job = await _get_job_or_404(db, job_id)
    if not job.custom_music_path:
        raise HTTPException(status_code=404, detail="No custom music uploaded")

    if os.path.exists(job.custom_music_path):
        os.remove(job.custom_music_path)

    job.custom_music_path = None
    await db.commit()


@router.get("/{job_id}/photos/analysis", response_model=list[PhotoAnalysisResponse])
async def get_photos_analysis(job_id: str, db: AsyncSession = Depends(get_db)):
    """Retourne les analyses Google Vision de toutes les photos du job (pour n8n)."""
    await _get_job_or_404(db, job_id)
    result = await db.execute(
        select(Photo).where(Photo.job_id == job_id).order_by(Photo.position)
    )
    photos = result.scalars().all()
    return [
        PhotoAnalysisResponse(
            photo_id=p.id,
            filename=p.original_filename,
            vision_labels=p.vision_labels,
            vision_description=p.vision_description,
            vision_objects=p.vision_objects,
        )
        for p in photos
    ]


@router.post("/{job_id}/montage-plan", response_model=JobResponse)
async def submit_montage_plan(
    job_id: str,
    segments: list[MontageSegment],
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Reçoit le plan de montage depuis n8n, le stocke et lance le pipeline."""
    job = await _get_job_or_404(db, job_id)

    # Valider que tous les photo_id existent dans ce job
    plan_photo_ids = {s.photo_id for s in segments}
    result = await db.execute(
        select(Photo.id).where(Photo.job_id == job_id)
    )
    existing_ids = {row[0] for row in result.all()}
    missing = plan_photo_ids - existing_ids
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown photo_ids: {', '.join(missing)}",
        )

    # Stocker le plan et lancer le pipeline
    job.montage_plan = [s.model_dump() for s in segments]
    job.status = "processing"
    await db.commit()
    await db.refresh(job)

    background_tasks.add_task(process_job, job_id)

    return await _job_to_response(db, job)


async def _get_job_or_404(db: AsyncSession, job_id: str) -> Job:
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


async def _job_to_response(db: AsyncSession, job: Job) -> dict:
    count_result = await db.execute(select(func.count()).where(Photo.job_id == job.id))
    photo_count = count_result.scalar() or 0
    return {
        **{c.name: getattr(job, c.name) for c in job.__table__.columns},
        "photo_count": photo_count,
    }
