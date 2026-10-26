"""Middleware de cabeçalhos de segurança.

Adiciona um conjunto mínimo e sensato de headers em toda resposta.
HSTS e CSP só entram em produção: não fazem sentido em HTTP local e o CSP
quebraria o HMR/inline styles do Vite. A CSP é estática (sem nonce), o que
basta para um template; sobrescreva `CSP_POLICY` se o app precisar de mais.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.core.config import settings
from app.core.observability import current_trace_id

# Valores que valem para a maioria dos apps web.
# Override no seu app se precisar de algo mais permissivo.
_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}

# Constante única para o app sobrescrever sem mexer no middleware.
CSP_POLICY = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "font-src 'self' data:; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "frame-ancestors 'none'; "
    "form-action 'self'"
)

_HSTS = "max-age=31536000; includeSubDomains"

# Headers que só valem em produção (HTTPS). Ver `settings.is_prod`.
_PROD_HEADERS: dict[str, str] = {
    "Strict-Transport-Security": _HSTS,
    "Content-Security-Policy": CSP_POLICY,
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
        if settings.is_prod:
            for k, v in _PROD_HEADERS.items():
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
