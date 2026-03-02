"""Assemblage vidéo via FFmpeg : download, speed adjust, concat, audio ducking."""

import asyncio
import logging
import subprocess
from pathlib import Path

import httpx

from app.schemas.assemble import AssembleRequest
from app.services.job_logger import emit

logger = logging.getLogger("uvicorn.error")


async def download_file(url: str, dest: Path) -> Path:
    """Télécharge un fichier depuis une URL vers le chemin local."""
    async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        dest.write_bytes(resp.content)
    return dest


def run_ffmpeg(args: list[str], desc: str = "") -> None:
    """Exécute une commande FFmpeg et lève une exception en cas d'erreur."""
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"] + args
    logger.info(f"FFmpeg {desc}: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg error ({desc}): {result.stderr.strip()}")


def get_duration(file_path: Path) -> float:
    """Retourne la durée d'un fichier média en secondes."""
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(file_path)],
        capture_output=True, text=True, timeout=30,
    )
    return float(result.stdout.strip())


async def assemble_video(job_id: str, request: AssembleRequest, work_dir: Path) -> Path:
    """Pipeline complet d'assemblage vidéo."""
    segments = sorted(request.segments, key=lambda s: s.order)
    width, height = request.resolution.split("x")

    # --- 1. Télécharger les clips ---
    emit(job_id, "pipeline", "info", f"Téléchargement de {len(segments)} clips...")
    clip_paths: list[Path] = []
    for i, seg in enumerate(segments):
        dest = work_dir / f"clip_{i:03d}.mp4"
        await download_file(seg.video_url, dest)
        clip_paths.append(dest)
        emit(job_id, "pipeline", "info", f"Clip {i + 1}/{len(segments)} téléchargé")

    # --- 2. Speed adjust + resize chaque clip ---
    emit(job_id, "ffmpeg", "info", "Ajustement vitesse et résolution des clips...")
    adjusted_paths: list[Path] = []
    for i, (clip_path, seg) in enumerate(zip(clip_paths, segments)):
        adjusted = work_dir / f"adj_{i:03d}.mp4"
        actual_duration = get_duration(clip_path)
        target_duration = seg.duration_seconds

        # Facteur PTS : >1 = ralentir, <1 = accélérer
        pts_factor = target_duration / actual_duration

        # atempo accepte seulement [0.5, 100.0], et il faut chaîner pour les valeurs extrêmes
        atempo = 1.0 / pts_factor
        atempo_filters = _build_atempo_chain(atempo)

        vf = f"setpts={pts_factor}*PTS,scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"

        run_ffmpeg(
            ["-i", str(clip_path),
             "-vf", vf,
             "-af", atempo_filters,
             "-r", str(request.fps),
             "-c:v", "libx264", "-preset", "fast", "-crf", "23",
             "-c:a", "aac", "-b:a", "192k",
             str(adjusted)],
            desc=f"adjust clip {i + 1}",
        )
        adjusted_paths.append(adjusted)
        emit(job_id, "ffmpeg", "info", f"Clip {i + 1}/{len(segments)} : {actual_duration:.1f}s → {target_duration:.1f}s")

    # --- 3. Concaténer les clips (cut franc) ---
    emit(job_id, "ffmpeg", "info", "Concaténation des clips...")
    concat_list = work_dir / "concat.txt"
    concat_list.write_text("\n".join(f"file '{p.name}'" for p in adjusted_paths))
    concat_video = work_dir / "concat.mp4"
    run_ffmpeg(
        ["-f", "concat", "-safe", "0", "-i", str(concat_list),
         "-c", "copy", str(concat_video)],
        desc="concat",
    )
    total_duration = get_duration(concat_video)
    emit(job_id, "ffmpeg", "success", f"Vidéo concaténée : {total_duration:.1f}s")

    # --- 4. Audio (voiceover + musique avec ducking) ---
    output_path = work_dir / request.output_filename
    audio = request.audio

    if audio and (audio.voiceover_url or audio.music_url):
        output_path = await _mix_audio(
            job_id, work_dir, concat_video, audio.voiceover_url, audio.music_url,
            audio.music_volume_base, total_duration, request, output_path,
        )
    else:
        # Pas d'audio externe — garder l'audio des clips
        emit(job_id, "ffmpeg", "info", "Pas d'audio externe, conservation audio clips")
        run_ffmpeg(
            ["-i", str(concat_video), "-c", "copy", str(output_path)],
            desc="copy final",
        )

    emit(job_id, "pipeline", "success", f"Vidéo finale : {request.output_filename}")
    return output_path


async def _mix_audio(
    job_id: str,
    work_dir: Path,
    video_path: Path,
    voiceover_url: str | None,
    music_url: str | None,
    music_volume_base: float,
    total_duration: float,
    request: AssembleRequest,
    output_path: Path,
) -> Path:
    """Télécharge et mixe voix off + musique avec ducking automatique."""
    width, height = request.resolution.split("x")

    vo_path = None
    music_path = None

    if voiceover_url:
        emit(job_id, "pipeline", "info", "Téléchargement voix off...")
        vo_path = work_dir / "voiceover.mp3"
        await download_file(voiceover_url, vo_path)

    if music_url:
        emit(job_id, "pipeline", "info", "Téléchargement musique...")
        music_path = work_dir / "music.mp3"
        await download_file(music_url, music_path)

    if vo_path and music_path:
        # Ducking : sidechaincompress
        emit(job_id, "ffmpeg", "info", f"Mixage audio avec ducking (musique base: {music_volume_base})...")
        filter_complex = (
            f"[1:a]apad=whole_dur={total_duration}[vo];"
            f"[2:a]aloop=loop=-1:size=2e+09,atrim=0:{total_duration},"
            f"volume={music_volume_base}[music_base];"
            f"[music_base][vo]sidechaincompress="
            f"threshold=0.015:ratio=10:attack=500:release=500:"
            f"level_in=1:level_sc=1[ducked];"
            f"[vo][ducked]amix=inputs=2:duration=first:normalize=0[aout]"
        )
        run_ffmpeg(
            ["-i", str(video_path), "-i", str(vo_path), "-i", str(music_path),
             "-filter_complex", filter_complex,
             "-map", "0:v", "-map", "[aout]",
             "-c:v", "libx264", "-preset", "fast", "-crf", "23",
             "-c:a", "aac", "-b:a", "192k",
             "-shortest",
             str(output_path)],
            desc="audio ducking mix",
        )

    elif vo_path:
        emit(job_id, "ffmpeg", "info", "Ajout voix off (sans musique)...")
        run_ffmpeg(
            ["-i", str(video_path), "-i", str(vo_path),
             "-map", "0:v", "-map", "1:a",
             "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
             "-shortest",
             str(output_path)],
            desc="voiceover only",
        )

    elif music_path:
        emit(job_id, "ffmpeg", "info", "Ajout musique de fond...")
        filter_complex = (
            f"[1:a]aloop=loop=-1:size=2e+09,atrim=0:{total_duration},"
            f"volume={music_volume_base},afade=t=out:st={max(0, total_duration - 3)}:d=3[music]"
        )
        run_ffmpeg(
            ["-i", str(video_path), "-i", str(music_path),
             "-filter_complex", filter_complex,
             "-map", "0:v", "-map", "[music]",
             "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
             str(output_path)],
            desc="music only",
        )

    return output_path


def _build_atempo_chain(factor: float) -> str:
    """Construit un filtre atempo chaîné pour les facteurs hors [0.5, 100.0]."""
    if 0.5 <= factor <= 100.0:
        return f"atempo={factor}"

    # Chaîner des atempo pour les facteurs extrêmes
    filters = []
    remaining = factor
    while remaining < 0.5:
        filters.append("atempo=0.5")
        remaining /= 0.5
    while remaining > 100.0:
        filters.append("atempo=100.0")
        remaining /= 100.0
    filters.append(f"atempo={remaining}")
    return ",".join(filters)
