import asyncio
import base64
import json
import time
from pathlib import Path

import httpx

from app.config import settings
from app.services.job_logger import emit

KIE_BASE_URL = "https://api.kie.ai"
KIE_UPLOAD_URL = "https://kieai.redpandaai.co/api/file-base64-upload"
OUTPUTS_DIR = Path("outputs")
POLL_INTERVAL = 5  # secondes
POLL_TIMEOUT = 300  # 5 minutes max par clip
MAX_RETRIES = 3  # retries HTTP (429 / 422 / 5xx)
ANIMATE_RETRIES = 3  # retries globaux par photo (500, 422, PA, etc.)
ANIMATE_WAIT = 15  # secondes entre retries globaux


def _auth_headers(*, with_content_type: bool = True) -> dict:
    headers = {"Authorization": f"Bearer {settings.KIE_API_KEY}"}
    if with_content_type:
        headers["Content-Type"] = "application/json"
    return headers


async def _upload_image(image_path: str, job_id: str) -> str:
    """Upload une image en base64 vers Kie.ai et retourne l'URL publique."""
    image_bytes = Path(image_path).read_bytes()
    size_mb = len(image_bytes) / (1024 * 1024)
    emit(job_id, "kie", "info", f"Taille image : {size_mb:.1f} Mo")

    image_b64 = base64.b64encode(image_bytes).decode()
    ext = Path(image_path).suffix.lower()
    mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}.get(ext.lstrip("."), "image/jpeg")

    payload = {
        "base64Data": f"data:{mime};base64,{image_b64}",
        "uploadPath": f"montage/{job_id}",
        "fileName": Path(image_path).name,
    }

    async with httpx.AsyncClient(timeout=120) as client:
        for attempt in range(MAX_RETRIES):
            resp = await client.post(
                KIE_UPLOAD_URL,
                headers=_auth_headers(),
                json=payload,
            )
            if resp.status_code >= 500:
                wait = 5 * (attempt + 1)
                emit(job_id, "kie", "warning",
                     f"Upload erreur {resp.status_code} — retry {attempt + 1}/{MAX_RETRIES} "
                     f"dans {wait}s (réponse : {resp.text})")
                await asyncio.sleep(wait)
                continue
            if resp.status_code >= 400:
                emit(job_id, "kie", "error",
                     f"Upload erreur {resp.status_code} : {resp.text}")
                resp.raise_for_status()
            break
        else:
            emit(job_id, "kie", "error",
                 f"Upload échoué après {MAX_RETRIES} tentatives : {resp.text}")
            resp.raise_for_status()

        data = resp.json()
        return data["data"]["downloadUrl"]


async def animate_photo(
    image_path: str,
    job_id: str,
    photo_id: str,
    prompt: str = "",
    duration: str = "5",
) -> str | None:
    """Anime une photo via Kie.ai (Kling 2.6 image-to-video).

    Retourne le chemin du fichier MP4 généré, ou None si l'animation a échoué
    après tous les retries (ex: code PA).
    """
    # Upload l'image pour obtenir une URL
    emit(job_id, "kie", "info", f"Upload de l'image vers Kie.ai...")
    image_url = await _upload_image(image_path, job_id)
    emit(job_id, "kie", "info", f"Image uploadée → {image_url[:80]}...")

    emit(job_id, "kie", "info", f"Prompt envoyé : \"{prompt}\"")

    last_error = ""
    for attempt in range(ANIMATE_RETRIES):
        try:
            task_id = await _submit_task(image_url, prompt, duration, job_id)
            video_url = await _poll_task(task_id, job_id)

            # Télécharger le MP4
            emit(job_id, "kie", "info", "Téléchargement du clip vidéo...")
            output_path = await _download_video(video_url, job_id, photo_id)
            return str(output_path)

        except (RuntimeError, TimeoutError, httpx.HTTPStatusError) as e:
            last_error = str(e)
            if attempt < ANIMATE_RETRIES - 1:
                emit(job_id, "kie", "warning",
                     f"Photo {photo_id} — erreur : {last_error} — "
                     f"retry {attempt + 1}/{ANIMATE_RETRIES} dans {ANIMATE_WAIT}s...")
                await asyncio.sleep(ANIMATE_WAIT)
            else:
                emit(job_id, "kie", "warning",
                     f"Photo {photo_id} — échec après {ANIMATE_RETRIES} tentatives "
                     f"({last_error}) — clip ignoré, le pipeline continue")
                return None

    return None


async def _submit_task(
    image_url: str, prompt: str, duration: str, job_id: str
) -> str:
    """Soumet une tâche d'animation à Kie.ai et retourne le taskId."""
    emit(job_id, "kie", "info",
         f"Envoi à Kie.ai (modèle: kling-2.6/image-to-video, durée: {duration}s)")

    payload = {
        "model": "kling-2.6/image-to-video",
        "input": {
            "prompt": prompt,
            "image_urls": [image_url],
            "duration": duration,
            "sound": False,
        },
    }

    # Log le payload pour vérifier que input est bien un dict (pas une string)
    emit(job_id, "kie", "info",
         f"Payload createTask : {json.dumps(payload, ensure_ascii=False)}")

    async with httpx.AsyncClient(timeout=30) as client:
        for attempt in range(MAX_RETRIES):
            # json= sérialise le dict en JSON (input reste un objet, pas une string)
            resp = await client.post(
                f"{KIE_BASE_URL}/api/v1/jobs/createTask",
                headers=_auth_headers(with_content_type=False),
                json=payload,
            )
            if resp.status_code in (422, 429) or resp.status_code >= 500:
                wait = 10 * (attempt + 1)
                emit(job_id, "kie", "warning",
                     f"createTask erreur {resp.status_code} — "
                     f"retry {attempt + 1}/{MAX_RETRIES} dans {wait}s "
                     f"(réponse : {resp.text})")
                await asyncio.sleep(wait)
                continue
            resp.raise_for_status()
            break
        else:
            emit(job_id, "kie", "error",
                 f"createTask échoué après {MAX_RETRIES} tentatives : {resp.text}")
            resp.raise_for_status()

        resp_data = resp.json()
        emit(job_id, "kie", "info",
             f"Réponse createTask : code={resp_data.get('code')}, "
             f"msg={resp_data.get('msg', 'N/A')}")

        if resp_data.get("code") != 200:
            raise RuntimeError(f"Kie.ai error: {resp_data.get('msg', 'Unknown error')}")

        task_id = resp_data["data"]["taskId"]
        emit(job_id, "kie", "info", f"Tâche soumise — taskId: {task_id}")
        return task_id


async def _poll_task(task_id: str, job_id: str = "") -> str:
    """Poll le statut de la tâche Kie.ai jusqu'à success/fail.

    Retourne l'URL du MP4 généré.
    """
    start = time.time()
    poll_count = 0
    async with httpx.AsyncClient(timeout=30) as client:
        while True:
            elapsed = time.time() - start
            if elapsed > POLL_TIMEOUT:
                raise TimeoutError(
                    f"Kie.ai task {task_id} timed out after {POLL_TIMEOUT}s"
                )

            resp = await client.get(
                f"{KIE_BASE_URL}/api/v1/jobs/recordInfo",
                headers=_auth_headers(),
                params={"taskId": task_id},
            )
            resp.raise_for_status()
            data = resp.json().get("data", {})
            state = data.get("state", "")
            poll_count += 1

            if state == "success":
                result_json = json.loads(data.get("resultJson", "{}"))
                urls = result_json.get("resultUrls", [])
                if not urls:
                    raise RuntimeError("Kie.ai task succeeded but no video URL returned")
                emit(job_id, "kie", "success",
                     f"Clip prêt après {elapsed:.0f}s ({poll_count} requêtes de polling)")
                return urls[0]
            elif state == "fail":
                msg = data.get("failMsg", "Unknown error")
                emit(job_id, "kie", "error",
                     f"Échec Kie.ai : {msg} — réponse complète : {json.dumps(data, default=str)}")
                raise RuntimeError(f"Kie.ai task failed: {msg}")

            if poll_count % 3 == 0:
                emit(job_id, "kie", "warning",
                     f"En attente... ({elapsed:.0f}s écoulées, statut: {state})")

            await asyncio.sleep(POLL_INTERVAL)


async def _download_video(url: str, job_id: str, photo_id: str) -> Path:
    """Télécharge le MP4 depuis l'URL Kie.ai."""
    job_dir = OUTPUTS_DIR / job_id / "clips"
    job_dir.mkdir(parents=True, exist_ok=True)
    output_path = job_dir / f"{photo_id}.mp4"

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        output_path.write_bytes(resp.content)

    return output_path
