import aiofiles
from pathlib import Path

from elevenlabs.client import AsyncElevenLabs

from app.config import settings
from app.services.job_logger import emit

OUTPUTS_DIR = Path("outputs")


async def generate_voiceover(text: str, job_id: str) -> str:
    """Génère un fichier audio voix off via ElevenLabs TTS.

    Retourne le chemin du fichier audio généré.
    """
    client = AsyncElevenLabs(api_key=settings.ELEVENLABS_API_KEY)

    emit(job_id, "elevenlabs", "info",
         f"Appel TTS — modèle: eleven_multilingual_v2, voice: {settings.ELEVENLABS_VOICE_ID}, "
         f"format: mp3_44100_128")

    audio = client.text_to_speech.convert(
        text=text,
        voice_id=settings.ELEVENLABS_VOICE_ID,
        model_id="eleven_multilingual_v2",
        output_format="mp3_44100_128",
    )

    job_dir = OUTPUTS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    output_path = job_dir / "voiceover.mp3"

    async with aiofiles.open(output_path, "wb") as f:
        async for chunk in audio:
            await f.write(chunk)

    emit(job_id, "elevenlabs", "success",
         f"Voix off sauvegardée → {output_path}")
    return str(output_path)


async def generate_music(prompt: str, job_id: str, duration_seconds: int = 30) -> str | None:
    """Génère un fichier audio musique de fond via ElevenLabs Music.

    Retourne le chemin du fichier audio généré, ou None si le plan ne supporte pas la musique.
    """
    client = AsyncElevenLabs(api_key=settings.ELEVENLABS_API_KEY)

    emit(job_id, "elevenlabs", "info",
         f"Appel Music — durée: {duration_seconds}s, instrumental: oui")

    try:
        audio = client.music.compose(
            prompt=prompt,
            music_length_ms=duration_seconds * 1000,
            force_instrumental=True,
        )

        job_dir = OUTPUTS_DIR / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        output_path = job_dir / "music.mp3"

        async with aiofiles.open(output_path, "wb") as f:
            async for chunk in audio:
                await f.write(chunk)

        emit(job_id, "elevenlabs", "success",
             f"Musique sauvegardée → {output_path}")
        return str(output_path)

    except Exception as e:
        error_str = str(e)
        if "402" in error_str or "payment" in error_str.lower():
            emit(job_id, "elevenlabs", "warning",
                 "Génération musicale indisponible (plan payant requis) — "
                 "la vidéo sera générée sans musique")
            return None
        raise
