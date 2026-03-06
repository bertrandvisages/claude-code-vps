from pydantic import BaseModel, Field, model_validator


class Clip(BaseModel):
    index: int
    video_url: str
    duree_secondes: float


class VoiceoverSegment(BaseModel):
    in_seconds: float = Field(ge=0)
    out_seconds: float = Field(gt=0)
    start_seconds: float = Field(ge=0)


class AudioConfig(BaseModel):
    voiceover_volume: float = 1.0
    music_volume: float = 0.15
    music_fade_in_seconds: float = 3
    music_fade_out_seconds: float = 5
    sidechain_threshold: float = 0.02
    sidechain_ratio: float = 6
    sidechain_attack: float = 200
    sidechain_release: float = 1000
    resample_rate: int = 44100
    output_codec: str = "aac"
    output_bitrate: str = "192k"


class VideoConfig(BaseModel):
    width: int = 1920
    height: int = 1080
    fps: int = 30
    codec: str = "libx264"
    preset: str = "fast"
    crf: int = 23
    movflags: str = "+faststart"


class AssembleRequest(BaseModel):
    hotel_id: str
    voiceover_url: str | None = None
    voiceover_segments: list[VoiceoverSegment] | None = None
    music_url: str | None = None
    clips: list[Clip]
    audio_config: AudioConfig = AudioConfig()
    video_config: VideoConfig = VideoConfig()
    webhook_url: str | None = None

    @model_validator(mode="after")
    def resolve_voiceover(self) -> "AssembleRequest":
        if self.voiceover_segments is not None and len(self.voiceover_segments) == 0:
            self.voiceover_segments = None
        if self.voiceover_segments and not self.voiceover_url:
            raise ValueError("voiceover_url est requis quand voiceover_segments est fourni")
        return self


class AssembleResponse(BaseModel):
    job_id: str
    status: str


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    output_url: str | None = None
    error_message: str | None = None
