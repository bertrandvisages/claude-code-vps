from google.cloud import vision_v1
from google.oauth2 import service_account

from app.config import settings
from app.services.job_logger import emit


def _get_client() -> vision_v1.ImageAnnotatorAsyncClient:
    """Crée un client Vision API avec les credentials configurées."""
    if settings.GOOGLE_APPLICATION_CREDENTIALS:
        creds = service_account.Credentials.from_service_account_file(
            settings.GOOGLE_APPLICATION_CREDENTIALS
        )
        return vision_v1.ImageAnnotatorAsyncClient(credentials=creds)
    return vision_v1.ImageAnnotatorAsyncClient()


async def analyze_photo(image_path: str, job_id: str = "") -> dict:
    """Analyse une photo via Google Vision API.

    Retourne un dict avec labels, objects et le prompt d'animation généré.
    """
    client = _get_client()

    with open(image_path, "rb") as f:
        content = f.read()

    image = vision_v1.Image(content=content)
    features = [
        vision_v1.Feature(type_=vision_v1.Feature.Type.LABEL_DETECTION, max_results=10),
        vision_v1.Feature(type_=vision_v1.Feature.Type.OBJECT_LOCALIZATION, max_results=10),
    ]
    annotate_request = vision_v1.AnnotateImageRequest(image=image, features=features)
    batch_response = await client.batch_annotate_images(
        requests=[annotate_request]
    )
    response = batch_response.responses[0]

    labels = [
        {"description": label.description, "score": round(label.score, 3)}
        for label in response.label_annotations
    ]
    objects = [
        {"name": obj.name, "score": round(obj.score, 3)}
        for obj in response.localized_object_annotations
    ]

    if job_id:
        label_names = ", ".join(l["description"] for l in labels[:5])
        object_names = ", ".join(o["name"] for o in objects[:5])
        emit(job_id, "vision", "info",
             f"Labels détectés : {label_names or 'aucun'}")
        if object_names:
            emit(job_id, "vision", "info",
                 f"Objets détectés : {object_names}")

    prompt = generate_animation_prompt(labels, objects)

    return {
        "labels": labels,
        "objects": objects,
        "animation_prompt": prompt,
    }


def generate_description(labels: list[dict], objects: list[dict]) -> str:
    """Génère une description lisible à partir des résultats Vision API."""
    label_names = [l["description"] for l in labels[:5]]
    object_names = [o["name"] for o in objects[:3]]
    parts = []
    if label_names:
        parts.append(", ".join(label_names))
    if object_names:
        parts.append("Objets: " + ", ".join(object_names))
    return ". ".join(parts) if parts else ""


def generate_animation_prompt(labels: list[dict], objects: list[dict]) -> str:
    """Génère un prompt d'animation pour Kie.ai à partir des labels et objets détectés."""
    high_conf_labels = [l["description"].lower() for l in labels if l["score"] > 0.7]
    high_conf_objects = [o["name"].lower() for o in objects if o["score"] > 0.5]

    parts = []

    # Mouvement des personnes
    person_keywords = {"person", "people", "man", "woman", "child", "boy", "girl"}
    if person_keywords & set(high_conf_objects):
        parts.append("gentle natural movement, subtle breathing, slight smile")

    # Éléments naturels
    nature_keywords = {"water", "sea", "ocean", "river", "lake", "waterfall"}
    if nature_keywords & (set(high_conf_labels) | set(high_conf_objects)):
        parts.append("flowing water with gentle waves and ripples")

    sky_keywords = {"sky", "cloud", "clouds", "sunset", "sunrise"}
    if sky_keywords & set(high_conf_labels):
        parts.append("clouds drifting slowly across the sky")

    tree_keywords = {"tree", "plant", "flower", "grass", "vegetation", "forest"}
    if tree_keywords & (set(high_conf_labels) | set(high_conf_objects)):
        parts.append("leaves and branches swaying gently in the breeze")

    animal_keywords = {"dog", "cat", "bird", "animal", "pet", "horse"}
    if animal_keywords & (set(high_conf_labels) | set(high_conf_objects)):
        parts.append("natural animal movement, breathing and looking around")

    # Prompt par défaut si rien de spécifique détecté
    if not parts:
        parts.append("subtle ambient motion, gentle camera movement")

    return ", ".join(parts)
