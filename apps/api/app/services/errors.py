"""Erros de domínio da camada de serviço (agnósticos de HTTP; o app os traduz)."""


class NotFoundError(LookupError):
    """Recurso inexistente (→ 404)."""
