"""Assemblage vidéo via FFmpeg : download, speed adjust, concat, audio ducking."""

import logging
import subprocess
from pathlib import Path

import httpx

from app.schemas.assemble import AssembleRequest, AudioConfig, VideoConfig
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
    clips = sorted(request.clips, key=lambda c: c.index)
    vc = request.video_config
    ac = request.audio_config

    # --- 1. Télécharger les clips ---
    emit(job_id, "pipeline", "info", f"Téléchargement de {len(clips)} clips...")
    clip_paths: list[Path] = []
    for i, clip in enumerate(clips):
        dest = work_dir / f"clip_{i:03d}.mp4"
        await download_file(clip.video_url, dest)
        clip_paths.append(dest)
        emit(job_id, "pipeline", "info", f"Clip {i + 1}/{len(clips)} téléchargé")

    # --- 2. Speed adjust + resize chaque clip ---
    emit(job_id, "ffmpeg", "info", "Ajustement vitesse et résolution des clips...")
    adjusted_paths: list[Path] = []
    for i, (clip_path, clip) in enumerate(zip(clip_paths, clips)):
        adjusted = work_dir / f"adj_{i:03d}.mp4"
        actual_duration = get_duration(clip_path)
        target_duration = clip.duree_secondes

        pts_factor = target_duration / actual_duration
        atempo = 1.0 / pts_factor
        atempo_filters = _build_atempo_chain(atempo)

        vf = (
            f"setpts={pts_factor}*PTS,"
            f"scale={vc.width}:{vc.height}:force_original_aspect_ratio=decrease,"
            f"pad={vc.width}:{vc.height}:(ow-iw)/2:(oh-ih)/2"
        )

        run_ffmpeg(
            ["-i", str(clip_path),
             "-vf", vf,
             "-af", atempo_filters,
             "-r", str(vc.fps),
             "-c:v", vc.codec, "-preset", vc.preset, "-crf", str(vc.crf),
             "-c:a", ac.output_codec, "-b:a", ac.output_bitrate,
             "-ar", str(ac.resample_rate),
             str(adjusted)],
            desc=f"adjust clip {i + 1}",
        )
        adjusted_paths.append(adjusted)
        emit(job_id, "ffmpeg", "info", f"Clip {i + 1}/{len(clips)} : {actual_duration:.1f}s → {target_duration:.1f}s")

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
    output_filename = f"hotel_{request.hotel_id}.mp4"
    output_path = work_dir / output_filename

    if request.voiceover_url or request.music_url:
        await _mix_audio(job_id, work_dir, concat_video, request, total_duration, output_path)
    else:
        emit(job_id, "ffmpeg", "info", "Pas d'audio externe, conservation audio clips")
        run_ffmpeg(
            ["-i", str(concat_video), "-c", "copy",
             "-movflags", vc.movflags, str(output_path)],
            desc="copy final",
        )

    emit(job_id, "pipeline", "success", f"Vidéo finale : {output_filename}")
    return output_path


async def _mix_audio(
    job_id: str,
    work_dir: Path,
    video_path: Path,
    request: AssembleRequest,
    total_duration: float,
    output_path: Path,
) -> None:
    """Télécharge et mixe voix off + musique avec ducking automatique."""
    ac = request.audio_config
    vc = request.video_config

    vo_path = None
    music_path = None

    if request.voiceover_url:
        emit(job_id, "pipeline", "info", "Téléchargement voix off...")
        vo_path = work_dir / "voiceover.mp3"
        await download_file(request.voiceover_url, vo_path)

    if request.music_url:
        emit(job_id, "pipeline", "info", "Téléchargement musique...")
        music_path = work_dir / "music.mp3"
        await download_file(request.music_url, music_path)

    if vo_path and music_path:
        # Ducking : sidechaincompress avec paramètres de audio_config
        emit(job_id, "ffmpeg", "info",
             f"Mixage audio avec ducking (music_volume={ac.music_volume}, "
             f"threshold={ac.sidechain_threshold}, ratio={ac.sidechain_ratio})")

        fade_in = f"afade=t=in:d={ac.music_fade_in_seconds}," if ac.music_fade_in_seconds > 0 else ""
        fade_out_start = max(0, total_duration - ac.music_fade_out_seconds)
        fade_out = f"afade=t=out:st={fade_out_start}:d={ac.music_fade_out_seconds}," if ac.music_fade_out_seconds > 0 else ""

        filter_complex = (
            f"[1:a]volume={ac.voiceover_volume},apad=whole_dur={total_duration},"
            f"aresample={ac.resample_rate}[vo];"
            f"[2:a]aloop=loop=-1:size=2e+09,atrim=0:{total_duration},"
            f"{fade_in}{fade_out}"
            f"volume={ac.music_volume},aresample={ac.resample_rate}[music_base];"
            f"[music_base][vo]sidechaincompress="
            f"threshold={ac.sidechain_threshold}:ratio={ac.sidechain_ratio}:"
            f"attack={ac.sidechain_attack}:release={ac.sidechain_release}:"
            f"level_in=1:level_sc=1[ducked];"
            f"[vo][ducked]amix=inputs=2:duration=first:normalize=0[aout]"
        )
        run_ffmpeg(
            ["-i", str(video_path), "-i", str(vo_path), "-i", str(music_path),
             "-filter_complex", filter_complex,
             "-map", "0:v", "-map", "[aout]",
             "-c:v", vc.codec, "-preset", vc.preset, "-crf", str(vc.crf),
             "-c:a", ac.output_codec, "-b:a", ac.output_bitrate,
             "-movflags", vc.movflags,
             "-shortest",
             str(output_path)],
            desc="audio ducking mix",
        )

    elif vo_path:
        emit(job_id, "ffmpeg", "info", "Ajout voix off (sans musique)...")
        run_ffmpeg(
            ["-i", str(video_path), "-i", str(vo_path),
             "-map", "0:v", "-map", "1:a",
             "-c:v", "copy",
             "-c:a", ac.output_codec, "-b:a", ac.output_bitrate,
             "-movflags", vc.movflags,
             "-shortest",
             str(output_path)],
            desc="voiceover only",
        )

    elif music_path:
        emit(job_id, "ffmpeg", "info", "Ajout musique de fond...")
        fade_in = f"afade=t=in:d={ac.music_fade_in_seconds}," if ac.music_fade_in_seconds > 0 else ""
        fade_out_start = max(0, total_duration - ac.music_fade_out_seconds)
        fade_out = f"afade=t=out:st={fade_out_start}:d={ac.music_fade_out_seconds}," if ac.music_fade_out_seconds > 0 else ""

        filter_complex = (
            f"[1:a]aloop=loop=-1:size=2e+09,atrim=0:{total_duration},"
            f"{fade_in}{fade_out}"
            f"volume={ac.music_volume},aresample={ac.resample_rate}[music]"
        )
        run_ffmpeg(
            ["-i", str(video_path), "-i", str(music_path),
             "-filter_complex", filter_complex,
             "-map", "0:v", "-map", "[music]",
             "-c:v", "copy",
             "-c:a", ac.output_codec, "-b:a", ac.output_bitrate,
             "-movflags", vc.movflags,
             str(output_path)],
            desc="music only",
        )


def _build_atempo_chain(factor: float) -> str:
    """Construit un filtre atempo chaîné pour les facteurs hors [0.5, 100.0]."""
    if 0.5 <= factor <= 100.0:
        return f"atempo={factor}"

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
