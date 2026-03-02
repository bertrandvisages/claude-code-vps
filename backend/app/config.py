from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    APP_ENV: str = "production"
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    API_KEY: str = ""
    DATABASE_URL: str = "sqlite+aiosqlite:///./data/app.db"

    SUPABASE_URL: str = ""
    SUPABASE_SERVICE_KEY: str = ""

    class Config:
        env_file = ".env"


settings = Settings()
