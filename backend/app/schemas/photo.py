from datetime import datetime
from pydantic import BaseModel


class PhotoResponse(BaseModel):
    id: str
    job_id: str
    filename: str
    original_filename: str
    position: int
    created_at: datetime
    vision_labels: list | None = None
    vision_description: str | None = None
    vision_objects: list | None = None

    model_config = {"from_attributes": True}


class PhotoAnalysisResponse(BaseModel):
    photo_id: str
    filename: str
    vision_labels: list | None = None
    vision_description: str | None = None
    vision_objects: list | None = None

    model_config = {"from_attributes": True}
