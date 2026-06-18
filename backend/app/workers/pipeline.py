"""Pipeline d'assemblage : download → FFmpeg → upload Supabase → update DB → webhook."""

import asyncio
import logging
import shutil
from pathlib import Path

import httpx
from sqlalchemy import select

from app.database import async_session
from app.models.job import Job
from app.schemas.assemble import AssembleRequest
from app.services.assembler import assemble_video
from app.services.job_logger import emit
from app.services.supabase import upload_to_supabase

logger = logging.getLogger("uvicorn.error")

WORK_BASE = Path("tmp")

# Limite a 1 assemblage ffmpeg simultane (1 rendu a la fois). Les jobs lances
# pendant qu'un rendu tourne restent en statut "queued" et attendent leur tour
# sur ce semaphore (file FIFO en memoire, dans le process). ffmpeg est lourd :
# serialiser evite la contention CPU/RAM et les OOM.
_ASSEMBLE_SEMAPHORE = asyncio.Semaphore(1)


async def _set_job_status(job_id: str, status: str) -> None:
    """Met a jour le statut d'un job (best-effort)."""
    try:
        async with async_session() as db:
            result = await db.execute(select(Job).where(Job.id == job_id))
            job = result.scalar_one_or_none()
            if job:
                job.status = status
                await db.commit()
    except Exception as exc:
        logger.warning(f"set_job_status({job_id}, {status}) failed: {exc}")


async def _notify_webhook(webhook_url: str, payload: dict) -> None:
    """POST le résultat du job vers le webhook n8n."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(webhook_url, json=payload)
            resp.raise_for_status()
            logger.info(f"Webhook notified: {webhook_url} → {resp.status_code}")
    except Exception as exc:
        logger.warning(f"Webhook notification failed: {exc}")


async def run_assembly(job_id: str, request: AssembleRequest) -> None:
    """Exécute le pipeline complet d'assemblage dans une BackgroundTask.

    Serialise via _ASSEMBLE_SEMAPHORE : 1 rendu ffmpeg a la fois. Tant qu'un
    autre rendu tourne, le job reste "queued" et attend ici (file FIFO).
    """
    # Attente en file (1 rendu a la fois). Si le semaphore est deja pris, on
    # reste bloque ici en statut "queued" jusqu'a liberation.
    if _ASSEMBLE_SEMAPHORE.locked():
        await _set_job_status(job_id, "queued")
        emit(job_id, "pipeline", "info", "En file d'attente (1 rendu à la fois)...")

    async with _ASSEMBLE_SEMAPHORE:
        await _run_assembly_locked(job_id, request)


async def _run_assembly_locked(job_id: str, request: AssembleRequest) -> None:
    """Corps de l'assemblage, execute une fois le semaphore acquis."""
    work_dir = WORK_BASE / job_id
    work_dir.mkdir(parents=True, exist_ok=True)

    status = "failed"
    public_url = None
    error_message = None

    try:
        await _set_job_status(job_id, "processing")
        emit(job_id, "pipeline", "info", "Démarrage du pipeline d'assemblage")

        # 1. Assembler la vidéo
        output_path = await assemble_video(job_id, request, work_dir)

        # 2. Upload vers Supabase
        emit(job_id, "pipeline", "info", "Upload vers Supabase Storage...")
        storage_path = f"montages/{request.entity_type}s/{request.entity_id}/{output_path.name}"
        public_url = await upload_to_supabase(output_path, storage_path)

        # 3. Mettre à jour le job en DB
        async with async_session() as db:
            result = await db.execute(select(Job).where(Job.id == job_id))
            job = result.scalar_one()
            job.status = "completed"
            job.output_url = public_url
            await db.commit()

        status = "completed"
        emit(job_id, "pipeline", "success", f"Terminé — {public_url}")
        logger.info(f"Job {job_id} completed: {public_url}")

    except Exception as exc:
        logger.exception(f"Job {job_id} failed: {exc}")
        error_message = str(exc)[:1000]
        emit(job_id, "pipeline", "error", f"Erreur : {exc}")

        async with async_session() as db:
            result = await db.execute(select(Job).where(Job.id == job_id))
            job = result.scalar_one_or_none()
            if job:
                job.status = "failed"
                job.error_message = error_message
                await db.commit()

    finally:
        if work_dir.exists():
            shutil.rmtree(work_dir, ignore_errors=True)

        # 4. Webhook callback vers n8n
        if request.webhook_url:
            await _notify_webhook(request.webhook_url, {
                "job_id": job_id,
                "status": status,
                "output_url": public_url,
                "error_message": error_message,
            })
