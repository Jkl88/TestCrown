"""Настройки Crown из .env. Секреты только в окружении, не в коде."""

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Конфиг шлюза: БД, Redis, Gemini, cookie."""

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/crown"
    redis_url: str = "redis://localhost:6379/0"

    # Google Gemini. В .env допускается опечатка API_GMINI (как в остальных сервисах).
    api_gemini: str = Field(
        default="",
        validation_alias=AliasChoices("API_GMINI", "API_GEMINI", "api_gemini"),
    )
    gemini_model: str = Field(
        default="gemini-flash-lite-latest",
        validation_alias=AliasChoices("GEMINI_MODEL", "gemini_model"),
    )
    gemini_models: str = Field(
        default=(
            "gemini-flash-lite-latest,gemini-3.1-flash-lite,"
            "gemini-flash-latest,gemini-3.5-flash-lite"
        ),
        validation_alias=AliasChoices("GEMINI_MODELS", "gemini_models"),
    )
    ai_proxy_url: str = Field(default="", validation_alias="AI_PROXY_URL")

    cookie_name: str = "crown_api_key"
    cookie_secure: bool = False
    cookie_max_age_sec: int = 60 * 60 * 24 * 30
    frontend_origin: str = Field(default="http://localhost:8090")

    rate_limit_requests: int = 5
    rate_limit_window_sec: int = 60
    max_pdf_bytes: int = 15 * 1024 * 1024
    summary_cache_ttl_sec: int = 60 * 60

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def gemini_model_list(self) -> list[str]:
        """GEMINI_MODEL первым, затем GEMINI_MODELS без дублей — failover при 429."""
        out: list[str] = []
        primary = (self.gemini_model or "").strip()
        if primary:
            out.append(primary)
        for part in (self.gemini_models or "").split(","):
            name = part.strip()
            if name and name not in out:
                out.append(name)
        return out or ["gemini-flash-lite-latest"]


settings = Settings()
