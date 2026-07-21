"""Environment/config loading for the FastAPI service."""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    postgres_user: str = "analytics"
    postgres_password: str = "changeme"
    postgres_db: str = "claude_code_analytics"
    postgres_host: str = "postgres"
    postgres_port: int = 5432

    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://localhost:8501",
    ]

    @property
    def database_dsn(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
