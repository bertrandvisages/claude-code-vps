"""Upload B2 (S3-compatible) en STREAMING depuis le disque.

boto3 upload_file lit le fichier par morceaux (multipart auto pour les gros
fichiers) -> aucune charge du fichier entier en memoire, indispensable pour les
films de plusieurs Go (append packshot)."""

import asyncio
import logging

import boto3
from botocore.config import Config as BotoConfig

from app.config import settings

logger = logging.getLogger("uvicorn.error")


def _client():
    return boto3.client(
        "s3",
        endpoint_url=f"https://{settings.B2_ENDPOINT}",
        region_name=settings.B2_REGION,
        aws_access_key_id=settings.B2_KEY_ID,
        aws_secret_access_key=settings.B2_APPLICATION_KEY,
        config=BotoConfig(s3={"addressing_style": "path"}),
    )


def _upload_sync(file_path: str, key: str) -> str:
    client = _client()
    client.upload_file(
        file_path,
        settings.B2_BUCKET,
        key,
        ExtraArgs={"ContentType": "video/mp4"},
    )
    # URL publique virtual-hosted (meme forme que app-vod migrate-to-b2).
    return f"https://{settings.B2_BUCKET}.s3.{settings.B2_REGION}.backblazeb2.com/{key}"


async def upload_to_b2(file_path: str, key: str) -> str:
    """Uploade un fichier local sur B2 (streaming). Retourne l'URL publique."""
    if not settings.B2_BUCKET or not settings.B2_KEY_ID:
        raise RuntimeError("B2 non configure (B2_BUCKET / B2_KEY_ID manquants)")
    logger.info(f"Uploading to B2: {settings.B2_BUCKET}/{key}")
    url = await asyncio.to_thread(_upload_sync, file_path, key)
    logger.info(f"Uploaded to B2: {url}")
    return url
