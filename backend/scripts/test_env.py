#!/usr/bin/env python3
"""Vérifie les variables d'environnement et teste la connexion aux services externes."""

import asyncio
import os
import sys
from pathlib import Path

# Ajouter le dossier backend au path pour importer app.config
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# Couleurs terminal
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BOLD = "\033[1m"
RESET = "\033[0m"


def ok(msg: str):
    print(f"  {GREEN}✓{RESET} {msg}")


def fail(msg: str):
    print(f"  {RED}✗{RESET} {msg}")


def warn(msg: str):
    print(f"  {YELLOW}⚠{RESET} {msg}")


def header(title: str):
    print(f"\n{BOLD}{'─' * 50}")
    print(f"  {title}")
    print(f"{'─' * 50}{RESET}")


# ─── 1. Variables d'environnement ───────────────────────────────────────────

def check_env_vars() -> dict[str, bool]:
    """Vérifie la présence des variables d'environnement critiques."""
    header("1. Variables d'environnement")

    results = {}

    required = {
        "KIE_API_KEY": "Kie.ai — API Key",
        "ELEVENLABS_API_KEY": "ElevenLabs — API Key",
        "ELEVENLABS_VOICE_ID": "ElevenLabs — Voice ID",
        "GOOGLE_APPLICATION_CREDENTIALS": "Google Vision — Credentials path",
    }

    optional = {
        "API_KEY": "Auth API Key (vide = auth désactivée)",
    }

    for var, desc in required.items():
        val = os.getenv(var, "")
        is_placeholder = val in ("", "your_key_here", "your_kie_api_key_here",
                                  "your_voice_id",
                                  "path/to/service-account.json")
        if is_placeholder:
            fail(f"{desc}: non configurée ({var})")
            results[var] = False
        else:
            display = val[:8] + "..." if len(val) > 12 else val
            ok(f"{desc}: {display}")
            results[var] = True

    for var, desc in optional.items():
        val = os.getenv(var, "")
        if not val or val.startswith("your_"):
            warn(f"{desc}: non définie (optionnel)")
        else:
            ok(f"{desc}: {val}")

    # Vérifier le fichier credentials Google
    creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
    if creds_path and not creds_path.startswith("your_"):
        full_path = Path(creds_path)
        if not full_path.is_absolute():
            full_path = Path(__file__).resolve().parent.parent / creds_path
        if full_path.exists():
            ok(f"Fichier credentials Google existe: {full_path.name}")
        else:
            fail(f"Fichier credentials Google introuvable: {full_path}")
            results["GOOGLE_APPLICATION_CREDENTIALS"] = False

    return results


# ─── 2. Google Vision ───────────────────────────────────────────────────────

async def test_google_vision() -> bool:
    header("2. Google Cloud Vision API")

    creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
    if not creds_path or creds_path.startswith("your_"):
        fail("GOOGLE_APPLICATION_CREDENTIALS non configurée — test ignoré")
        return False

    try:
        from google.cloud import vision_v1
        from google.oauth2 import service_account

        full_path = Path(creds_path)
        if not full_path.is_absolute():
            full_path = Path(__file__).resolve().parent.parent / creds_path

        creds = service_account.Credentials.from_service_account_file(str(full_path))
        ok(f"Credentials chargées (projet: {creds.project_id})")

        client = vision_v1.ImageAnnotatorAsyncClient(credentials=creds)

        # Test minimal : envoyer une image 1x1 pixel PNG transparent
        import struct
        import zlib

        def _minimal_png() -> bytes:
            sig = b"\x89PNG\r\n\x1a\n"
            ihdr_data = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
            ihdr = _chunk(b"IHDR", ihdr_data)
            raw = zlib.compress(b"\x00\xff\xff\xff")
            idat = _chunk(b"IDAT", raw)
            iend = _chunk(b"IEND", b"")
            return sig + ihdr + idat + iend

        def _chunk(chunk_type: bytes, data: bytes) -> bytes:
            c = chunk_type + data
            crc = zlib.crc32(c) & 0xFFFFFFFF
            return struct.pack(">I", len(data)) + c + struct.pack(">I", crc)

        image = vision_v1.Image(content=_minimal_png())
        feature = vision_v1.Feature(type_=vision_v1.Feature.Type.LABEL_DETECTION, max_results=1)
        request = vision_v1.AnnotateImageRequest(image=image, features=[feature])
        response = await client.batch_annotate_images(requests=[request])

        if response.responses:
            ok("Connexion réussie — API Vision répond correctement")
            return True
        else:
            fail("Réponse vide de l'API Vision")
            return False

    except Exception as e:
        fail(f"Erreur: {e}")
        return False


# ─── 3. ElevenLabs ──────────────────────────────────────────────────────────

async def test_elevenlabs() -> bool:
    header("3. ElevenLabs API")

    api_key = os.getenv("ELEVENLABS_API_KEY", "")
    voice_id = os.getenv("ELEVENLABS_VOICE_ID", "")

    if not api_key or api_key.startswith("your_"):
        fail("ELEVENLABS_API_KEY non configurée — test ignoré")
        return False

    try:
        from elevenlabs.client import AsyncElevenLabs

        client = AsyncElevenLabs(api_key=api_key)

        # Test : récupérer les infos utilisateur (endpoint léger, pas de coût)
        user = await client.user.get()
        ok(f"Connexion réussie — utilisateur: {user.first_name or 'N/A'}")

        # Vérifier le quota
        sub = user.subscription
        if sub:
            chars_used = sub.character_count
            chars_limit = sub.character_limit
            ok(f"Quota caractères: {chars_used:,} / {chars_limit:,}")

        # Vérifier que le voice_id est valide
        if voice_id and not voice_id.startswith("your_"):
            try:
                voice = await client.voices.get(voice_id)
                ok(f"Voice ID valide: {voice.name}")
            except Exception:
                fail(f"Voice ID invalide: {voice_id}")
        else:
            warn("ELEVENLABS_VOICE_ID non configurée")

        return True

    except Exception as e:
        fail(f"Erreur: {e}")
        return False


# ─── 4. Kie.ai ─────────────────────────────────────────────────────────────

async def test_kie() -> bool:
    header("4. Kie.ai API")

    api_key = os.getenv("KIE_API_KEY", "")

    if not api_key or api_key.startswith("your_"):
        fail("KIE_API_KEY non configurée — test ignoré")
        return False

    try:
        import httpx

        # Test : vérifier que l'API répond avec un Bearer token
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                "https://api.kie.ai/api/v1/user/info",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
            )

            if resp.status_code == 200:
                data = resp.json()
                if data.get("code") == 200:
                    ok("Connexion réussie — API Kie.ai répond correctement")
                    user_data = data.get("data", {})
                    if "balance" in user_data:
                        ok(f"Balance: {user_data['balance']}")
                    return True
                else:
                    msg = data.get("msg", "erreur inconnue")
                    fail(f"API Kie.ai a répondu avec code {data.get('code')}: {msg}")
                    return False
            else:
                fail(f"HTTP {resp.status_code}: {resp.text[:200]}")
                return False

    except Exception as e:
        fail(f"Erreur: {e}")
        return False


# ─── 5. FFmpeg ───────────────────────────────────────────────────────────────

def check_ffmpeg() -> bool:
    header("5. FFmpeg")

    import shutil
    import subprocess

    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        fail("FFmpeg non trouvé dans le PATH")
        return False

    ok(f"FFmpeg trouvé: {ffmpeg_path}")

    try:
        result = subprocess.run(
            ["ffmpeg", "-version"], capture_output=True, text=True, timeout=5
        )
        version_line = result.stdout.split("\n")[0]
        ok(f"Version: {version_line}")
        return True
    except Exception as e:
        fail(f"Erreur exécution FFmpeg: {e}")
        return False


# ─── Main ────────────────────────────────────────────────────────────────────

async def main():
    print(f"\n{BOLD}🔍 Test de l'environnement — Video Montage App{RESET}")

    env_results = check_env_vars()
    ffmpeg_ok = check_ffmpeg()

    vision_ok = await test_google_vision()
    elevenlabs_ok = await test_elevenlabs()
    kie_ok = await test_kie()

    # Résumé
    header("Résumé")
    services = [
        ("Variables d'env", all(env_results.values())),
        ("FFmpeg", ffmpeg_ok),
        ("Google Vision", vision_ok),
        ("ElevenLabs", elevenlabs_ok),
        ("Kie.ai", kie_ok),
    ]

    all_ok = True
    for name, status in services:
        if status:
            ok(name)
        else:
            fail(name)
            all_ok = False

    if all_ok:
        print(f"\n{GREEN}{BOLD}Tout est opérationnel !{RESET}\n")
    else:
        print(f"\n{YELLOW}{BOLD}Certains services nécessitent une attention.{RESET}\n")


if __name__ == "__main__":
    asyncio.run(main())
