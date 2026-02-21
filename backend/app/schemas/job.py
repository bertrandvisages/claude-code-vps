from datetime import datetime
from pydantic import BaseModel, field_validator


class JobCreate(BaseModel):
    title: str | None = None
    description: str | None = None
    webhook_url: str | None = None
    voiceover_text: str | None = None
    music_prompt: str | None = None
    include_music: bool = True
    transition_type: str = "crossfade"  # "crossfade" ou "cut"


class JobResponse(BaseModel):
    id: str
    status: str
    progress: int
    title: str | None
    description: str | None
    estimated_cost: float | None
    actual_cost: float | None
    output_url: str | None
    error_message: str | None
    webhook_url: str | None
    voiceover_text: str | None
    music_prompt: str | None
    include_music: bool
    custom_music_path: str | None
    transition_type: str
    montage_plan: list | None = None
    created_at: datetime
    updated_at: datetime
    photo_count: int

    model_config = {"from_attributes": True}


class JobApproval(BaseModel):
    approved: bool


class MontageSegment(BaseModel):
    photo_id: str
    segment_text: str
    duration_seconds: float = 5.0
    music_volume: float = 0.8

    @field_validator("duration_seconds")
    @classmethod
    def validate_duration(cls, v: float) -> float:
        if v < 2.0 or v > 10.0:
            raise ValueError("duration_seconds must be between 2.0 and 10.0")
        return v

    @field_validator("music_volume")
    @classmethod
    def validate_volume(cls, v: float) -> float:
        if v < 0.0 or v > 1.0:
            raise ValueError("music_volume must be between 0.0 and 1.0")
        return v


class CostBreakdown(BaseModel):
    kie_animation: float
    google_vision: float
    elevenlabs_voiceover: float
    kie_suno_music: float


class CostEstimate(BaseModel):
    job_id: str
    photo_count: int
    voiceover_chars: int
    include_music: bool
    breakdown: CostBreakdown
    total: float
    currency: str = "USD"
