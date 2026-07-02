from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    APP_ENV: str = "production"
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    API_KEY: str = ""
    DATABASE_URL: str = "sqlite+aiosqlite:///./data/app.db"

    SUPABASE_URL: str = ""
    SUPABASE_SERVICE_KEY: str = ""
    SUPABASE_BUCKET: str = "hotel-videos"

    # B2 (S3-compatible) — upload direct des gros fichiers (append packshot) sur
    # vod-s3, en streaming depuis le disque (memory-safe), sans double-hop.
    B2_ENDPOINT: str = ""      # ex: s3.eu-central-003.backblazeb2.com
    B2_REGION: str = ""        # ex: eu-central-003
    B2_KEY_ID: str = ""
    B2_APPLICATION_KEY: str = ""
    B2_BUCKET: str = ""        # ex: vod-s3

    class Config:
        env_file = ".env"


settings = Settings()
