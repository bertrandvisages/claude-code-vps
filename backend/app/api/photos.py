import os
import uuid
import aiofiles
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.job import Job
from app.models.photo import Photo
from app.schemas.photo import PhotoResponse
from app.services.photo_analyzer import analyze_photo, generate_description

router = APIRouter(prefix="/jobs/{job_id}/photos", tags=["photos"])

UPLOAD_DIR = Path("uploads")
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 Mo


@router.post("/", response_model=PhotoResponse, status_code=201)
async def upload_photo(
    job_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    # Vérifier que le job existe et accepte des photos
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status not in ("pending",):
        raise HTTPException(status_code=400, detail=f"Cannot add photos to job in status '{job.status}'")

    # Valider l'extension
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"File type '{ext}' not allowed. Use: {ALLOWED_EXTENSIONS}")

    # Valider la taille
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail=f"File too large (max {MAX_FILE_SIZE // 1024 // 1024} Mo)")

    # Compter les photos existantes pour la position
    count_result = await db.execute(select(Photo).where(Photo.job_id == job_id))
    existing = len(count_result.scalars().all())

    # Sauvegarder le fichier
    filename = f"{uuid.uuid4()}{ext}"
    job_dir = UPLOAD_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    file_path = job_dir / filename

    async with aiofiles.open(file_path, "wb") as f:
        await f.write(content)

    # Créer l'enregistrement en base
    photo = Photo(
        job_id=job_id,
        filename=filename,
        original_filename=file.filename or "unknown",
        file_path=str(file_path),
        position=existing,
    )

    # Auto-analyse Google Vision
    try:
        result = await analyze_photo(str(file_path))
        photo.vision_labels = result["labels"]
        photo.vision_objects = result["objects"]
        photo.vision_description = generate_description(
            result["labels"], result["objects"]
        )
    except Exception:
        pass  # L'upload reste valide même si Vision échoue

    db.add(photo)
    await db.commit()
    await db.refresh(photo)
    return photo


@router.get("/", response_model=list[PhotoResponse])
async def list_photos(job_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Photo).where(Photo.job_id == job_id).order_by(Photo.position)
    )
    return result.scalars().all()


@router.delete("/{photo_id}", status_code=204)
async def delete_photo(job_id: str, photo_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Photo).where(Photo.id == photo_id, Photo.job_id == job_id)
    )
    photo = result.scalar_one_or_none()
    if not photo:
        raise HTTPException(status_code=404, detail="Photo not found")

    # Supprimer le fichier
    if os.path.exists(photo.file_path):
        os.remove(photo.file_path)

    await db.delete(photo)
    await db.commit()
