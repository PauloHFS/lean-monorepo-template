"""Config de produção (fail-fast) e aplicação de sslmode na DSN."""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest
from psycopg.conninfo import conninfo_to_dict
from pydantic import ValidationError
from sqlalchemy.engine import make_url

from app.core.config import Settings
from app.db.session import apply_sslmode

_DEFAULT_SECRET = Settings.model_fields["secret_key"].default
_SECRET = "s" * 40
_HTTPS_ORIGIN = "https://app.example.com"


def _prod(**overrides: object) -> Settings:
    kwargs: dict[str, object] = {
        "app_env": "prod",
        "secret_key": _SECRET,
        "cookie_secure": True,
        "web_origin": _HTTPS_ORIGIN,
        **overrides,
    }
    return Settings.model_validate(kwargs)


def test_prod_accepts_hardened_config() -> None:
    settings = _prod()

    assert settings.is_prod is True
    assert settings.secret_key == _SECRET


def test_non_prod_keeps_insecure_defaults() -> None:
    settings = Settings(app_env="local")

    assert settings.is_prod is False
    assert settings.cookie_secure is False


def test_prod_rejects_default_secret() -> None:
    with pytest.raises(ValidationError) as exc_info:
        _prod(secret_key=_DEFAULT_SECRET)

    assert "SECRET_KEY" in str(exc_info.value)


def test_prod_rejects_short_secret() -> None:
    with pytest.raises(ValidationError) as exc_info:
        _prod(secret_key="too-short")

    assert "SECRET_KEY" in str(exc_info.value)


def test_prod_rejects_insecure_cookie() -> None:
    with pytest.raises(ValidationError) as exc_info:
        _prod(cookie_secure=False)

    assert "COOKIE_SECURE" in str(exc_info.value)


def test_prod_rejects_non_https_origin() -> None:
    with pytest.raises(ValidationError) as exc_info:
        _prod(web_origin="http://insecure.example.com")

    assert "WEB_ORIGIN" in str(exc_info.value)


def test_db_sslmode_default_and_override(monkeypatch: pytest.MonkeyPatch) -> None:
    # O .env de dev pode setar DB_SSLMODE; o default é None (sem sslmode).
    monkeypatch.delenv("DB_SSLMODE", raising=False)
    assert Settings(app_env="local").db_sslmode is None
    assert Settings(app_env="local", db_sslmode="require").db_sslmode == "require"


def test_apply_sslmode_noop_when_unset() -> None:
    dsn = "postgresql+asyncpg://u:p@db:5432/app?pool_pre_ping=true"

    assert apply_sslmode(dsn, None) == dsn


def test_apply_sslmode_appends_and_preserves_existing_query() -> None:
    dsn = "postgresql+asyncpg://u:p@db:5432/app?pool_pre_ping=true"

    result = apply_sslmode(dsn, "require")

    parts = urlsplit(result)
    assert parse_qs(parts.query) == {"pool_pre_ping": ["true"], "sslmode": ["require"]}


def test_apply_sslmode_replaces_existing_value() -> None:
    dsn = "postgresql+asyncpg://u:p@db:5432/app?sslmode=prefer"

    result = apply_sslmode(dsn, "require")

    assert parse_qs(urlsplit(result).query) == {"sslmode": ["require"]}


@pytest.mark.parametrize(
    "password",
    [
        "Ifa5q/ZB1eCoA9lYTDynJPpJNT7Ebo5B",  # "/" quebra a DSN sem encoding
        "p@ssw0rd",
        "senha#com#hash",
        "senha:com:dois-pontos",
        "senha?com?query",
        "senha%com%percent",
        "senha com espaco",
    ],
)
def test_dsn_encodes_url_unsafe_credentials(password: str) -> None:
    """Senha com caractere de URL não pode derrubar o import do config.

    `PostgresDsn.build()` não escapa as credenciais: com "/" na senha a DSN
    fica inválida (`invalid port number`) e o `migrate` morre antes de rodar
    a migration. As credenciais precisam ir percent-encoded.
    """
    settings = Settings(
        app_env="local",
        postgres_user="app",
        postgres_password=password,
        postgres_host="postgres",
        postgres_port=5432,
        postgres_db="app",
    )

    assert "%2F" in settings.database_url_async or "/" not in password

    # Round-trip: quem consome a DSN tem que receber a senha original.
    assert make_url(settings.database_url_async).password == password
    assert make_url(settings.database_url_sync).password == password
    assert conninfo_to_dict(settings.database_url_procrastinate)["password"] == password
