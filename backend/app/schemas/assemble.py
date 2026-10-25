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
    # Musique normalisee a music_loudnorm_target puis x music_volume : 0.56
    # (-5 dB) place la musique seule ~1,5 dB sous les passages de voix (voix
    # normalisee a -16 LUFS). 2.0 (ancien reglage app-vod) la mettait a -8 LUFS,
    # plus fort que la voix.
    music_volume: float = 0.56
    music_fade_in_seconds: float = 3
    music_fade_out_seconds: float = 5
    # Ducking : voix (x3) en sidechain ; ratio 6 => ~16 dB de reduction sous
    # la voix, attaque rapide, relachement 400 ms.
    sidechain_threshold: float = 0.05
    sidechain_ratio: float = 6
    sidechain_attack: float = 50
    sidechain_release: float = 400
    music_loudnorm_target: float = -14
    # Niveau FINAL du mix (apres voix + musique) : gain lineaire mesure
    # (ebur128) vers la cible, puis limiteur a final_true_peak. Conserve la
    # dynamique voix/musique (pas de loudnorm dynamique). None = desactive.
    final_loudnorm_target: float | None = -14
    final_true_peak: float = -1
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
    # yuv420p : seul pixel format universellement lisible (navigateurs,
    # QuickTime, Okast). Sans ca, libx264 garde le format de la source
    # (yuv444p/yuvj420p possible sur packshot ou certains clips) -> "fichier
    # corrompu" a la lecture + raccord concat -c copy casse au packshot.
    pix_fmt: str = "yuv420p"
    movflags: str = "+faststart"
    # Fondu au noir en fin de film (sur le packshot s'il y en a un, sinon sur
    # le dernier plan). 0 = desactive.
    fade_out_seconds: float = 1.5


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
