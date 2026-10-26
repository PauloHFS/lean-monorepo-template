"""Config central via Pydantic Settings.

Lê de .env / variáveis de ambiente. Importa em qualquer lugar como:
    from app.core.config import settings
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import (
    AliasChoices,
    Field,
    PostgresDsn,
    computed_field,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_SECRET_KEY = "change-me-please-32-bytes-minimum-aaaaaaaaaaaaaaaaaaaa"


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
    # Anexado à DSN (query string) quando definido; ex.: "require".
    db_sslmode: str | None = None

    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_timeout: int = 30

    # --- Auth ---
    secret_key: str = _DEFAULT_SECRET_KEY
    session_cookie_name: str = "lm_session"
    session_ttl_seconds: int = 60 * 60 * 24 * 30  # 30d
    cookie_secure: bool = False
    cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    password_min_length: int = 8

    # --- Worker ---
    worker_poll_interval_ms: int = 500
    worker_batch_size: int = 5
    worker_visibility_timeout_s: int = 300

    # --- Observability (AD-011) ---
    # Tudo opcional: sem endpoint/DSN o tracing é no-op.
    otel_exporter_otlp_endpoint: str | None = None
    otel_traces_sampler: str | None = None
    # Aceita também o nome padrão do OTel para o argumento do sampler.
    otel_sample_ratio: float = Field(
        default=1.0,
        validation_alias=AliasChoices("OTEL_SAMPLE_RATIO", "OTEL_TRACES_SAMPLER_ARG"),
    )
    sentry_dsn: str | None = None
    sentry_traces_sample_rate: float = 1.0

    @field_validator("password_min_length")
    @classmethod
    def _validate_password_min_length(cls, value: int) -> int:
        """Fail-fast: o schema de senha rejeita acima de 72 bytes.

        O bcrypt 5.x rejeita senhas acima disso. Um mínimo acima do teto geraria
        um schema impossível e quebraria o import do app; falhar aqui dá uma
        mensagem acionável no boot.
        """
        if not 1 <= value <= 72:
            raise ValueError(
                "PASSWORD_MIN_LENGTH must be between 1 and 72: the password "
                "schema caps at 72 and bcrypt rejects passwords over 72 BYTES."
            )
        return value

    @model_validator(mode="after")
    def _validate_prod(self) -> Settings:
        """Fail-fast: config insegura em prod não sobe (AGENTS.md)."""
        if self.app_env != "prod":
            return self
        problems: list[str] = []
        if self.secret_key == _DEFAULT_SECRET_KEY or len(self.secret_key) < 32:
            problems.append(
                "SECRET_KEY must be changed from the default and have at least 32 characters"
            )
        if not self.cookie_secure:
            problems.append("COOKIE_SECURE must be true in prod")
        if not self.web_origin.startswith("https://"):
            problems.append("WEB_ORIGIN must start with https:// in prod")
        if problems:
            raise ValueError("invalid production config: " + "; ".join(problems))
        return self

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

    @computed_field  # type: ignore[prop-decorator]
    @property
    def database_url_procrastinate(self) -> str:
        """DSN libpq puro (psycopg3) para o Procrastinate.

        O worker do Procrastinate exige um connector *async* (PsycopgConnector),
        que recebe uma conninfo libpq (`postgresql://...`) — sem sufixo de driver
        SQLAlchemy. Derivamos da DSN sync removendo o `+psycopg2`.
        """
        return self.database_url_sync.replace("+psycopg2", "")

    @property
    def is_prod(self) -> bool:
        return self.app_env == "prod"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings: Settings = get_settings()
