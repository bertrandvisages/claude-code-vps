import asyncio
import time
from pathlib import Path

import httpx

from app.config import settings
from app.services.job_logger import emit

KIE_BASE_URL = "https://api.kie.ai"
GENERATE_URL = f"{KIE_BASE_URL}/api/v1/generate"
RECORD_INFO_URL = f"{KIE_BASE_URL}/api/v1/generate/record-info"
OUTPUTS_DIR = Path("outputs")
POLL_INTERVAL = 10  # secondes
POLL_TIMEOUT = 300  # 5 minutes max
MAX_RETRIES = 3
RETRY_WAIT = 15  # secondes entre retries


def _auth_headers() -> dict:
    return {"Authorization": f"Bearer {settings.KIE_API_KEY}"}


async def generate_music(prompt: str, job_id: str) -> str | None:
    """Génère de la musique via l'API Suno de Kie.ai.

    Retourne le chemin du fichier MP3 généré, ou None si la génération a échoué.
    """
    emit(job_id, "music", "info", f"Génération musicale Suno — prompt : \"{prompt}\"")

    last_error = ""
    for attempt in range(MAX_RETRIES):
        try:
            task_id = await _submit_generation(prompt, job_id)
            audio_url = await _poll_generation(task_id, job_id)
            output_path = await _download_audio(audio_url, job_id)
            emit(job_id, "music", "success",
                 f"Musique générée → {output_path}")
            return str(output_path)

        except (RuntimeError, TimeoutError, httpx.HTTPStatusError) as e:
            last_error = str(e)
            if attempt < MAX_RETRIES - 1:
                emit(job_id, "music", "warning",
                     f"Erreur génération musique : {last_error} — "
                     f"retry {attempt + 1}/{MAX_RETRIES} dans {RETRY_WAIT}s...")
                await asyncio.sleep(RETRY_WAIT)
            else:
                emit(job_id, "music", "warning",
                     f"Génération musique échouée après {MAX_RETRIES} tentatives "
                     f"({last_error}) — le pipeline continue sans musique")
                return None

    return None


async def _submit_generation(prompt: str, job_id: str) -> str:
    """Soumet une tâche de génération musicale et retourne le taskId."""
    payload = {
        "prompt": prompt,
        "customMode": False,
        "instrumental": True,
        "model": "V4_5",
        "callBackUrl": "https://localhost/callback",
    }

    emit(job_id, "music", "info",
         f"Envoi à Kie.ai Suno (modèle: V4_5, instrumental: true)")

    async with httpx.AsyncClient(timeout=30) as client:
        for attempt in range(MAX_RETRIES):
            resp = await client.post(
                GENERATE_URL,
                headers=_auth_headers(),
                json=payload,
            )
            if resp.status_code in (422, 429) or resp.status_code >= 500:
                wait = 10 * (attempt + 1)
                emit(job_id, "music", "warning",
                     f"generate erreur {resp.status_code} — "
                     f"retry {attempt + 1}/{MAX_RETRIES} dans {wait}s "
                     f"(réponse : {resp.text})")
                await asyncio.sleep(wait)
                continue
            resp.raise_for_status()
            break
        else:
            emit(job_id, "music", "error",
                 f"generate échoué après {MAX_RETRIES} tentatives : {resp.text}")
            resp.raise_for_status()

        resp_data = resp.json()
        emit(job_id, "music", "info",
             f"Réponse generate : code={resp_data.get('code')}, "
             f"msg={resp_data.get('msg', 'N/A')}")

        if resp_data.get("code") != 200:
            raise RuntimeError(
                f"Kie.ai Suno error: {resp_data.get('msg', 'Unknown error')}"
            )

        task_id = resp_data["data"]["taskId"]
        emit(job_id, "music", "info", f"Tâche musicale soumise — taskId: {task_id}")
        return task_id


async def _poll_generation(task_id: str, job_id: str) -> str:
    """Poll le statut de la génération musicale jusqu'à SUCCESS/FAIL.

    Retourne l'URL du fichier audio.
    """
    start = time.time()
    poll_count = 0

    # Statuts d'échec connus
    fail_statuses = {
        "CREATE_TASK_FAILED",
        "GENERATE_AUDIO_FAILED",
        "CALLBACK_EXCEPTION",
        "SENSITIVE_WORD_ERROR",
    }

    async with httpx.AsyncClient(timeout=30) as client:
        while True:
            elapsed = time.time() - start
            if elapsed > POLL_TIMEOUT:
                raise TimeoutError(
                    f"Kie.ai Suno task {task_id} timed out after {POLL_TIMEOUT}s"
                )

            resp = await client.get(
                RECORD_INFO_URL,
                headers=_auth_headers(),
                params={"taskId": task_id},
            )
            resp.raise_for_status()
            resp_data = resp.json()
            data = resp_data.get("data", {})
            status = data.get("status", "")
            poll_count += 1

            if status == "SUCCESS":
                response = data.get("response", {})
                suno_data = response.get("sunoData", [])
                if not suno_data:
                    raise RuntimeError(
                        "Kie.ai Suno task succeeded but no audio data returned"
                    )
                audio_url = suno_data[0].get("audioUrl", "")
                if not audio_url:
                    raise RuntimeError(
                        "Kie.ai Suno task succeeded but no audioUrl in response"
                    )
                duration = suno_data[0].get("duration", 0)
                emit(job_id, "music", "success",
                     f"Musique prête après {elapsed:.0f}s "
                     f"({poll_count} requêtes de polling, "
                     f"durée: {duration:.0f}s)")
                return audio_url

            if status in fail_statuses:
                error_msg = data.get("errorMessage") or status
                emit(job_id, "music", "error",
                     f"Échec Suno : {error_msg}")
                raise RuntimeError(f"Kie.ai Suno task failed: {error_msg}")

            if poll_count % 3 == 0:
                emit(job_id, "music", "info",
                     f"En attente musique... ({elapsed:.0f}s écoulées, statut: {status})")

            await asyncio.sleep(POLL_INTERVAL)


async def _download_audio(url: str, job_id: str) -> Path:
    """Télécharge le fichier audio MP3 depuis l'URL Suno."""
    job_dir = OUTPUTS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    output_path = job_dir / "music.mp3"

    emit(job_id, "music", "info", "Téléchargement du fichier audio...")

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        output_path.write_bytes(resp.content)

    size_kb = output_path.stat().st_size / 1024
    emit(job_id, "music", "info", f"Audio téléchargé : {size_kb:.0f} Ko")
    return output_path
