import logging
from pathlib import Path

import httpx

from app.schemas.assemble import SupabaseConfig

logger = logging.getLogger("uvicorn.error")


async def upload_to_supabase(
    file_path: Path,
    storage_path: str,
    config: SupabaseConfig,
) -> str:
    """Upload un fichier vers Supabase Storage et retourne l'URL publique."""
    url = f"{config.url}/storage/v1/object/{config.bucket}/{storage_path}"

    headers = {
        "Authorization": f"Bearer {config.service_key}",
        "apikey": config.service_key,
        "Content-Type": "video/mp4",
        "x-upsert": "true",
    }

    async with httpx.AsyncClient(timeout=300) as client:
        with open(file_path, "rb") as f:
            resp = await client.post(url, content=f.read(), headers=headers)
        resp.raise_for_status()

    public_url = f"{config.url}/storage/v1/object/public/{config.bucket}/{storage_path}"
    logger.info(f"Uploaded to Supabase: {public_url}")
    return public_url
