import base64
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

# --- Google Vision credentials depuis base64 (Docker / VPS) ---
_creds_b64 = os.environ.get("GOOGLE_CREDENTIALS_BASE64")
if _creds_b64:
    _creds_path = "/tmp/google-vision.json"
    Path(_creds_path).write_bytes(base64.b64decode(_creds_b64))
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = _creds_path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.api.router import api_router
from app.config import settings
from app.database import engine
from app.models.base import Base

logger = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- Startup ---
    for d in ["uploads", "outputs", "data"]:
        Path(d).mkdir(exist_ok=True)
        logger.info(f"Directory ensured: {d}/")

    # Créer les tables SQLite si elles n'existent pas
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables ensured (create_all)")

    # Vérifier que la DB est accessible
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
        tables = [row[0] for row in result]
        logger.info(f"Database tables found: {tables}")

    yield

    # --- Shutdown ---
    await engine.dispose()


app = FastAPI(
    title="Video Montage API",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS : en prod le frontend est servi par FastAPI (même origine)
allowed_origins = [settings.FRONTEND_URL]
if settings.APP_ENV != "development":
    allowed_origins.append("*")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    logger.info(f"{request.method} {request.url.path}")
    try:
        response = await call_next(request)
        if response.status_code >= 400:
            logger.warning(f"{request.method} {request.url.path} → {response.status_code}")
        return response
    except Exception as exc:
        logger.exception(f"{request.method} {request.url.path} → Exception: {exc}")
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})


# --- API routes (prioritaires) ---
app.include_router(api_router)


@app.get("/health")
async def health_check():
    return {"status": "ok"}


# --- Fichiers vidéo générés ---
outputs_dir = Path("outputs")
outputs_dir.mkdir(exist_ok=True)
app.mount("/outputs", StaticFiles(directory="outputs"), name="outputs")

# --- Frontend React (build Vite) ---
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "static" / "frontend"

if FRONTEND_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIR / "assets"), name="frontend-assets")

    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        """Sert index.html pour le routing React, ou le fichier statique demandé."""
        file_path = (FRONTEND_DIR / full_path).resolve()
        # Protection traversée de chemin
        if file_path.is_relative_to(FRONTEND_DIR) and full_path and file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(FRONTEND_DIR / "index.html")
