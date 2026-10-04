"""Registro de tasks: kind -> callable."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger


@dataclass(slots=True)
class JobContext:
    """Tudo que a task precisa para rodar."""
    session: AsyncSession
    job_id: Any
    kind: str
    payload: dict
    log: Any = None

    def __post_init__(self) -> None:
        if self.log is None:
            self.log = get_logger("jobs")


TaskFn = Callable[[JobContext], Awaitable[None]]

_REGISTRY: dict[str, TaskFn] = {}


def register_task(kind: str, fn: TaskFn) -> None:
    if kind in _REGISTRY:
        raise RuntimeError(f"task já registrada para kind={kind!r}")
    _REGISTRY[kind] = fn


def get_task(kind: str) -> TaskFn | None:
    return _REGISTRY.get(kind)


def known_kinds() -> list[str]:
    return sorted(_REGISTRY.keys())