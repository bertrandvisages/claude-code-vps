from pydantic import BaseModel


class Segment(BaseModel):
    order: int
    video_url: str
    duration_seconds: float


class Audio(BaseModel):
    voiceover_url: str | None = None
    music_url: str | None = None
    music_volume_base: float = 0.3


class OutputStorage(BaseModel):
    supabase_bucket: str
    supabase_path: str


class AssembleRequest(BaseModel):
    job_id: str
    output_filename: str
    resolution: str = "1920x1080"
    fps: int = 30
    segments: list[Segment]
    audio: Audio | None = None
    output_storage: OutputStorage


class AssembleResponse(BaseModel):
    job_id: str
    status: str


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    output_url: str | None = None
    error_message: str | None = None
