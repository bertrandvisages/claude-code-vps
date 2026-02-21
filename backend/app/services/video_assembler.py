import logging
from pathlib import Path

from moviepy import (
    AudioFileClip,
    CompositeAudioClip,
    CompositeVideoClip,
    VideoFileClip,
    afx,
    concatenate_videoclips,
    vfx,
)
from proglog import ProgressBarLogger

from app.config import settings

logger = logging.getLogger(__name__)


class _FFmpegLogger(ProgressBarLogger):
    """Capture la sortie FFmpeg dans les logs Python."""

    def callback(self, **changes):
        for key, value in changes.items():
            logger.info(f"FFmpeg [{key}]: {value}")

    def bars_callback(self, bar, attr, value, old_value=None):
        if attr == "total":
            logger.info(f"FFmpeg {bar}: total={value}")
        elif attr == "index" and value == old_value:
            pass  # skip duplicate progress updates

OUTPUTS_DIR = Path("outputs")
CROSSFADE_DURATION = 0.5  # secondes de chevauchement
MIN_CLIP_SIZE = 10_000  # 10 Ko minimum pour un clip vidéo valide


def _validate_clip_files(clip_paths: list[str]) -> None:
    """Vérifie que tous les fichiers clips existent et ne sont pas vides."""
    for path in clip_paths:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Clip introuvable : {path}")
        size = p.stat().st_size
        if size < MIN_CLIP_SIZE:
            raise ValueError(
                f"Clip trop petit ({size} octets), probablement corrompu : {path}"
            )
        logger.info(f"Clip OK : {p.name} ({size / 1024:.0f} Ko)")


def assemble_video(
    clip_paths: list[str],
    job_id: str,
    voiceover_path: str | None = None,
    music_path: str | None = None,
    transition_type: str = "crossfade",
    segment_durations: list[float] | None = None,
    segment_volumes: list[float] | None = None,
) -> str:
    """Assemble les clips vidéo + audio en une vidéo finale MP4.

    Args:
        clip_paths: Liste ordonnée des chemins vers les clips MP4.
        job_id: ID du job pour le dossier de sortie.
        voiceover_path: Chemin vers le fichier voix off (optionnel).
        music_path: Chemin vers le fichier musique (optionnel).
        transition_type: "crossfade" ou "cut".
        segment_durations: Durées cibles par clip (ajuste la vitesse).
        segment_volumes: Volumes musique par segment (0.0 à 1.0).

    Retourne le chemin de la vidéo finale.
    """
    # Valider les fichiers d'entrée
    _validate_clip_files(clip_paths)

    target_w = settings.VIDEO_WIDTH
    target_h = settings.VIDEO_HEIGHT

    # Charger, redimensionner et ajuster la vitesse des clips
    clips = []
    for idx, path in enumerate(clip_paths):
        clip = VideoFileClip(path)
        logger.info(
            f"Clip chargé : {Path(path).name} — "
            f"{clip.w}x{clip.h}, {clip.duration:.1f}s, {clip.fps}fps"
        )
        clip = clip.with_effects([vfx.Resize((target_w, target_h))])

        # Ajuster la vitesse si une durée cible est fournie
        if segment_durations and idx < len(segment_durations):
            desired = segment_durations[idx]
            actual = clip.duration
            if abs(actual - desired) > 0.1:
                speed_factor = actual / desired
                clip = clip.with_effects([vfx.MultiplySpeed(speed_factor)])
                logger.info(
                    f"Clip {idx}: vitesse ajustée {actual:.1f}s → {desired:.1f}s "
                    f"(facteur: {speed_factor:.2f}x)"
                )

        clips.append(clip)

    # Assembler les clips
    if transition_type == "crossfade" and len(clips) > 1:
        video = _crossfade_clips(clips)
    else:
        video = _cut_clips(clips)

    logger.info(
        f"Vidéo assemblée : {video.w}x{video.h}, {video.duration:.1f}s, "
        f"transition: {transition_type}"
    )

    # Mixer l'audio
    audio_tracks = []
    video_duration = video.duration

    # La durée finale inclut la voix off si elle dépasse la vidéo
    final_duration = video_duration

    if voiceover_path:
        voiceover = AudioFileClip(voiceover_path)
        logger.info(f"Voix off chargée : {voiceover.duration:.1f}s")
        audio_tracks.append(voiceover)
        if voiceover.duration > final_duration:
            final_duration = voiceover.duration
            logger.info(
                f"Voix off plus longue que la vidéo — "
                f"durée finale ajustée : {final_duration:.1f}s"
            )

    if music_path:
        music = AudioFileClip(music_path)
        logger.info(f"Musique chargée : {music.duration:.1f}s")
        # Boucler la musique si plus courte que la durée finale
        if music.duration < final_duration:
            music = music.with_effects([afx.AudioLoop(duration=final_duration)])
        else:
            music = music.subclipped(0, final_duration)
        # Fade out sur les 3 dernières secondes
        fade_duration = min(3.0, music.duration)
        music = music.with_effects([afx.AudioFadeOut(fade_duration)])
        logger.info(f"Fade out appliqué : {fade_duration:.1f}s")

        if segment_volumes and segment_durations:
            # Volume par segment : découper la musique et appliquer des volumes différents
            music_segments = []
            current_time = 0.0
            overlap = CROSSFADE_DURATION if transition_type == "crossfade" and len(clips) > 1 else 0.0
            for idx, dur in enumerate(segment_durations):
                vol = segment_volumes[idx] if idx < len(segment_volumes) else 0.2
                end_time = min(current_time + dur, final_duration)
                if current_time >= final_duration:
                    break
                segment = music.subclipped(current_time, end_time)
                segment = segment.with_effects([afx.MultiplyVolume(vol)])
                segment = segment.with_start(current_time)
                music_segments.append(segment)
                logger.info(
                    f"Musique segment {idx}: {current_time:.1f}s-{end_time:.1f}s, "
                    f"volume={vol}"
                )
                # Le prochain segment commence après, moins l'overlap du crossfade
                current_time = end_time - (overlap if idx < len(segment_durations) - 1 else 0.0)

            # Remplir le reste si nécessaire
            if current_time < final_duration:
                remaining = music.subclipped(current_time, final_duration)
                last_vol = segment_volumes[-1] if segment_volumes else 0.2
                remaining = remaining.with_effects([afx.MultiplyVolume(last_vol)])
                remaining = remaining.with_start(current_time)
                music_segments.append(remaining)

            music_audio = CompositeAudioClip(music_segments)
            audio_tracks.append(music_audio)
        else:
            # Mode legacy : volume global 0.2 sous la voix off
            if voiceover_path:
                music = music.with_effects([afx.MultiplyVolume(0.2)])
            audio_tracks.append(music)

    if audio_tracks:
        final_audio = CompositeAudioClip(audio_tracks)
        video = video.with_audio(final_audio)

    # Exporter
    job_dir = OUTPUTS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    output_path = job_dir / "final.mp4"

    logger.info(
        f"Export FFmpeg → {output_path} "
        f"(codec: {settings.VIDEO_CODEC}, fps: {settings.VIDEO_FPS}, audio: aac)"
    )

    ffmpeg_logger = _FFmpegLogger()
    try:
        video.write_videofile(
            str(output_path),
            codec=settings.VIDEO_CODEC,
            fps=settings.VIDEO_FPS,
            audio_codec="aac",
            logger=ffmpeg_logger,
        )
    except Exception as e:
        logger.error(f"FFmpeg a échoué : {e}")
        raise RuntimeError(f"FFmpeg a échoué lors de l'export : {e}") from e

    # Vérifier le fichier de sortie
    output_size = output_path.stat().st_size
    logger.info(f"Fichier généré : {output_size / 1024:.0f} Ko")
    if output_size < MIN_CLIP_SIZE:
        raise RuntimeError(
            f"Vidéo finale corrompue ({output_size} octets). "
            f"Vérifiez les logs FFmpeg ci-dessus."
        )

    # Fermer les clips pour libérer les ressources
    for clip in clips:
        clip.close()
    video.close()

    return str(output_path)


def _crossfade_clips(clips: list) -> CompositeVideoClip:
    """Assemble les clips avec fondu enchaîné."""
    composed = []
    current_start = 0.0

    for i, clip in enumerate(clips):
        if i == 0:
            composed.append(clip.with_start(0))
        else:
            start = current_start - CROSSFADE_DURATION
            composed.append(
                clip.with_start(start).with_effects(
                    [vfx.CrossFadeIn(CROSSFADE_DURATION)]
                )
            )
            current_start = start
        current_start += clip.duration

    total_duration = current_start
    fps = clips[0].fps if clips else settings.VIDEO_FPS
    result = CompositeVideoClip(
        composed, size=(settings.VIDEO_WIDTH, settings.VIDEO_HEIGHT)
    ).with_duration(total_duration).with_fps(fps)
    logger.info(f"Crossfade assemblé : {total_duration:.1f}s, fps={fps}")
    return result


def _cut_clips(clips: list) -> VideoFileClip:
    """Assemble les clips en coupe franche (concaténation simple)."""
    result = concatenate_videoclips(clips, method="compose")
    logger.info(f"Cut assemblé : {result.duration:.1f}s, fps={result.fps}")
    return result
