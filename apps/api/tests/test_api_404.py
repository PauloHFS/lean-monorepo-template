"""Fallback da SPA não pode engolir rotas /api/* inexistentes."""

from __future__ import annotations

import asyncio
import importlib
import json
from pathlib import Path

import pytest


def test_api_prefix_returns_404(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "index.html").write_text("<html></html>")
    monkeypatch.setenv("SPA_DIST_PATH", str(tmp_path))

    main = importlib.reload(importlib.import_module("app.main"))

    response = asyncio.run(main.spa_fallback("api/v1/nonexistent"))

    assert response.status_code == 404
    assert json.loads(response.body) == {"detail": "not found"}
