"""CLI utilitário para devs.

Uso:
    python -m app.cli dump-openapi > apps/api/openapi.json
    python -m app.cli seed                       # cria admin@example.com (primeiro dev)
    python -m app.cli create-user email@x.com senha123 "Nome"
    python -m app.cli enqueue-job email.send '{"to":"a@b.com"}'
    python -m app.cli db-status
"""
from __future__ import annotations

import asyncio
import json
import secrets
import string
import sys
from collections.abc import Awaitable, Callable

from sqlalchemy import text

from app.core.logging import get_logger
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.jobs.app import app as procrastinate_app
from app.jobs.tasks.email import send_email
from app.main import app as fastapi_app

log = get_logger("cli")

_DEFAULT_SEED_EMAIL = "admin@example.com"
_DEFAULT_SEED_NAME = "Admin"


# -----------------------------------------------------------------------------
# Subcommands (sync e async)
# -----------------------------------------------------------------------------
def cmd_dump_openapi(_args: list[str]) -> int:
    sys.stdout.write(json.dumps(fastapi_app.openapi(), indent=2))
    return 0


def _gen_password(length: int = 16) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


async def _seed() -> None:
    """Cria admin se ainda não existe. Imprime credenciais na 1ª vez."""
    email = _DEFAULT_SEED_EMAIL
    async with SessionLocal() as session, session.begin():
        existing = (
            await session.execute(
                text("SELECT id FROM users WHERE email = :e"),
                {"e": email},
            )
            .mappings()
            .first()
        )
        if existing:
            print(f"admin já existe (id={existing['id']}); nada a fazer.")
            return

        password = _gen_password()
        row = (
            await session.execute(
                text(
                    """
                        INSERT INTO users (email, password_hash, full_name, is_superuser)
                        VALUES (:e, :ph, :n, TRUE)
                        RETURNING id, email, created_at
                        """
                ),
                {
                    "e": email,
                    "ph": hash_password(password),
                    "n": _DEFAULT_SEED_NAME,
                },
            )
            .mappings()
            .first()
        )
    print(f"admin criado: id={row['id']} email={row['email']}")
    print(f"senha (guarde, não será mostrada de novo): {password}")


async def _create_user(email: str, password: str, full_name: str | None) -> None:
    ph = hash_password(password)
    async with SessionLocal() as session:
        async with session.begin():
            row = (
                await session.execute(
                    text(
                        """
                        INSERT INTO users (email, password_hash, full_name)
                        VALUES (:e, :ph, :n)
                        RETURNING id, email, full_name
                        """
                    ),
                    {"e": email, "ph": ph, "n": full_name},
                )
                .mappings()
                .first()
            )
        print(f"created: id={row['id']} email={row['email']}")


async def _enqueue_job(kind: str, payload_json: str) -> None:
    """Enfileira um job via Procrastinate.

    `kind` mapeia 1:1 pro nome da task; `payload_json` são os kwargs do defer.
    """
    payload = json.loads(payload_json)
    tasks = {"email.send": send_email}
    task = tasks.get(kind)
    if task is None:
        raise SystemExit(f"kind desconhecido: {kind} (conhecidos: {sorted(tasks)})")
    # defer_async exige o App aberto (pool de conexões).
    async with procrastinate_app.open_async():
        job_id = await task.defer_async(**payload)
    print(f"queued: id={job_id} task={kind}")


async def _db_status() -> None:
    async with SessionLocal() as session:
        db_ok = (await session.execute(text("SELECT 1"))).scalar_one() == 1
        row = (
            await session.execute(
                text(
                    "SELECT status::text AS status, COUNT(*) AS n "
                    "FROM procrastinate_jobs GROUP BY status"
                )
            )
            .mappings()
            .all()
        )
        jobs = {r["status"]: r["n"] for r in row}
        sessions = (await session.execute(text("SELECT COUNT(*) FROM sessions"))).scalar_one()

    print(f"db:           {'ok' if db_ok else 'DOWN'}")
    print(f"jobs by status: {jobs or '{}'}")
    print(f"active sessions: {sessions}")

# -----------------------------------------------------------------------------
# Dispatcher
# -----------------------------------------------------------------------------
AsyncCmd = Callable[[list[str]], Awaitable[int]]
SyncCmd = Callable[[list[str]], int]


def _need(rank: str, n: int, args: list[str], usage_msg: str) -> int:
    if len(args) < n:
        sys.stderr.write(f"uso: {rank} {usage_msg}\n")
        return 2
    return 0


async def cmd_create_user(args: list[str]) -> int:
    if (rc := _need("create-user", 2, args, "<email> <password> [name]")):
        return rc
    await _create_user(args[0], args[1], args[2] if len(args) > 2 else None)
    return 0


async def cmd_enqueue_job(args: list[str]) -> int:
    if (rc := _need("enqueue-job", 1, args, "<kind> [payload-json]")):
        return rc
    await _enqueue_job(args[0], args[1] if len(args) > 1 else "{}")
    return 0


async def cmd_db_status(_args: list[str]) -> int:
    await _db_status()
    return 0


async def cmd_seed(_args: list[str]) -> int:
    await _seed()
    return 0


# Registry: name → async handler (sync ones wrapped in trivial async).
_REGISTRY: dict[str, AsyncCmd] = {
    "dump-openapi": lambda a: _to_async(cmd_dump_openapi, a),
    "seed": cmd_seed,
    "create-user": cmd_create_user,
    "enqueue-job": cmd_enqueue_job,
    "db-status": cmd_db_status,
}


async def _to_async(sync_fn: SyncCmd, args: list[str]) -> int:
    return sync_fn(args)


def usage() -> None:
    sys.stderr.write(
        "uso:\n"
        "  python -m app.cli dump-openapi\n"
        "  python -m app.cli seed\n"
        "  python -m app.cli create-user <email> <password> [name]\n"
        "  python -m app.cli enqueue-job <kind> [payload-json]\n"
        "  python -m app.cli db-status\n"
    )


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        usage()
        return 2
    cmd, args = argv[1], argv[2:]
    handler = _REGISTRY.get(cmd)
    if handler is None:
        sys.stderr.write(f"comando desconhecido: {cmd}\n")
        usage()
        return 2
    return asyncio.run(handler(args))


if __name__ == "__main__":
    sys.exit(main(sys.argv))