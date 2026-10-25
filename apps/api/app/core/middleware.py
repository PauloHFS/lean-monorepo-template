"""Middleware de cabeçalhos de segurança.

Adiciona um conjunto mínimo e sensato de headers em toda resposta.
Não inclui CSP porque o template serve SPA + API; configurar CSP
corretamente requer decisões específicas do app (nonce, allowed origins).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.core.observability import current_trace_id

# Valores que valem para a maioria dos apps web.
# Override no seu app se precisar de algo mais permissivo.
_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Any]],
    ) -> Any:
        response = await call_next(request)
        for k, v in _HEADERS.items():
            response.headers.setdefault(k, v)
        return response


class TraceIdMiddleware(BaseHTTPMiddleware):
    """Expõe o trace id corrente para o cliente (`X-Trace-Id`)."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Any]],
    ) -> Any:
        response = await call_next(request)
        trace_id = current_trace_id()
        if trace_id is not None:
            response.headers.setdefault("X-Trace-Id", trace_id)
        return response
