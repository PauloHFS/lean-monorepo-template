"""Config central via Pydantic Settings.

Lê de .env / variáveis de ambiente. Importa em qualquer lugar como:
    from app.core.config import settings
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import PostgresDsn, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Geral ---
    app_env: Literal["local", "staging", "prod"] = "local"
    app_name: str = "lean-monorepo"
    app_version: str = "0.1.0"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # --- API ---
    web_origin: str = "http://localhost:5173"

    # --- Banco ---
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "app"
    postgres_user: str = "app"
    postgres_password: str = "app"
    database_url: str | None = None

    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_timeout: int = 30

    # --- Auth ---
    secret_key: str = "change-me-please-32-bytes-minimum-aaaaaaaaaaaaaaaaaaaa"
    session_cookie_name: str = "lm_session"
    session_ttl_seconds: int = 60 * 60 * 24 * 30  # 30d
    cookie_secure: bool = False
    cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    password_min_length: int = 8

    # --- Worker ---
    worker_poll_interval_ms: int = 500
    worker_batch_size: int = 5
    worker_visibility_timeout_s: int = 300

    # ---------- DSNs computadas ----------
    @computed_field  # type: ignore[prop-decorator]
    @property
    def database_url_async(self) -> str:
        if self.database_url:
            return self.database_url
        return str(
            PostgresDsn.build(
                scheme="postgresql+asyncpg",
                username=self.postgres_user,
                password=self.postgres_password,
                host=self.postgres_host,
                port=self.postgres_port,
                path=self.postgres_db,
            )
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def database_url_sync(self) -> str:
        if self.database_url:
            return self.database_url.replace("+asyncpg", "+psycopg2")
        return str(
            PostgresDsn.build(
                scheme="postgresql+psycopg2",
                username=self.postgres_user,
                password=self.postgres_password,
                host=self.postgres_host,
                port=self.postgres_port,
                path=self.postgres_db,
            )
        )

    @property
    def is_prod(self) -> bool:
        return self.app_env == "prod"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings: Settings = get_settings()