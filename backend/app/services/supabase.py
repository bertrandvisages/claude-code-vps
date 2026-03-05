import logging
from pathlib import Path

import httpx

from app.config import settings

logger = logging.getLogger("uvicorn.error")


async def upload_to_supabase(file_path: Path, storage_path: str) -> str:
    """Upload un fichier vers Supabase Storage et retourne l'URL publique."""
    url = f"{settings.SUPABASE_URL}/storage/v1/object/{settings.SUPABASE_BUCKET}/{storage_path}"

    headers = {
        "Authorization": f"Bearer {settings.SUPABASE_SERVICE_KEY}",
        "apikey": settings.SUPABASE_SERVICE_KEY,
        "Content-Type": "video/mp4",
        "x-upsert": "true",
    }

    logger.info(f"Uploading to Supabase: {url}")
    async with httpx.AsyncClient(timeout=300, verify=False) as client:
        with open(file_path, "rb") as f:
            resp = await client.post(url, content=f.read(), headers=headers)
        if resp.status_code >= 400:
            logger.error(f"Supabase upload failed ({resp.status_code}): {resp.text}")
        resp.raise_for_status()

    public_url = f"{settings.SUPABASE_URL}/storage/v1/object/public/{settings.SUPABASE_BUCKET}/{storage_path}"
    logger.info(f"Uploaded to Supabase: {public_url}")
    return public_url
