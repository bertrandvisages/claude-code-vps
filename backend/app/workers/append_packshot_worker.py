"""Worker background : append packshot -> upload B2. Met a jour le Job.

Separe de l'assemblage lourd (pas de semaphore ffmpeg) : le concat -c copy est
leger en CPU ; le cout est l'I/O (download/upload du film). Async -> pas de
timeout HTTP, quelle que soit la taille du film."""

import logging
import shutil
import tempfile
from pathlib import Path

from sqlalchemy import select

from app.database import async_session
from app.models.job import Job
from app.services.packshot_append import append_packshot
from app.services.b2 import upload_to_b2

logger = logging.getLogger("uvicorn.error")


async def _set_status(job_id: str, status: str, output_url: str | None = None,
                      error: str | None = None) -> None:
    try:
        async with async_session() as db:
            res = await db.execute(select(Job).where(Job.id == job_id))
            job = res.scalar_one_or_none()
            if not job:
                return
            job.status = status
            if output_url is not None:
                job.output_url = output_url
            if error is not None:
                job.error_message = error
            await db.commit()
    except Exception as exc:
        logger.warning(f"append set_status({job_id},{status}) failed: {exc}")


async def run_append_packshot(
    job_id: str, video_url: str, packshot_url: str, output_key: str
) -> None:
    work_dir = Path(tempfile.mkdtemp(prefix="append-packshot-"))
    try:
        await _set_status(job_id, "processing")
        out = await append_packshot(video_url, packshot_url, work_dir)
        b2_url = await upload_to_b2(str(out), output_key)
        await _set_status(job_id, "completed", output_url=b2_url)
        logger.info(f"append job {job_id} completed: {b2_url}")
    except Exception as exc:
        logger.exception(f"append job {job_id} failed: {exc}")
        await _set_status(job_id, "failed", error=str(exc)[:1000])
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
