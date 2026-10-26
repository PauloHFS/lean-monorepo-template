"""CLI utilitário para devs.

Uso:
    python -m app.cli dump-openapi > apps/api/openapi.json
    python -m app.cli seed                       # cria admin@example.com (primeiro dev)
    python -m app.cli create-user email@x.com senha123 "Nome"
    python -m app.cli enqueue-job email.send '{"to":"a@b.com"}'
    python -m app.cli list-dead-letters [limit]
    python -m app.cli retry-dead-letter <id>
    python -m app.cli discard-dead-letter <id>
    python -m app.cli db-status
"""

from __future__ import annotations

import asyncio
import json
import secrets
import string
import sys
from collections.abc import Callable, Coroutine
from typing import Any, cast

from sqlalchemy import text

from app.core.logging import get_logger
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.jobs.app import app as procrastinate_app
from app.jobs.app import defer_job
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


def gen_password(length: int = 16) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


async def _seed() -> None:
    """Cria admin se ainda não existe. Imprime credenciais na 1ª vez."""
    email = _DEFAULT_SEED_EMAIL
    async with SessionLocal() as session, session.begin():
        existing = (
            (
                await session.execute(
                    text("SELECT id FROM users WHERE email = :e"),
                    {"e": email},
                )
            )
            .mappings()
            .first()
        )
        if existing:
            print(f"admin já existe (id={existing['id']}); nada a fazer.")
            return

        password = gen_password()
        row = (
            (
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
            )
            .mappings()
            .first()
        )
    if row is None:
        raise RuntimeError("INSERT de admin não retornou linha")
    print(f"admin criado: id={row['id']} email={row['email']}")
    print(f"senha (guarde, não será mostrada de novo): {password}")


async def _create_user(
    email: str, password: str, full_name: str | None, *, superuser: bool = False
) -> None:
    """Cria o usuário ou garante o existente (idempotente).

    `superuser=True` promove; um usuário comum NUNCA rebaixa um admin
    (`users.is_superuser OR EXCLUDED.is_superuser`).
    """
    ph = hash_password(password)
    async with SessionLocal() as session:
        async with session.begin():
            row = (
                (
                    await session.execute(
                        text(
                            """
                            INSERT INTO users (email, password_hash, full_name, is_superuser)
                            VALUES (:e, :ph, :n, :su)
                            ON CONFLICT (email) DO UPDATE
                              SET password_hash = EXCLUDED.password_hash,
                                  full_name = COALESCE(EXCLUDED.full_name, users.full_name),
                                  is_superuser = users.is_superuser OR EXCLUDED.is_superuser
                            RETURNING id, email, full_name, is_superuser
                            """
                        ),
                        {"e": email, "ph": ph, "n": full_name, "su": superuser},
                    )
                )
                .mappings()
                .first()
            )
        if row is None:
            raise RuntimeError("INSERT de usuário não retornou linha")
        print(f"ok: id={row['id']} email={row['email']} superuser={row['is_superuser']}")


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
        job_id = await defer_job(task, **payload)
    print(f"queued: id={job_id} task={kind}")


async def _list_dead_letters(limit: int) -> None:
    async with SessionLocal() as session:
        rows = (
            (
                await session.execute(
                    text(
                        "SELECT id, kind, key, status, retries, created_at, error "
                        "FROM dead_letters ORDER BY created_at DESC LIMIT :limit"
                    ),
                    {"limit": limit},
                )
            )
            .mappings()
            .all()
        )
    if not rows:
        print("nenhuma dead letter")
        return
    for row in rows:
        print(
            f"#{row['id']} kind={row['kind']} key={row['key']!r} "
            f"status={row['status']} retries={row['retries']} "
            f"created_at={row['created_at']} error={row['error']}"
        )


async def _retry_dead_letter(dead_letter_id: int) -> None:
    async with SessionLocal() as session:
        row = (
            (
                await session.execute(
                    text(
                        "SELECT id, kind, payload FROM dead_letters "
                        "WHERE id = :id AND status = 'pending'"
                    ),
                    {"id": dead_letter_id},
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            raise SystemExit(f"dead letter {dead_letter_id} não encontrada ou já resolvida")

        task = cast(Any, procrastinate_app).tasks.get(row["kind"])
        if task is None:
            raise SystemExit(f"task {row['kind']!r} não registrada")

        stored = cast(dict[str, Any], row["payload"]) if isinstance(row["payload"], dict) else {}
        kwargs = cast(dict[str, Any], stored.get("kwargs", stored))
        async with procrastinate_app.open_async():
            job_id = await task.defer_async(**kwargs)

        updated = (
            (
                await session.execute(
                    text(
                        "UPDATE dead_letters SET status = 'retried', "
                        "retries = retries + 1, resolved_at = now() "
                        "WHERE id = :id AND status = 'pending' RETURNING id"
                    ),
                    {"id": dead_letter_id},
                )
            )
            .mappings()
            .first()
        )
        await session.commit()

    if updated is None:
        raise SystemExit(f"dead letter {dead_letter_id} mudou de estado; não foi marcada")
    print(f"requeued: dead_letter={dead_letter_id} job_id={job_id} task={row['kind']}")


async def _discard_dead_letter(dead_letter_id: int) -> None:
    async with SessionLocal() as session:
        row = (
            (
                await session.execute(
                    text(
                        "UPDATE dead_letters SET status = 'discarded', resolved_at = now() "
                        "WHERE id = :id AND status = 'pending' RETURNING id"
                    ),
                    {"id": dead_letter_id},
                )
            )
            .mappings()
            .first()
        )
        await session.commit()
    if row is None:
        raise SystemExit(f"dead letter {dead_letter_id} não encontrada ou já resolvida")
    print(f"discarded: dead_letter={dead_letter_id}")


async def _db_status() -> None:
    async with SessionLocal() as session:
        db_ok = (await session.execute(text("SELECT 1"))).scalar_one() == 1
        row = (
            (
                await session.execute(
                    text(
                        "SELECT status::text AS status, COUNT(*) AS n "
                        "FROM procrastinate_jobs GROUP BY status"
                    )
                )
            )
            .mappings()
            .all()
        )
        jobs: dict[str, Any] = {r["status"]: r["n"] for r in row}
        sessions = (await session.execute(text("SELECT COUNT(*) FROM sessions"))).scalar_one()

    print(f"db:           {'ok' if db_ok else 'DOWN'}")
    print(f"jobs by status: {jobs or '{}'}")
    print(f"active sessions: {sessions}")


# -----------------------------------------------------------------------------
# Dispatcher
# -----------------------------------------------------------------------------
AsyncCmd = Callable[[list[str]], Coroutine[Any, Any, int]]
SyncCmd = Callable[[list[str]], int]


def _need(rank: str, n: int, args: list[str], usage_msg: str) -> int:
    if len(args) < n:
        sys.stderr.write(f"uso: {rank} {usage_msg}\n")
        return 2
    return 0


async def cmd_create_user(args: list[str]) -> int:
    if rc := _need("create-user", 2, args, "<email> <password> [name] [--superuser]"):
        return rc
    superuser = "--superuser" in args
    positional = [a for a in args if a != "--superuser"]
    await _create_user(
        positional[0],
        positional[1],
        positional[2] if len(positional) > 2 else None,
        superuser=superuser,
    )
    return 0


async def cmd_enqueue_job(args: list[str]) -> int:
    if rc := _need("enqueue-job", 1, args, "<kind> [payload-json]"):
        return rc
    await _enqueue_job(args[0], args[1] if len(args) > 1 else "{}")
    return 0


def _parse_dead_letter_id(action: str, args: list[str]) -> int | None:
    if _need(action, 1, args, "<id>"):
        return None
    try:
        return int(args[0])
    except ValueError:
        sys.stderr.write(f"uso: {action} <id> (id numérico)\n")
        return None


async def cmd_list_dead_letters(args: list[str]) -> int:
    limit = 20
    if args:
        try:
            limit = int(args[0])
        except ValueError:
            sys.stderr.write("uso: list-dead-letters [limit]\n")
            return 2
    await _list_dead_letters(limit)
    return 0


async def cmd_retry_dead_letter(args: list[str]) -> int:
    dead_letter_id = _parse_dead_letter_id("retry-dead-letter", args)
    if dead_letter_id is None:
        return 2
    await _retry_dead_letter(dead_letter_id)
    return 0


async def cmd_discard_dead_letter(args: list[str]) -> int:
    dead_letter_id = _parse_dead_letter_id("discard-dead-letter", args)
    if dead_letter_id is None:
        return 2
    await _discard_dead_letter(dead_letter_id)
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
    "list-dead-letters": cmd_list_dead_letters,
    "retry-dead-letter": cmd_retry_dead_letter,
    "discard-dead-letter": cmd_discard_dead_letter,
    "db-status": cmd_db_status,
}


async def _to_async(sync_fn: SyncCmd, args: list[str]) -> int:
    return sync_fn(args)


def usage() -> None:
    sys.stderr.write(
        "uso:\n"
        "  python -m app.cli dump-openapi\n"
        "  python -m app.cli seed\n"
        "  python -m app.cli create-user <email> <password> [name] [--superuser]\n"
        "  python -m app.cli enqueue-job <kind> [payload-json]\n"
        "  python -m app.cli list-dead-letters [limit]\n"
        "  python -m app.cli retry-dead-letter <id>\n"
        "  python -m app.cli discard-dead-letter <id>\n"
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
