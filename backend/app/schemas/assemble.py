from pydantic import BaseModel, Field, model_validator


class ColorCorrection(BaseModel):
    # Filtre ffmpeg eq= applique au cut rush (propage depuis app-vod via
    # rushes.analysis.color_correction renvoye par Gemini). None par defaut.
    brightness: float | None = None
    contrast: float | None = None
    saturation: float | None = None
    gamma: float | None = None


class Clip(BaseModel):
    index: int
    video_url: str
    duree_secondes: float
    # Pour les rushes : offset ffmpeg `-ss`. None = pas de cut, le clip est utilise tel quel.
    start_seconds: float | None = None
    # Pour les rushes : etalonnage colorimetrique optionnel applique au cut.
    color_correction: ColorCorrection | None = None


class VoiceoverSegment(BaseModel):
    in_seconds: float = Field(ge=0)
    out_seconds: float = Field(gt=0)
    start_seconds: float = Field(ge=0)


class AudioConfig(BaseModel):
    voiceover_volume: float = 1.0
    music_volume: float = 1.0
    music_fade_in_seconds: float = 3
    music_fade_out_seconds: float = 5
    sidechain_threshold: float = 0.02
    sidechain_ratio: float = 2
    sidechain_attack: float = 100
    sidechain_release: float = 80
    music_loudnorm_target: float = -14
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
    hotel_id: str | None = None
    idea_id: str | None = None
    voiceover_url: str | None = None
    voiceover_segments: list[VoiceoverSegment] | None = None
    music_url: str | None = None
    clips: list[Clip]
    # Packshot mp4 a concatener en silence apres le mix audio (musique fade out
    # se termine sur les derniers clips, packshot 100% muet).
    packshot_url: str | None = None
    audio_config: AudioConfig = AudioConfig()
    video_config: VideoConfig = VideoConfig()
    webhook_url: str | None = None

    @property
    def entity_type(self) -> str:
        return "idea" if self.idea_id else "hotel"

    @property
    def entity_id(self) -> str:
        # validator garantit qu'au moins un des deux est present
        return self.idea_id or self.hotel_id  # type: ignore[return-value]

    @model_validator(mode="after")
    def resolve_voiceover(self) -> "AssembleRequest":
        if not self.hotel_id and not self.idea_id:
            raise ValueError("hotel_id ou idea_id requis")
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
