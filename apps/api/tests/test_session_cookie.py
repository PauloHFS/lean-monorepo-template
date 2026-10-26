"""Cookie de sessão: set mantém TTL; clear expira sem `max_age` (bug do logout)."""

from __future__ import annotations

from starlette.responses import Response

from app.core.config import settings
from app.core.security import clear_session_cookie, set_session_cookie


def test_clear_session_cookie_expires_without_max_age_kwarg() -> None:
    # Antes do fix, delete_cookie recebia max_age e estourava TypeError (500).
    response = Response()

    clear_session_cookie(response)

    header = response.headers["set-cookie"].lower()
    assert f"{settings.session_cookie_name}=" in header
    assert "max-age=0" in header
    assert "expires=" in header
    assert "httponly" in header


def test_set_session_cookie_keeps_ttl() -> None:
    response = Response()

    set_session_cookie(response, "opaque-token")

    header = response.headers["set-cookie"].lower()
    assert f"max-age={settings.session_ttl_seconds}" in header
    assert "opaque-token" in header
