"""Endpoint de preview d'etalonnage colorimetrique pour la validation manuelle.

Le rush original est telecharge, ffmpeg applique le filtre eq= sur les N
premieres secondes, et le mp4 resultant est renvoye en streaming. Pas de
persistence cote ce service : c'est l'appelant (app-vod) qui decide ou
stocker (typiquement B2 vod-rushes/preview/).
"""

import logging
import shutil
import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.schemas.assemble import ColorCorrection
from app.services.assembler import download_file, run_ffmpeg

logger = logging.getLogger("uvicorn.error")

router = APIRouter()


class GradePreviewRequest(BaseModel):
    video_url: str
    color_correction: ColorCorrection
    duration: float = Field(default=10.0, ge=1.0, le=60.0)
    width: int = 1280
    height: int = 720
    fps: int = 30


def _build_eq_filter(cc: ColorCorrection) -> str | None:
    eq_args: list[str] = []
    if cc.brightness is not None:
        eq_args.append(f"brightness={cc.brightness}")
    if cc.contrast is not None:
        eq_args.append(f"contrast={cc.contrast}")
    if cc.saturation is not None:
        eq_args.append(f"saturation={cc.saturation}")
    if cc.gamma is not None:
        eq_args.append(f"gamma={cc.gamma}")
    return f"eq={':'.join(eq_args)}" if eq_args else None


@router.post("/grade-preview")
async def grade_preview(
    data: GradePreviewRequest,
    background_tasks: BackgroundTasks,
):
    """Genere une preview colorimetrique du rush en streaming mp4.

    Telecharge le rush, applique eq= via ffmpeg sur les N premieres secondes,
    renvoie le mp4 final en stream. Le repertoire temporaire est nettoye
    apres l'envoi via BackgroundTasks.
    """
    work_dir = Path(tempfile.mkdtemp(prefix="grade-preview-"))
    background_tasks.add_task(shutil.rmtree, work_dir, ignore_errors=True)

    try:
        input_path = work_dir / "input.mp4"
        output_path = work_dir / f"preview-{uuid.uuid4().hex[:8]}.mp4"

        await download_file(data.video_url, input_path)

        eq_filter = _build_eq_filter(data.color_correction)
        vf_parts = []
        if eq_filter:
            vf_parts.append(eq_filter)
        vf_parts.append(
            f"scale=w={data.width}:h={data.height}:force_original_aspect_ratio=increase"
        )
        vf_parts.append(f"crop={data.width}:{data.height}")
        vf = ",".join(vf_parts)

        # -t avant -i serait input-only ; on le met cote output pour cut precis
        run_ffmpeg(
            [
                "-i", str(input_path),
                "-t", str(data.duration),
                "-vf", vf,
                "-r", str(data.fps),
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-an",
                "-movflags", "+faststart",
                str(output_path),
            ],
            desc="grade preview",
        )

        return FileResponse(
            path=output_path,
            media_type="video/mp4",
            filename=output_path.name,
        )
    except Exception as exc:
        logger.exception(f"grade-preview failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc)[:500])
