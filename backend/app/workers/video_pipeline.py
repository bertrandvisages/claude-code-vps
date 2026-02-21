import asyncio
import logging
from datetime import datetime

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.models.job import Job
from app.models.photo import Photo
from app.services.photo_analyzer import analyze_photo, generate_animation_prompt, generate_description
from app.services.voice_generator import generate_voiceover
from app.services.music_generator import generate_music
from app.services.kie_animator import animate_photo
from app.services.video_assembler import assemble_video
from app.services.cost_estimator import estimate_job_cost
from app.services.job_logger import emit

logger = logging.getLogger(__name__)


async def process_job(job_id: str) -> None:
    """Pipeline complet de génération vidéo pour un job."""
    async with async_session() as db:
        try:
            job = await _get_job(db, job_id)
            if not job:
                logger.error(f"Job {job_id} not found")
                return

            photos = await _get_photos(db, job_id)
            if not photos:
                await _fail_job(db, job, "No photos found for this job")
                emit(job_id, "pipeline", "error", "Aucune photo trouvée pour ce job")
                return

            total_steps = len(photos) * 2 + 3
            current_step = 0

            emit(job_id, "pipeline", "info",
                 f"Démarrage du pipeline — {len(photos)} photo(s), "
                 f"{total_steps} étapes au total")

            # ── Étape 1 : Analyse Google Vision ──
            emit(job_id, "vision", "info",
                 f"Analyse de {len(photos)} photo(s) via Google Vision...")
            animation_prompts = {}
            for i, photo in enumerate(photos, 1):
                if photo.vision_labels is not None:
                    # Déjà analysée à l'upload — réutiliser
                    emit(job_id, "vision", "info",
                         f"Photo {i}/{len(photos)} : analyse existante réutilisée")
                    prompt = generate_animation_prompt(
                        photo.vision_labels, photo.vision_objects or []
                    )
                    animation_prompts[photo.id] = prompt
                else:
                    emit(job_id, "vision", "info",
                         f"Analyse photo {i}/{len(photos)} : {photo.original_filename}")
                    result = await analyze_photo(photo.file_path, job_id)
                    animation_prompts[photo.id] = result["animation_prompt"]
                    # Stocker pour réutilisation future
                    photo.vision_labels = result["labels"]
                    photo.vision_objects = result["objects"]
                    photo.vision_description = generate_description(
                        result["labels"], result["objects"]
                    )
                    await db.commit()
                emit(job_id, "vision", "success",
                     f"Photo {i} — prompt : \"{animation_prompts[photo.id]}\"")
                current_step += 1
                await _update_progress(db, job, current_step, total_steps)

            # ── Étape 2 : Génération voix off + musique (en parallèle) ──
            voiceover_path = None
            music_path = None

            # Préparer les tâches parallèles
            tasks = {}

            if job.voiceover_text:
                chars = len(job.voiceover_text)
                emit(job_id, "elevenlabs", "info",
                     f"Génération voix off ({chars} caractères)...")
                tasks["voiceover"] = generate_voiceover(job.voiceover_text, job_id)

            if job.custom_music_path:
                music_path = job.custom_music_path
                emit(job_id, "pipeline", "info",
                     f"Musique custom utilisée → {music_path}")
            elif job.include_music and job.music_prompt:
                emit(job_id, "music", "info",
                     f"Génération musicale via Suno...")
                tasks["music"] = generate_music(job.music_prompt, job_id)
            else:
                emit(job_id, "pipeline", "info", "Pas de musique de fond")

            # Exécuter en parallèle
            if tasks:
                results = await asyncio.gather(
                    *tasks.values(), return_exceptions=True
                )
                task_keys = list(tasks.keys())
                for key, result in zip(task_keys, results):
                    if isinstance(result, Exception):
                        emit(job_id, "pipeline", "warning",
                             f"{key} a échoué : {result} — le pipeline continue")
                    elif key == "voiceover" and result:
                        voiceover_path = result
                        emit(job_id, "elevenlabs", "success",
                             f"Voix off générée → {voiceover_path}")
                    elif key == "music" and result:
                        music_path = result

            current_step += 1
            await _update_progress(db, job, current_step, total_steps)

            # ── Étape 3 : Animation Kie.ai ──
            # Construire le segment_map et l'ordre des photos selon le plan de montage
            segment_map = {}
            if job.montage_plan:
                for seg in job.montage_plan:
                    segment_map[seg["photo_id"]] = seg
                # Ordre du plan de montage
                photo_by_id = {p.id: p for p in photos}
                ordered_photos = [
                    photo_by_id[seg["photo_id"]]
                    for seg in job.montage_plan
                    if seg["photo_id"] in photo_by_id
                ]
                emit(job_id, "pipeline", "info",
                     f"Plan de montage détecté — {len(ordered_photos)} segments")
            else:
                ordered_photos = photos  # ordre d'upload (position)

            emit(job_id, "kie", "info",
                 f"Animation de {len(ordered_photos)} photo(s) via Kie.ai...")
            clip_paths = []
            segment_durations = []
            segment_volumes = []
            skipped = 0

            for i, photo in enumerate(ordered_photos, 1):
                seg = segment_map.get(photo.id, {})
                desired_duration = seg.get("duration_seconds", 5.0)
                music_vol = seg.get("music_volume", 0.2)
                segment_text = seg.get("segment_text", "")

                # Kie.ai supporte "5" ou "10"
                kie_duration = "5" if desired_duration < 6.0 else "10"

                prompt = animation_prompts.get(photo.id, "")

                # LiveLog : détails du segment
                if segment_text:
                    emit(job_id, "pipeline", "info",
                         f"Segment {i}/{len(ordered_photos)} — "
                         f"Photo: {photo.original_filename}, "
                         f"Texte: \"{segment_text[:80]}{'...' if len(segment_text) > 80 else ''}\", "
                         f"Durée: {desired_duration}s (clip Kie: {kie_duration}s), "
                         f"Volume musique: {music_vol}")

                emit(job_id, "kie", "info",
                     f"Animation photo {i}/{len(ordered_photos)} — prompt : \"{prompt}\"")
                clip_path = await animate_photo(
                    image_path=photo.file_path,
                    job_id=job_id,
                    photo_id=photo.id,
                    prompt=prompt,
                    duration=kie_duration,
                )
                if clip_path:
                    clip_paths.append(clip_path)
                    segment_durations.append(desired_duration)
                    segment_volumes.append(music_vol)
                    emit(job_id, "kie", "success",
                         f"Clip {i}/{len(ordered_photos)} reçu → {clip_path}")
                else:
                    skipped += 1
                    emit(job_id, "kie", "warning",
                         f"Photo {i}/{len(ordered_photos)} ignorée — clip non généré")
                current_step += 1
                await _update_progress(db, job, current_step, total_steps)

            if not clip_paths:
                await _fail_job(db, job, "Aucun clip vidéo n'a pu être généré")
                emit(job_id, "pipeline", "error",
                     "Aucun clip généré — impossible d'assembler la vidéo")
                return
            if skipped:
                emit(job_id, "kie", "warning",
                     f"{skipped} photo(s) ignorée(s) — assemblage avec "
                     f"{len(clip_paths)} clip(s) sur {len(ordered_photos)}")

            # ── Étape 4 : Assemblage FFmpeg/MoviePy ──
            if job.montage_plan:
                emit(job_id, "ffmpeg", "info",
                     f"Assemblage avec plan de montage — "
                     f"{len(clip_paths)} segments, "
                     f"durées: {segment_durations}, "
                     f"volumes: {segment_volumes}")
            emit(job_id, "ffmpeg", "info",
                 f"Assemblage vidéo — {len(clip_paths)} clips, "
                 f"transition: {job.transition_type}, "
                 f"audio: {'voix off + ' if voiceover_path else ''}"
                 f"{'musique' if music_path else 'aucun'}")
            output_path = await asyncio.to_thread(
                assemble_video,
                clip_paths=clip_paths,
                job_id=job_id,
                voiceover_path=voiceover_path,
                music_path=music_path,
                transition_type=job.transition_type,
                segment_durations=segment_durations if job.montage_plan else None,
                segment_volumes=segment_volumes if job.montage_plan else None,
            )
            emit(job_id, "ffmpeg", "success",
                 f"Vidéo assemblée → {output_path}")
            current_step += 1
            await _update_progress(db, job, current_step, total_steps)

            # ── Étape 5 : Finalisation ──
            voiceover_chars = len(job.voiceover_text) if job.voiceover_text else 0
            cost = estimate_job_cost(len(photos), voiceover_chars, job.include_music)

            job.status = "completed"
            job.progress = 100
            job.output_url = f"/outputs/{job_id}/final.mp4"
            job.actual_cost = cost["total"]
            job.updated_at = datetime.utcnow()
            await db.commit()

            emit(job_id, "pipeline", "success",
                 f"Pipeline terminé — coût réel : {cost['total']:.3f} USD")
            logger.info(f"[{job_id}] Completed! Output: {output_path}")
            await _send_webhook(job, "completed")

        except Exception as e:
            logger.exception(f"[{job_id}] Pipeline failed: {e}")
            emit(job_id, "pipeline", "error", f"Erreur fatale : {e}")
            async with async_session() as db2:
                job2 = await _get_job(db2, job_id)
                if job2:
                    await _fail_job(db2, job2, str(e))
                    await _send_webhook(job2, "failed")


async def _get_job(db: AsyncSession, job_id: str) -> Job | None:
    result = await db.execute(select(Job).where(Job.id == job_id))
    return result.scalar_one_or_none()


async def _get_photos(db: AsyncSession, job_id: str) -> list[Photo]:
    result = await db.execute(
        select(Photo).where(Photo.job_id == job_id).order_by(Photo.position)
    )
    return list(result.scalars().all())


async def _update_progress(db: AsyncSession, job: Job, step: int, total: int) -> None:
    job.progress = min(int((step / total) * 100), 99)
    job.updated_at = datetime.utcnow()
    await db.commit()


async def _fail_job(db: AsyncSession, job: Job, error: str) -> None:
    job.status = "failed"
    job.error_message = error
    job.updated_at = datetime.utcnow()
    await db.commit()


async def _send_webhook(job: Job, status: str) -> None:
    """Envoie une notification webhook à n8n."""
    if not job.webhook_url:
        return
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                job.webhook_url,
                json={
                    "job_id": job.id,
                    "status": status,
                    "output_url": job.output_url,
                    "actual_cost": job.actual_cost,
                    "error_message": job.error_message,
                },
            )
        logger.info(f"[{job.id}] Webhook sent to {job.webhook_url}")
    except Exception as e:
        logger.warning(f"[{job.id}] Webhook failed: {e}")
