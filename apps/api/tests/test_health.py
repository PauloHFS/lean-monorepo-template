"""Testes dos health checks (sem Postgres — AD-008).

Chama os handlers diretamente: `httpx`/`TestClient` não são dependências.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import Response

from app.api.v1.endpoints import health


async def _fail() -> bool:
    raise RuntimeError("db down")


async def _ok() -> bool:
    return True


def test_livez_does_not_touch_db(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(health, "_db_ok", _fail)

    out = asyncio.run(health.livez())

    assert out.status == "ok"


def test_liveness_model_default() -> None:
    assert health.LivenessOut().status == "ok"


def test_readiness_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(health, "_db_ok", _ok)
    response = Response()

    out = asyncio.run(health.healthz(response))

    assert response.status_code == 200
    assert out.status == "ok"
    assert out.db is True


def test_readiness_degraded_on_db_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(health, "_db_ok", _fail)
    response = Response()

    out = asyncio.run(health.healthz(response))

    assert response.status_code == 503
    assert out.status == "degraded"
    assert out.db is False


def test_readiness_degraded_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _slow() -> bool:
        await asyncio.sleep(1)
        return True

    monkeypatch.setattr(health, "DB_PROBE_TIMEOUT_S", 0.01)
    monkeypatch.setattr(health, "_db_ok", _slow)
    response = Response()

    out = asyncio.run(health.healthz(response))

    assert response.status_code == 503
    assert out.status == "degraded"
    assert out.db is False


def test_liveness_out_has_no_db_field() -> None:
    assert set(health.LivenessOut().model_dump()) == {"status"}
