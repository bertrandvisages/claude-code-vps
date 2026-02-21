from fastapi import Header, HTTPException

from app.config import settings


async def verify_api_key(x_api_key: str | None = Header(default=None)):
    if not settings.API_KEY:
        return  # Pas de clé configurée = pas d'auth (dev)
    if x_api_key != settings.API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
