# Architecture decisions (ADR)

> Records of decisions that shaped this template.
> Each section follows: **Status** (current / superseded), **Context**, **Consequences**.
> Edit in place rather than appending new files unless the decision is final.

---

## AD-001 · Postgres-only (no Redis)

**Status**: current.

**Context**: The template needs cache, queues, sessions, geo, full-text, embeddings, and
hierarchies. Each could be a separate service (Redis, Elasticsearch, Neo4j, Pinecone…).
A monolith template shouldn't ship five different pieces of infra to be "complete".

**Decision**: Use Postgres + extensions (PostGIS, pgvector, ltree, pg_trgm, btree_gist,
pgcrypto, uuid-ossp, citext) as the single source of truth for everything except the front.

**Consequences**:
- One connection pool, one backup, one set of credentials.
- `background_jobs` table replaces Celery/Redis; `SELECT … FOR UPDATE SKIP LOCKED` scales
  horizontally and is ACID with the rest of the app.
- Sessions are server-side rows (`sessions.token_hash` + `sha256(token)` in cookie) — instant
  revocation, no JWT blocklist dance.
- `kv_cache` is `UNLOGGED` + TTL for ephemeral cache.
- When something genuinely needs sub-ms latency at massive scale (pub/sub, geofencing with
  millions of writes/s) we add the right tool then, not preemptively.

---

## AD-002 · Procrastinate over Celery/RQ/custom SKIP LOCKED

**Status**: current.

**Context**: We need a job queue. Options: Celery (Redis/RabbitMQ broker), RQ, Dramatiq,
arq, a hand-rolled `background_jobs` + `SKIP LOCKED` runner, or **Procrastinate** (Postgres-only,
async-native, lib maintained by PeopleDoc/UKG).

We previously ran the hand-rolled `background_jobs` table + `SELECT … FOR UPDATE SKIP LOCKED`
+ visibility-timeout recovery + exponential backoff. It worked, but reinventing the wheel
came with ongoing maintenance (heartbeat, stall detection, periodic tasks, DLQ, retry
strategies — each implemented and tested by hand).

**Decision**: Use **Procrastinate 3.10.0** as the queue. Schema is applied verbatim from the
lib via `SchemaManager.apply_schema()` in the migration — no duplication.

**Consequences**:
- Postgres-only: same transactional guarantees as the rest of the app.
- Async-native (psycopg3), so the API event loop is never blocked by worker I/O.
- Heartbeat + stall recovery are handled by the lib, not by us.
- Periodic tasks built-in (`@app.periodic(cron="...")`).
- Trade-off: a few advanced Celery features (chains, chords, fanout canvas) aren't available.
  For our use cases, the `@app.task` decorator + `defer_async` covers everything.
- See `apps/api/app/jobs/app.py` for the wiring and `apps/api/app/jobs/tasks/email.py` for an
  example task.

---

## AD-003 · bcrypt directly (no passlib)

**Status**: current.

**Context**: passlib 1.7.4 (latest) is in maintenance and is incompatible with bcrypt ≥ 4.1
(`AttributeError: module 'bcrypt' has no '__about__'`, plus the silent 72-byte truncation).

**Decision**: Use `bcrypt` library directly. Truncate passwords to 72 bytes explicitly
before hashing (per bcrypt spec) to avoid divergence between hash and check on multibyte chars.

**Consequences**:
- One library instead of two.
- Tests caught the passlib issue at template time; users don't rediscover it.
- Hash format: `$2b$…` (matches what `passlib` produced for existing hashes — backwards-compatible).

---

## AD-004 · OpenAPI → TypeScript via openapi-typescript

**Status**: current.

**Context**: Frontend needs typed `fetch` calls. Options: hand-roll types, codegen from
OpenAPI, or use a runtime client like `openapi-fetch`.

**Decision**: 
- Backend exposes OpenAPI at `/api/openapi.json`.
- `python -m app.cli dump-openapi` exports it to `apps/api/openapi.json` (gitignored).
- `npm run gen:api` (alias for `openapi-typescript`) produces `apps/web/src/api/schema.d.ts`
  (committed).
- `src/api/types.ts` re-exports what the app uses via `components["schemas"]`.
- `src/api/endpoints.ts` declares the helpers (`AuthApi.login({…}) → Promise<UserOut>`).

**Consequences**:
- Renaming a field on `UserOut` → typecheck fails on the front → fix or accept.
- Adding a path? TS picks up via `paths["/api/v1/…"]` in the generated schema.
- No runtime cost (types-only).

---

## AD-005 · SPA served by FastAPI (same host)

**Status**: current.

**Context**: Dev needs proxy /api → :8000 from Vite (:5173). Prod has CORS gotchas and
two deployable artifacts.

**Decision**: Build the front once into `apps/web/dist`. FastAPI mounts `/assets/*` and
serves `/favicon.ico` directly; catch-all GET serves `index.html` for client routing.
CORS only enabled in non-prod (same-origin in prod).

**Consequences**:
- One host, one origin, no CORS issues.
- `Cookie: HttpOnly; SameSite=Lax` works without flags.
- Dev still uses Vite + proxy for HMR.

---

## AD-006 · FastAPI/Starlette default catches unhandled exceptions as JSON

**Status**: current.

**Context**: Default FastAPI behavior on uncaught exception is `500 Internal Server Error`
with empty body — bad UX for clients, bad ops (no log correlation).

**Decision**: Custom `@app.exception_handler(Exception)` that:
1. Logs the traceback with `path` as context.
2. Returns `{"detail": "internal error"}` with status 500.

**Consequences**:
- Stack trace goes to the logger (structlog JSON in prod).
- Client gets a parseable shape.
- Pydantic validation errors keep their native 422 handler (FastAPI default).

---

## AD-007 · CLI is a real CLI, not just `dump-openapi`

**Status**: current.

**Context**: A template needs dev tooling. `dump-openapi` alone isn't enough.

**Decision**: `python -m app.cli <subcommand>`:
- `dump-openapi` — exports OpenAPI to stdout (used by `just web-types`)
- `create-user <email> <password> [name]` — admin tool
- `enqueue-job <kind> [payload-json]` — manual job injection
- `db-status` — quick health snapshot

**Consequences**:
- Subcommands live in `app.cli` next to the app, easy to extend.
- All async via `asyncio.run`.
- Documented via `--help` and the `usage()` function.

---

## AD-008 · Tests live next to code, not in CI

**Status**: current.

**Context**: A "lean" template shouldn't gate first commit behind a CI pipeline.

**Decision**: 
- `apps/api/tests/` with unit tests for pure functions (no DB).
- `just test` runs them locally.
- `.github/workflows/ci.yml` runs the same `just test` + `just lint` + `just typecheck`.

**Consequences**:
- No Postgres needed for `pytest`.
- Pure functions only — runner SQL is tested as text, not executed.
- CI catches regressions; users don't need to run it locally.

---

## AD-009 · Rate limit por IP+endpoint (Postgres-only)

**Status**: current.

**Context**: `/auth/login` e `/auth/register` precisam de rate limit. Sem isso,
força bruta e account-enumeration são triviais. Opções incluem Redis (mais uma peça
de infra) ou tabela `rate_limits` em Postgres.

**Decision**: Tabela `rate_limits (key, count, window_start)` + `INSERT … ON CONFLICT
DO UPDATE` que reseta a janela se expirada, incrementa caso contrário. Chave =
`ip:endpoint`. Algoritmo de janela fixa (não sliding). Limites atuais: login 5/min,
register 10/min.

**Consequences**:
- 1 round-trip por request (`hit()`); aceitable para auth.
- Janela fixa tem o problema clássico de bursts no boundary (5 em :59 + 5 em :00),
  mas é o trade-off certo pra proteger contra força bruta.
- Limpeza de linhas expiradas precisa de job (futuro: `pg_cron`).
- Se virar problema de latência sob carga, migrar para `pg_try_advisory_lock` mantém
  Postgres-only sem mudar a interface.

---

## AD-010 · Multi-region seams (documented, not implemented)

**Status**: documented seams; no implementation.

**Context**: o template não é multi-region, mas precisa apontar **onde** a costura
estaria quando virar. Sem isso, qualquer decisão de infra precisa reabrir tudo.

**Decision**: **só ADR por enquanto.** Multi-region para um app lean é over-engineering.

**Onde mexer:**

| Componente | Estado hoje | Quando virar multi-region |
|---|---|---|
| `sessions.token_hash` | único Postgres | precisa replicação síncrona (ou shared store) |
| Procrastinate (`procrastinate_jobs`) | uma fila global | múltiplos `locked_by` por região precisam de quorum / sharding |
| `rate_limits` | local ao cluster | pode ser local + sync entre regiões |
| Cookie `__Host-` | não usa | importante para multi-domain |
| `app.cli dump-openapi` | uma URL | por região |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | uma | múltiplos collectors |
| Procrastinate heartbeat/recovery | lib trata | por região, com `region` na chave de claim |

**Critério para ativar:**
- Latência p99 de geo > 200ms em algum mercado alvo.
- Ratio read:Write > 75:25 (read replicas compensam).
- Compliance exige dados em jurisdição específica.

Quando algum desses virar realidade, é hora de:
1. Adicionar `region` em `settings`.
2. Multi-cluster Postgres (RDS Multi-AZ ou Citus).
3. Router edge com sticky session.
4. Worker pool por região com separação clara.

---

## AD-011 · Observability: vendor-agnostic via OTLP + Sentry opcional

**Status**: current.

**Context**: o app precisa de tracing/metrics e error tracking sem ficar preso a um
vendor. Grafana stack é a stack open-source/self-hosted que o usuário pediu.

**Decision**:
- `app.core.observability` ativa OTel SDK (FastAPI, SQLAlchemy, logging) quando
  `OTEL_EXPORTER_OTLP_ENDPOINT` está setado.
- `app.core.observability` ativa Sentry SDK quando `SENTRY_DSN` está setado.
- O compose tem um perfil `observability` com OTel Collector + Tempo + Prometheus +
  Grafana, todos Grafana Labs (free, open source).
- App nunca importa o vendor diretamente — sempre OTLP/Sentry SDK.

**Consequences**:
- Quem prefere Grafana Cloud (SaaS) só aponta `OTEL_EXPORTER_OTLP_ENDPOINT` pra URL deles.
- Quem prefere Honeycomb/Dynatrace/New Relic: mesmo mecanismo.
- Sentry self-hosted é **pesado** (Postgres + ClickHouse + Kafka + Snuba) — não cabe
  no `observability` profile. Se quiser, opera separado.
- `traces_sample_rate=1.0` por padrão; ajustar em prod com base em volume.

---

## Future ADs (open questions)

- _(none open — all shipped infra is documented above; product-level decisions like
  2FA enforcement policy and OAuth/SSO live in the project README roadmap)_