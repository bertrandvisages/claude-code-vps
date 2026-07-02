"""Ajout d'un packshot en fin de video SANS recompresser le film.

Principe : on normalise UNIQUEMENT le packshot (court) aux parametres EXACTS de
la video source (codec, resolution, fps, pix_fmt, SAR, audio), puis on
concatene en `-c copy` (stream copy) -> le gros film est copie tel quel, seul le
packshot est re-encode. Si le `-c copy` echoue (parametres exotiques), fallback
sur un concat re-encode complet.
"""

import asyncio
import json
import logging
import subprocess
from pathlib import Path

from app.services.assembler import download_file, run_ffmpeg, get_duration

logger = logging.getLogger("uvicorn.error")


async def _probe_streams(path: Path) -> tuple[dict | None, dict | None]:
    """Retourne (stream_video, stream_audio) via ffprobe, ou None si absent."""
    result = await asyncio.to_thread(
        subprocess.run,
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", str(path)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    try:
        streams = json.loads(result.stdout or "{}").get("streams", [])
    except json.JSONDecodeError:
        streams = []
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    return v, a


def _video_encoder(codec_name: str | None) -> str | None:
    """Encodeur a utiliser pour que le packshot ait le MEME codec que le film
    (indispensable au concat -c copy). None -> codec non gere, fallback."""
    return {"h264": "libx264", "hevc": "libx265", "mpeg4": "mpeg4"}.get(codec_name or "")


async def append_packshot(video_url: str, packshot_url: str, work_dir: Path) -> Path:
    """Telecharge film + packshot, normalise le packshot aux params du film,
    concatene en -c copy (fallback re-encode). Retourne le mp4 final."""
    film = work_dir / "film.mp4"
    packshot_raw = work_dir / "packshot_raw.mp4"
    await download_file(video_url, film)
    await download_file(packshot_url, packshot_raw)

    v, a = await _probe_streams(film)
    if not v:
        raise RuntimeError("Impossible de lire le flux video du film source")

    width = int(v.get("width") or 0)
    height = int(v.get("height") or 0)
    if not width or not height:
        raise RuntimeError("Dimensions du film source inconnues")
    pix_fmt = v.get("pix_fmt") or "yuv420p"
    r_frame_rate = v.get("r_frame_rate") or "25/1"
    # SAR : "N:M" -> setsar=N/M (defaut 1).
    sar = (v.get("sample_aspect_ratio") or "1:1").replace(":", "/")
    if sar in ("0/1", "0/0", ""):
        sar = "1/1"

    encoder = _video_encoder(v.get("codec_name"))

    packshot_norm = work_dir / "packshot_norm.mp4"
    out = work_dir / "film_packshot.mp4"

    # --- Normalisation du packshot aux params EXACTS du film ---
    vf = (
        f"scale=w={width}:h={height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},setsar={sar}"
    )
    norm_args = ["-i", str(packshot_raw)]
    has_audio = a is not None
    if has_audio:
        sample_rate = a.get("sample_rate") or "44100"
        channels = int(a.get("channels") or 2)
        layout = "stereo" if channels == 2 else ("mono" if channels == 1 else "stereo")
        # Piste audio silencieuse qui matche le film (codec/rate/canaux).
        a_codec = a.get("codec_name") or "aac"
        a_enc = {"aac": "aac", "mp3": "libmp3lame"}.get(a_codec, "aac")
        norm_args += ["-f", "lavfi", "-i", f"anullsrc=channel_layout={layout}:sample_rate={sample_rate}"]

    norm_args += [
        "-vf", vf,
        "-r", r_frame_rate,
        "-pix_fmt", pix_fmt,
        "-c:v", encoder or "libx264", "-preset", "fast", "-crf", "20",
    ]
    if has_audio:
        norm_args += ["-c:a", a_enc, "-ar", sample_rate, "-ac", str(channels), "-shortest"]
    else:
        norm_args += ["-an"]
    norm_args += ["-video_track_timescale", "90000", str(packshot_norm)]
    await run_ffmpeg(norm_args, desc="normalize packshot to source params")

    # --- Concat -c copy (le film n'est PAS re-encode) ---
    concat_list = work_dir / "concat.txt"
    concat_list.write_text(f"file '{film.name}'\nfile '{packshot_norm.name}'\n")

    try:
        await run_ffmpeg(
            ["-f", "concat", "-safe", "0", "-i", str(concat_list),
             "-c", "copy", "-movflags", "+faststart", str(out)],
            desc="concat film + packshot (-c copy, no recompress)",
        )
        # Sanity : le fichier doit exister, ne pas etre vide, et etre plus long
        # que le film seul (le packshot a bien ete ajoute).
        if not out.exists() or out.stat().st_size == 0:
            raise RuntimeError("sortie -c copy vide")
        film_dur = await get_duration(film)
        out_dur = await get_duration(out)
        if out_dur <= film_dur + 0.5:
            raise RuntimeError(
                f"sortie -c copy suspecte (film {film_dur:.1f}s, sortie {out_dur:.1f}s)"
            )
        logger.info(f"append_packshot: -c copy OK ({film_dur:.1f}s -> {out_dur:.1f}s)")
        return out
    except Exception as exc:
        logger.warning(f"append_packshot: -c copy a echoue ({exc}), fallback re-encode complet")

    # --- Fallback : re-encode complet (rare) ---
    fallback = work_dir / "film_packshot_reenc.mp4"
    a_out = ["-c:a", "aac", "-b:a", "192k"] if has_audio else ["-an"]
    await run_ffmpeg(
        ["-f", "concat", "-safe", "0", "-i", str(concat_list),
         "-c:v", encoder or "libx264", "-preset", "fast", "-crf", "20",
         "-pix_fmt", pix_fmt, *a_out, "-movflags", "+faststart", str(fallback)],
        desc="concat film + packshot (fallback re-encode)",
    )
    return fallback
