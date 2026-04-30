"""Assemblage vidéo via FFmpeg : download, speed adjust, concat, audio ducking."""

import logging
import subprocess
from pathlib import Path

import httpx

from app.schemas.assemble import AssembleRequest, AudioConfig, VideoConfig
from app.services.job_logger import emit

logger = logging.getLogger("uvicorn.error")
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


async def download_file(url: str, dest: Path) -> Path:
    """Télécharge un fichier en streaming depuis une URL vers le chemin local."""
    async with httpx.AsyncClient(timeout=120, follow_redirects=True, verify=False) as client:
        async with client.stream("GET", url) as resp:
            resp.raise_for_status()
            with open(dest, "wb") as f:
                async for chunk in resp.aiter_bytes(chunk_size=65536):
                    f.write(chunk)
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
        raw = work_dir / f"clip_{i:03d}_raw.mp4"
        await download_file(clip.video_url, raw)
        clip_paths.append(raw)
        emit(job_id, "pipeline", "info", f"Clip {i + 1}/{len(clips)} téléchargé")

    # --- 2. Cut rush (si applicable) + speed adjust + resize en UN SEUL re-encode
    # par clip. Pour les rushes, le -ss/-t est applique sur l input du re-encode,
    # ce qui est frame-accurate (pas de freeze image cause par cut -c copy avant
    # une keyframe). Pour les photos animees, -ss/-t omis : tout le clip est traite.
    emit(job_id, "ffmpeg", "info", "Cut + ajustement vitesse + résolution des clips...")
    adjusted_paths: list[Path] = []
    for i, (clip_path, clip) in enumerate(zip(clip_paths, clips)):
        adjusted = work_dir / f"adj_{i:03d}.mp4"
        target_duration = clip.duree_secondes

        # Pour rush : actual_duration = target (on cut exactement target sec).
        # Pour photo : actual_duration = duree reelle du clip telecharge.
        if clip.start_seconds is not None:
            actual_duration = float(target_duration)
        else:
            actual_duration = get_duration(clip_path)

        pts_factor = target_duration / actual_duration
        atempo = 1.0 / pts_factor
        atempo_filters = _build_atempo_chain(atempo)

        vf = (
            f"setpts={pts_factor}*PTS,"
            f"scale=w={vc.width}:h={vc.height}:force_original_aspect_ratio=increase,"
            f"crop={vc.width}:{vc.height}"
        )

        args: list[str] = []
        # Input seek rapide AVANT -i (pour les rushes) : pose le decodeur avant
        # la keyframe puis decode jusqu a start_seconds. Combine avec -t pour la
        # duree, et un re-encode propre : pas de freeze car les frames sont
        # ré-écrites avec timestamps continus à partir de 0.
        if clip.start_seconds is not None:
            args.extend(["-ss", str(clip.start_seconds)])
        args.extend(["-i", str(clip_path)])
        if clip.start_seconds is not None:
            args.extend(["-t", str(clip.duree_secondes)])
        args.extend([
            "-vf", vf,
            "-af", atempo_filters,
            "-r", str(vc.fps),
            "-c:v", vc.codec, "-preset", vc.preset, "-crf", str(vc.crf),
            "-c:a", ac.output_codec, "-b:a", ac.output_bitrate,
            "-ar", str(ac.resample_rate),
            "-avoid_negative_ts", "make_zero",
            str(adjusted),
        ])

        run_ffmpeg(args, desc=f"adjust clip {i + 1}")
        adjusted_paths.append(adjusted)
        adj_real_duration = get_duration(adjusted)
        rush_info = f" (rush cut {clip.start_seconds}s→{clip.start_seconds + target_duration}s)" if clip.start_seconds is not None else ""
        emit(job_id, "ffmpeg", "info",
             f"Clip {i + 1}/{len(clips)}{rush_info} : source={actual_duration:.3f}s → "
             f"target={target_duration:.3f}s (pts={pts_factor:.4f}) → "
             f"real_adjusted={adj_real_duration:.3f}s "
             f"(delta={adj_real_duration - target_duration:+.3f}s)")

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
    sum_target = sum(c.duree_secondes for c in clips)
    sum_adjusted = sum(get_duration(p) for p in adjusted_paths)
    emit(job_id, "ffmpeg", "info",
         f"DEBUG durations: concat_ffprobe={total_duration:.3f}s | "
         f"sum_target={sum_target:.3f}s | sum_adjusted_ffprobe={sum_adjusted:.3f}s | "
         f"drift_vs_target={total_duration - sum_target:+.3f}s")
    emit(job_id, "ffmpeg", "success", f"Vidéo concaténée : {total_duration:.1f}s")

    # --- 4. Audio (voiceover + musique avec ducking) ---
    output_filename = f"{request.entity_type}_{request.entity_id}.mp4"
    output_path = work_dir / output_filename

    # Si packshot present, on ecrit d'abord la video mixee dans un fichier tmp,
    # puis on concatene avec le packshot (silencieux) en derniere etape.
    mixed_path = (work_dir / f"mixed_{output_filename}") if request.packshot_url else output_path

    if request.voiceover_url or request.voiceover_segments or request.music_url:
        await _mix_audio(job_id, work_dir, concat_video, request, total_duration, mixed_path)
    else:
        emit(job_id, "ffmpeg", "info", "Pas d'audio externe, conservation audio clips")
        run_ffmpeg(
            ["-i", str(concat_video), "-c", "copy",
             "-movflags", vc.movflags, str(mixed_path)],
            desc="copy final",
        )

    # --- 5. Packshot silencieux concat a la fin ---
    if request.packshot_url:
        emit(job_id, "pipeline", "info", "Telechargement packshot...")
        packshot_raw = work_dir / "packshot_raw.mp4"
        await download_file(request.packshot_url, packshot_raw)

        # Re-encode packshot pour matcher fps/codec/dimensions + audio silence stereo
        packshot_norm = work_dir / "packshot_norm.mp4"
        run_ffmpeg(
            ["-i", str(packshot_raw),
             "-f", "lavfi", "-i", f"anullsrc=channel_layout=stereo:sample_rate={ac.resample_rate}",
             "-vf", f"scale=w={vc.width}:h={vc.height}:force_original_aspect_ratio=increase,crop={vc.width}:{vc.height}",
             "-r", str(vc.fps),
             "-c:v", vc.codec, "-preset", vc.preset, "-crf", str(vc.crf),
             "-c:a", ac.output_codec, "-b:a", ac.output_bitrate,
             "-shortest",
             str(packshot_norm)],
            desc="normalize packshot (silent)",
        )

        emit(job_id, "ffmpeg", "info", "Concatenation video + packshot silencieux...")
        final_concat_list = work_dir / "final_concat.txt"
        final_concat_list.write_text(
            f"file '{mixed_path.name}'\nfile '{packshot_norm.name}'\n"
        )
        run_ffmpeg(
            ["-f", "concat", "-safe", "0", "-i", str(final_concat_list),
             "-c", "copy", "-movflags", vc.movflags, str(output_path)],
            desc="concat with packshot",
        )
        emit(job_id, "pipeline", "success", f"Packshot ajoute : {get_duration(packshot_norm):.1f}s")

    emit(job_id, "pipeline", "success", f"Vidéo finale : {output_filename}")
    return output_path


def _build_segments_filter(
    segments: list,
    vo_input_idx: int,
    ac: AudioConfig,
) -> str:
    """Construit le filtre FFmpeg pour découper et positionner les segments voix off.

    Utilise atrim pour découper un seul fichier audio (input vo_input_idx)
    et adelay pour positionner chaque segment dans la timeline vidéo.
    Produit une piste [voice] stabilisée via dynaudnorm.
    """
    parts = []
    labels = []
    for i, seg in enumerate(segments):
        label = f"vo{i}"
        delay_ms = int(seg.start_seconds * 1000)
        delay_part = f",adelay={delay_ms}|{delay_ms}" if delay_ms > 0 else ""
        parts.append(
            f"[{vo_input_idx}:a]atrim=start={seg.in_seconds}:end={seg.out_seconds},"
            f"asetpts=PTS-STARTPTS,volume={ac.voiceover_volume}{delay_part}[{label}]"
        )
        labels.append(f"[{label}]")

    if len(segments) == 1:
        # Un seul segment, pas besoin de amix ni dynaudnorm
        return parts[0].replace(f"[{labels[0][1:-1]}]", "[voice]")

    mix_inputs = "".join(labels)
    parts.append(
        f"{mix_inputs}amix=inputs={len(segments)}:duration=longest"
        f":dropout_transition=0:normalize=0[voice_raw]"
    )
    # Normaliser + stabiliser le volume après le mix des segments
    parts.append("[voice_raw]loudnorm=I=-16:TP=-1.5:LRA=11,dynaudnorm=f=150:g=15[voice]")
    return ";".join(parts)


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

    segments = request.voiceover_segments

    # --- Debug: durées voiceover et segments ---
    if vo_path:
        vo_duration = get_duration(vo_path)
        emit(job_id, "ffmpeg", "info", f"DEBUG voiceover.mp3 duration: {vo_duration:.3f}s")
    if segments:
        last_seg = segments[-1]
        last_seg_audio_dur = last_seg.out_seconds - last_seg.in_seconds
        last_seg_end = last_seg.start_seconds + last_seg_audio_dur
        emit(job_id, "ffmpeg", "info",
             f"DEBUG last segment: in={last_seg.in_seconds}s out={last_seg.out_seconds}s "
             f"start={last_seg.start_seconds}s → ends at {last_seg_end:.1f}s in timeline "
             f"(video={total_duration:.1f}s, gap={total_duration - last_seg_end:.1f}s)")

    # --- Segments (atrim) + musique (ducking) ---
    if vo_path and segments and music_path:
        emit(job_id, "ffmpeg", "info",
             f"Mixage {len(segments)} segments voix off + musique avec ducking "
             f"(music_volume={ac.music_volume})")

        fade_in = f"afade=t=in:st=0:d={ac.music_fade_in_seconds}," if ac.music_fade_in_seconds > 0 else ""
        fade_out_start = max(0, total_duration - ac.music_fade_out_seconds)
        fade_out = f"afade=t=out:st={fade_out_start}:d={ac.music_fade_out_seconds}," if ac.music_fade_out_seconds > 0 else ""

        # input 0=video, 1=voiceover, 2=music
        seg_filter = _build_segments_filter(segments, 1, ac)

        filter_complex = (
            f"{seg_filter};"
            f"[voice]apad=whole_dur={total_duration},asplit[voice_out][voice_sc];"
            f"[voice_sc]volume=3[voice_sc_boosted];"
            f"[2:a]aloop=loop=-1:size=2e+09,atrim=0:{total_duration},"
            f"asetpts=PTS-STARTPTS,"
            f"loudnorm=I={ac.music_loudnorm_target}:TP=-1.5:LRA=11,"
            f"{fade_in}{fade_out}"
            f"volume={ac.music_volume},aresample={ac.resample_rate}[music];"
            f"[music][voice_sc_boosted]sidechaincompress="
            f"threshold={ac.sidechain_threshold}:ratio={ac.sidechain_ratio}:"
            f"attack={ac.sidechain_attack}:release={ac.sidechain_release}[musicduck];"
            f"[voice_out][musicduck]amix=inputs=2:duration=longest:dropout_transition=0:normalize=0[aout]"
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
            desc="segments + audio ducking mix",
        )

    # --- Segments (atrim) seuls (sans musique) ---
    elif vo_path and segments:
        emit(job_id, "ffmpeg", "info",
             f"Mixage {len(segments)} segments voix off (sans musique)...")

        seg_filter = _build_segments_filter(segments, 1, ac)
        filter_complex = seg_filter.replace("[voice]", "[aout]")

        run_ffmpeg(
            ["-i", str(video_path), "-i", str(vo_path),
             "-filter_complex", filter_complex,
             "-map", "0:v", "-map", "[aout]",
             "-c:v", vc.codec, "-preset", vc.preset, "-crf", str(vc.crf),
             "-c:a", ac.output_codec, "-b:a", ac.output_bitrate,
             "-movflags", vc.movflags,
             "-shortest",
             str(output_path)],
            desc="voiceover segments only",
        )

    # --- Voiceover unique + musique (ducking) ---
    elif vo_path and music_path:
        emit(job_id, "ffmpeg", "info",
             f"Mixage audio avec ducking (music_volume={ac.music_volume}, "
             f"threshold={ac.sidechain_threshold}, ratio={ac.sidechain_ratio})")

        fade_in = f"afade=t=in:d={ac.music_fade_in_seconds}," if ac.music_fade_in_seconds > 0 else ""
        fade_out_start = max(0, total_duration - ac.music_fade_out_seconds)
        fade_out = f"afade=t=out:st={fade_out_start}:d={ac.music_fade_out_seconds}," if ac.music_fade_out_seconds > 0 else ""

        filter_complex = (
            f"[1:a]volume={ac.voiceover_volume},apad=whole_dur={total_duration},"
            f"loudnorm=I=-16:TP=-1.5:LRA=11,"
            f"aresample={ac.resample_rate},asplit=2[vo_sc][vo_mix];"
            f"[2:a]aloop=loop=-1:size=2e+09,atrim=0:{total_duration},"
            f"loudnorm=I={ac.music_loudnorm_target}:TP=-1.5:LRA=11,"
            f"{fade_in}{fade_out}"
            f"volume={ac.music_volume},aresample={ac.resample_rate}[music_base];"
            f"[music_base][vo_sc]sidechaincompress="
            f"threshold={ac.sidechain_threshold}:ratio={ac.sidechain_ratio}:"
            f"attack={ac.sidechain_attack}:release={ac.sidechain_release}:"
            f"level_in=1:level_sc=1[ducked];"
            f"[vo_mix][ducked]amix=inputs=2:duration=first:normalize=0[aout]"
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

    # --- Voiceover unique seul ---
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

    # --- Musique seule ---
    elif music_path:
        emit(job_id, "ffmpeg", "info", "Ajout musique de fond...")
        fade_in = f"afade=t=in:d={ac.music_fade_in_seconds}," if ac.music_fade_in_seconds > 0 else ""
        fade_out_start = max(0, total_duration - ac.music_fade_out_seconds)
        fade_out = f"afade=t=out:st={fade_out_start}:d={ac.music_fade_out_seconds}," if ac.music_fade_out_seconds > 0 else ""

        filter_complex = (
            f"[1:a]aloop=loop=-1:size=2e+09,atrim=0:{total_duration},"
            f"loudnorm=I={ac.music_loudnorm_target}:TP=-1.5:LRA=11,"
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
