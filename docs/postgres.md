# Postgres-only: tabelas, extensões e filas

Guia de Postgres-only do monorepo: como cada necessidade vira uma tabela, extensões opt-in, upgrade de major e as filas com Procrastinate. O índice com links e atalhos vive no README.

## Como cada coisa vira uma tabela

| Necessidade                | Solução                                                                                          |
| -------------------------- | ------------------------------------------------------------------------------------------------ |
| **Cache**                  | Tabela `kv_cache` (UNLOGGED + `expires_at`) — mais rápido que Redis, sem infra extra             |
| **Filas / jobs**            | Procrastinate 3.10.0 (Postgres-only, heartbeat/stall built-in, DLQ em `dead_letters`) — escala, ACID |
| **Sessões de auth**        | Tabela `sessions` com token opaco + hash — revogação instantânea, sem Redis                      |
| **Rate limiting**          | Tabela `rate_limits` + janela fixa via `INSERT … ON CONFLICT DO UPDATE`                           |
| **Limpeza automática**     | `pg_cron` quando disponível — 6 jobs (kv_cache, rate_limits, job_rate_limits, dead_letters, recovery codes, sessions); opcional em RDS/Aurora/Cloud SQL |
| **Grafos / hierarquia**    | Extensão `ltree` (contrib, criada pelo init) + CTEs recursivas — paths, subárvores, ancestry     |
| **Full-text / fuzzy**      | Extensões `pg_trgm` + `unaccent` (contrib, criadas pelo init) — busca tolerante a typo e acentos  |
| **Geoespacial**            | **Opt-in por projeto**: PostGIS não vem na imagem oficial; use imagem própria ou provider (RDS)   |
| **Embeddings / RAG**       | **Opt-in por projeto**: `pgvector` não vem na imagem oficial (`vector(1536)` + ivfflat/hnsw)      |
| **Schedules / cron**       | `pg_cron` **opcional** (não vem na imagem oficial; o cleanup só agenda quando disponível)         |
| **Lock distribuído**       | `pg_try_advisory_lock` + `pg_advisory_unlock`                                                    |

Só `citext` é **obrigatória** — a coluna `users.email` depende dela e a migration a cria. As extensões contrib já vêm na `postgres:18-alpine` (nada além de `citext` é usado pelo app hoje); PostGIS, pgvector e pg_cron exigem provider gerenciado ou imagem própria.

## Extensões opt-in (PostGIS, pgvector, pg_cron)

O init `../scripts/postgres-init/01-extensions.sql` é tolerante: cada extensão roda num bloco `DO`/`EXCEPTION` e, se a imagem não tiver o pacote, vira `NOTICE` em vez de abortar. Então habilitar uma extensão extra é usar uma imagem que a tenha (`pg_cron` também exige `shared_preload_libraries=pg_cron` no start):

**Imagem própria (PostGIS no arm64)** — a `postgis/postgis` é amd64-only (em arm64 roda emulada). Use a oficial Debian/trixie + o pacote do PGDG:

```dockerfile
FROM postgres:18
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates gnupg \
 && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
      | gpg --dearmor -o /usr/share/keyrings/pgdg.gpg \
 && echo "deb [signed-by=/usr/share/keyrings/pgdg.gpg] http://apt.postgresql.org/pub/repos/apt trixie-pgdg main" \
      > /etc/apt/sources.list.d/pgdg.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends postgresql-18-postgis-3 \
 && rm -rf /var/lib/apt/lists/*
```

No compose, troque `image: postgres:18-alpine` por `build: { context: ., dockerfile: Dockerfile.postgres }`. Em Alpine existe `postgis` (3.6.x), mas ele é compilado contra o `postgresql18` do próprio Alpine — outro prefixo (`/usr/...`) do source-build da imagem oficial (`/usr/local/...`), então não é drop-in. O caminho Debian/trixie acima é o verificado para `linux/arm64`.

**Postgres gerenciado com PostGIS** (ex.: RDS oferece a extensão): aponte `DATABASE_URL` para o banco e defina `DB_SSLMODE` (ex.: `require`); a API já aceita essa configuração. O init só roda no compose local — no banco gerenciado, crie a extensão pelo console/`psql`.

## Upgrade do Postgres (volume de major antigo)

O major novo muda o `PGDATA` (no PG18 é `/var/lib/postgresql/18/docker`), então **um volume de PG16/17 não sobe no PG18**. O sintoma é o container do Postgres em **loop de restart** com `mkdir: can't create directory '/var/lib/postgresql/18/': Permission denied` — o volume antigo pertence ao uid 999 (Debian) e o Alpine do PG18 roda como uid 70. O caminho é:

1. **Dump no major antigo** — `just backup-now` (ou `../scripts/backup.sh` no host; o `pg_dump` precisa ser do major do servidor).
2. **Volume novo** — no Coolify, o volume é do resource: esvazie/recrie antes do novo deploy (`docker run --rm -v <volume>:/v alpine sh -c 'rm -rf /v/* /v/.[!.]*'` deixa o cluster se inicializar no path novo). Em dado descartável, pular o restore é suficiente.
3. **Restore** com o client do **major novo** (o `pg_restore` exige client ≥ servidor): `../scripts/restore.sh <dump> --db app --yes`.
4. **Deploy de novo** — o container `migrate` aplica a baseline no banco novo.

Quando algum caso *realmente* pede Redis (pub/sub com baixa latência, geofencing com milhões de updates/s), você sabe que é exceção — não o default.

---

## Filas no Postgres — Procrastinate

`../apps/api/app/jobs/app.py` configura o [Procrastinate](https://procrastinate.readthedocs.io/) 3.10.0:

- **Async nativo** (psycopg3) — não bloqueia o event loop.
- **Heartbeat / stall recovery** automáticos — jobs travados são re-claimados pela lib.
- **Periodic tasks** built-in (`@app.periodic(cron="*/5 * * * *")`).
- **Schema oficial** vem direto da lib (nunca duplicar ~600 linhas de SQL); a migration 0001 aplica via `SchemaManager.apply_schema()`.
- **Nomes padronizados**: `register_task(queue, action)` registra `name=f"{queue}.{action}"` e valida que queue/action são minúsculos, sem ponto/espaço.
- **Retry com teto**: `register_task(..., max_retries=3)` limita as tentativas; sem teto a falha nunca vira dead letter.
- **Rate limit por job** (`job_rate_limits`) e **DLQ** (`dead_letters`) no próprio Postgres.

Pra criar uma task:

```python
# ../apps/api/app/jobs/tasks/minha_task.py
from app.jobs.app import register_task


@register_task("default", "minha-coisa")  # nome final: default.minha-coisa
async def minha_task(ctx, tenant_id: str) -> None:
    # faça trabalho idempotente
    ...
```

`register_task` liga a DLQ: se a task levantar exceção na **última** tentativa
(o retry do Procrastinate já exhausted), a falha vai para `dead_letters` (com
`kind`, payload, erro e `original_job_id`) e a exceção é relançada. Como a
decisão de "última tentativa" é a mesma do Procrastinate, a DLQ tem uma linha
por job que desistiu — não uma por tentativa.

Enfileire com `defer_job(task, ...)`, que aplica o rate limit por janela fixa
antes do `defer_async`:

```python
from app.jobs.app import defer_job

await defer_job(
    minha_task,
    rate_limit_kind="default.minha-coisa",
    rate_limit_key=f"user:{user_id}",
    rate_limit_limit=20,
    rate_limit_window_s=60,
    tenant_id=tenant_id,
)
```

As tabelas e o cleanup (`pg_cron`, quando disponível) vivem na baseline: `job_rate_limits` expira em
1 dia; `dead_letters` resolvidas/descartadas expiram em 90 dias. Opere a DLQ por
CLI: `python -m app.cli list-dead-letters`, `retry-dead-letter <id>` e
`discard-dead-letter <id>`.

Adicione o módulo em `app/jobs/tasks/`; o worker descobre automaticamente todos os módulos do pacote (`app.jobs.tasks.*`) sem editar `app.py`.

A task `email.send` é o exemplo. Em dev → SMTP para o container `mailpit` (UI em <http://localhost:8025>). Em prod → qualquer SMTP-relay.

Guia extraído do README. Índice e atalhos: [README](../README.md).
