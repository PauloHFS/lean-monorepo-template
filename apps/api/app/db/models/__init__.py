"""Modelos relacionais.

A migration `0001_initial_schema.py` cria estas tabelas via SQL puro
(extensões + tipos específicos do Postgres: CITEXT, INET, JSONB).
Aqui mantemos o espelho SQLAlchemy 2.x para uso no app e autogenerate.
"""
from app.db.models.job import BackgroundJob, JobKind, JobStatus
from app.db.models.kv_cache import KvCache
from app.db.models.rate_limit import RateLimit
from app.db.models.session import Session
from app.db.models.twofa import TotpRecoveryCode, UserPasskey
from app.db.models.user import User

__all__ = [
    "User",
    "Session",
    "BackgroundJob",
    "JobKind",
    "JobStatus",
    "RateLimit",
    "KvCache",
    "TotpRecoveryCode",
    "UserPasskey",
]
