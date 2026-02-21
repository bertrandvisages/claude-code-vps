from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.config import settings

app = FastAPI(
    title="Video Montage API",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
