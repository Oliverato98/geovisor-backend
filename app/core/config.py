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

    # URL pública del backend. En producción debe ser la de Railway, porque con
    # ella se arma el tile_url que consume MapLibre desde el navegador.
    public_url: str = "http://localhost:8000"

    # URL interna del tile server Martin (red privada, no sale a internet).
    # Railway: http://martin.railway.internal:3000 | Docker local: http://martin:3000
    martin_internal_url: str = "http://martin:3000"

    # Railway inyecta PORT; se declara para que pydantic no lo rechace.
    port: int = 8000

    @property
    def origins_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",")]

    class Config:
        env_file = ".env"
        # Ignora variables de entorno extra (Railway inyecta muchas propias)
        # para que el contenedor no falle al arrancar.
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
