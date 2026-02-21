from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    APP_ENV: str = "development"
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    FRONTEND_URL: str = "http://localhost:5173"
    API_KEY: str = ""
    DATABASE_URL: str = "sqlite+aiosqlite:///./data/app.db"
    KIE_API_KEY: str = ""
    ELEVENLABS_API_KEY: str = ""
    ELEVENLABS_VOICE_ID: str = ""
    GOOGLE_APPLICATION_CREDENTIALS: str = ""

    # Tarification (placeholders à ajuster)
    KIE_COST_PER_CLIP: float = 0.125
    ELEVENLABS_COST_PER_1K_CHARS: float = 0.30
    ELEVENLABS_COST_PER_MUSIC: float = 0.50
    GOOGLE_VISION_COST_PER_IMAGE: float = 0.0015
    KIE_SUNO_COST_PER_GENERATION: float = 0.06

    # Vidéo output
    VIDEO_WIDTH: int = 1920
    VIDEO_HEIGHT: int = 1080
    VIDEO_FPS: int = 30
    VIDEO_CODEC: str = "libx264"

    class Config:
        env_file = ".env"


settings = Settings()
