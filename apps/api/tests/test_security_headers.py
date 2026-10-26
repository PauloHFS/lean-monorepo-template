"""HSTS/CSP só em produção (AD-008: sem banco)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from starlette.requests import Request
from starlette.responses import Response

from app.core import middleware
from app.core.middleware import CSP_POLICY, SecurityHeadersMiddleware


async def _dummy_app(scope: Any, receive: Any, send: Any) -> None:
    return None


def _request() -> Request:
    return Request({"type": "http", "method": "GET", "path": "/", "headers": []})


async def _call_next(_request: Request) -> Response:
    return Response("ok")


async def _dispatch() -> Response:
    return await SecurityHeadersMiddleware(_dummy_app).dispatch(_request(), _call_next)


async def test_prod_adds_hsts_and_csp(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(middleware, "settings", SimpleNamespace(is_prod=True))

    response = await _dispatch()

    assert response.headers["Strict-Transport-Security"] == "max-age=31536000; includeSubDomains"
    assert response.headers["Content-Security-Policy"] == CSP_POLICY


async def test_non_prod_omits_hsts_and_csp(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(middleware, "settings", SimpleNamespace(is_prod=False))

    response = await _dispatch()

    assert "Strict-Transport-Security" not in response.headers
    assert "Content-Security-Policy" not in response.headers
    # Os headers básicos continuam valendo em qualquer ambiente.
    assert response.headers["X-Content-Type-Options"] == "nosniff"
