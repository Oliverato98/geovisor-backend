from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    database_url: str
    sync_database_url: str
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 480
    redis_url: str = "redis://localhost:6379"
    upload_dir: str = "./uploads"
    max_file_size_mb: int = 200
    allowed_origins: str = "http://localhost:5173"

    @property
    def origins_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",")]

    class Config:
        env_file = ".env"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
