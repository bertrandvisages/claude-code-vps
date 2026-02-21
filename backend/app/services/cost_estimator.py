from app.config import settings


def estimate_job_cost(
    photo_count: int,
    voiceover_chars: int = 0,
    include_music: bool = True,
) -> dict:
    """Estime le coût total d'un job avant lancement."""
    kie_cost = photo_count * settings.KIE_COST_PER_CLIP
    vision_cost = photo_count * settings.GOOGLE_VISION_COST_PER_IMAGE
    voiceover_cost = (voiceover_chars / 1000) * settings.ELEVENLABS_COST_PER_1K_CHARS
    music_cost = settings.KIE_SUNO_COST_PER_GENERATION if include_music else 0.0
    total = kie_cost + vision_cost + voiceover_cost + music_cost

    return {
        "breakdown": {
            "kie_animation": round(kie_cost, 4),
            "google_vision": round(vision_cost, 4),
            "elevenlabs_voiceover": round(voiceover_cost, 4),
            "kie_suno_music": round(music_cost, 4),
        },
        "total": round(total, 4),
        "currency": "USD",
    }
