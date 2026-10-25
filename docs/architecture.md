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

## AD-012 · SQLAlchemy Core (`text()`) para queries, ORM só para schema

**Status**: current.

**Context**: SQLAlchemy oferece dois caminhos: ORM com `select(User).where(...)`
(retornando objetos, com identity map, lazy loading) e Core com `text()`/`select()`
(retornando `Row`/`dict`). Os modelos do projeto (`apps/api/app/db/models/`) usam
`Mapped[]` + `DeclarativeBase` (ORM) — isso alimenta Alembic autogen, metadata
introspection (FKs, indexes, tipos custom como `CITEXT`, `INET`, `JSONB`) e dá tipos
Python para os serviços. **As queries em runtime, porém, são todas Core/raw.**

Onde aparece:
- `apps/api/app/core/cache.py` — `GET_SQL`, `UPSERT_SQL`, `DELETE_SQL` como
  constantes módulo-level (`text()` na execução).
- `apps/api/app/core/ratelimit.py` — `INSERT INTO rate_limits ... ON CONFLICT DO UPDATE`
  para janela fixa de rate limit.
- `apps/api/app/api/v1/endpoints/auth.py`, `users.py`, `twofa.py`, `deps.py`,
  `health.py` — `text("SELECT/UPDATE/INSERT ...")` com `:bind` parameters.
- `apps/api/migrations/versions/0001_initial_schema.py` — DDL puro (Alembic op)
  + `SELECT cron.schedule(...)` para `pg_cron`.

**Decision**:
- **Modelos em ORM** (`Mapped[]`) — schema vive em Python, Alembic gera/revisão migrations,
  tipos Postgres exóticos declarados uma vez.
- **Queries em Core** (`text()`) — nenhuma rota passa por `session.query(Model)`;
  o que vai pro banco é SQL explícito com bind params (`session.execute(text(SQL), params)`).
- SQL dos hot paths de cache/ratelimit é exposto como constante módulo-level para
  que testes afirmem na *string* (não no efeito colateral).

**Consequences**:
- `ON CONFLICT DO UPDATE`, `FOR UPDATE SKIP LOCKED`, `RETURNING`, `cron.schedule`,
  CTE recursiva, operadores `JSONB`/`INET` — todos triviais em `text()`, todos
  exigiriam workaround em ORM (e alguns ficariam ilegíveis via `insert(...).on_conflict_do_update(...)`).
- Sem lazy loading → sem N+1 por acidente. Em hot path o custo é só do driver
  (`psycopg`/`asyncpg`), sem hydration de objeto nem identity map.
- Constantes SQL viram contrato — refactor de schema quebra `test_cache.py` /
  `test_ratelimit.py` (`assert "INSERT INTO kv_cache" in UPSERT_SQL`), exatamente
  onde deveria quebrar.
- Resultados das queries são consumidos como `Row`/`dict` e convertidos para Pydantic
  schemas (`UserOut(**dict(r))` em `users.py:list_users`). Sem hydration preguiçosa,
  sem identity map, sem N+1.
- Custo: SQL duplica entre modelo (`Mapped[...]`) e string SQL — schema drift é
  pego por `just check-schema` (gera migration e diffa contra a última commitada).
- Migração para outro ORM/SQL builder é custosa (muita string). Migração para
  dialect diferente de Postgres é igualmente custosa — assumido pela decisão
  Postgres-only em AD-001.

---

## AD-013 · `uv` como gerenciador único de Python (pyproject + uv.lock)

**Status**: current.

**Context**: o backend era instalado com `pip install -r apps/api/requirements.txt`
dentro de um venv criado à mão (`python -m venv .venv`). Isso dava pins diretos, mas
não lockfile: as versões transitivas eram re-resolvidas a cada instalação, o build do
Docker não tinha cache por dependência, o CI só cacheava o `requirements.txt` e não
existia auditoria de dependências Python (o `npm audit` cobria só o frontend).
`pip-audit` em modo `-r requirements.txt` ainda instala as dependências num venv
temporário, o que exige `ensurepip` — inviável com o Python gerenciado pelo `uv`.

**Decision**:
- `uv` é o único gerenciador de Python do projeto.
- Dependências de runtime ficam em `apps/api/pyproject.toml` (`[project]`, pins
  exatos) e as de desenvolvimento em `[dependency-groups] dev` (pytest, pytest-asyncio,
  ruff, pyright, bandit).
- `apps/api/uv.lock` é versionado e é a fonte de verdade das versões resolvidas
  (com hashes). `requirements.txt` foi removido.
- Local: `uv sync` cria/atualiza `apps/api/.venv`; `uv run <cmd>` executa ferramentas.
  CI: `uv sync --locked` (falha se o lock divergir do `pyproject.toml`).
  Docker: binário do `uv` copiado da imagem `ghcr.io/astral-sh/uv` pinada; o venv
  da imagem fica em `/opt/venv` (`UV_PROJECT_ENVIRONMENT`) para não ser encoberto
  pelo bind mount de `apps/api` no compose.
- Auditoria de dependências de produção: `just api-audit` roda
  `uvx pip-audit@2.10.1 --path` contra um env prod-only (`.venv-audit`), sem
  resolver/instalar nada — logo sem depender de `ensurepip`.

**Consequences**:
- Instalações reprodutíveis (lock com hashes) e cache de camadas por dependência
  no Docker/CI.
- O venv criado pelo `uv` não traz `pip`; ferramentas que dependem de pip rodam
  via `uvx` (semgrep, pip-audit) ou `uv tool install`.
- Atualização de segurança é bump em `pyproject.toml` + `uv lock` (ex.: aiosmtplib
  3.0.1 → 5.1.3, python-multipart 0.0.30 → 0.0.31, pytest 8.3.4 → 9.0.3).
- `uv` exige Python >= 3.10 no host; o projeto fixa 3.12 (`.python-version`).

---

## AD-014 · Tipagem estrita no backend (Pyright strict, sem lista de exclusões)

**Status**: current.

**Context**: `apps/api/pyrightconfig.json` rodava Pyright em `typeCheckingMode: "basic"`
com uma lista `ignore` que cobria endpoints, deps, cli, `core/*` e `tests/**` — a maior
parte do app não era checada. No modo `basic`, o padrão do app
`await session.execute(text(SQL), params).mappings().first()` passava sem aviso, mas
`AsyncSession.execute` é função corrotina: o `await` se aplica ao resultado inteiro e
`.mappings()` é chamado sobre o corrotina → `AttributeError: 'coroutine' object has no
attribute 'mappings'` em runtime. O padrão estava em 14 sites (cache, ratelimit, deps,
auth, users, twofa, cli) — ou seja, **toda query do app quebrava em produção**.

**Decision**:
- `typeCheckingMode: "strict"` com `include: ["app", "tests"]` e **sem** lista de
  exclusões. Única relaxação: `reportMissingTypeStubs: "warning"` (libs de terceiro
  sem stubs, ex.: `py-webauthn`).
- Invariante de runtime: isolar o `await` antes de encadear — `(await session.execute(...)).mappings().first()`.
- Fronteiras sem stub (`py-webauthn`, `pyotp`, `bcrypt`, instrumentação OTel) são
  normalizadas com `cast`/wrapper local, não com exclusão de arquivo nem `# type: ignore`
  em massa.
- `just typecheck` e o CI rodam `uv run pyright app tests` com 0 erros.

**Consequences**:
- O bug de `await` foi corrigido nos 14 sites e agora é erro de tipo, não de produção.
- `reportPrivateUsage` deixa de ser ignorada: código que usa API privada de lib precisa
  de wrapper público ou `getattr` explícito.
- Códigos novos em `app/` e `tests/` precisam de anotações completas; dívida de tipos
  vira falha de CI em vez de descoberta tardia.

---

## AD-015 · Testes de propriedades (Hypothesis) para validadores, cripto e rate limiter

**Status**: current.

**Context**: a suíte tinha 37 testes de caso fixo (`assert` direto), sem Postgres
(AD-008). Validadores Pydantic, criptografia (bcrypt/Fernet/TOTP) e rate limiter tinham
invariantes — round-trip, monotonicidade, limites de threshold — que nenhum teste
expressava.

**Decision**:
- `hypothesis` (dev group) cobre as propriedades em `tests/test_properties_*.py`:
  - **cripto**: round-trip bcrypt, hash ≠ senha, prefixo `$2b$12$`, senha errada → False,
    truncamento em 72 bytes, `ValueError` se e somente se `len < password_min_length`,
    sha256 do token de sessão (64 hex, determinístico), token URL-safe e único,
    TTL exato, round-trip Fernet, recovery codes.
  - **validadores**: `RegisterIn`, `LoginIn`, `EmailStr`, `UserOut`, `TotpConfirmIn`,
    `EnqueueEmailIn` — documentando a dívida atual sem alterar os schemas.
  - **rate limiter**: helpers puros `build_key(ip, endpoint)` e `is_blocked(count, limit)`
    extraídos de `app/core/ratelimit.py`, mais as invariantes do texto de `HIT_SQL`.
- `@settings(max_examples=..., deadline=None)` em tudo que usa bcrypt: um hash custa
  ~100 ms e o deadline padrão (200 ms) vira flake.
- A semântica de contagem/janela **continua no SQL**: extrai-se só a parte pura
  (chave e decisão), sem duplicar o algoritmo em Python.

**Consequences**:
- Invariantes ficam declaradas e verificadas por fuzzing, inclusive nas bordas
  (limiar `limit`/`limit+1`, senhas multibyte, tokens).
- Schemas com regras ausentes (`LoginIn` sem `min_length`, `TotpConfirmIn` sem padrão
  de 6 dígitos, `EnqueueEmailIn` sem `max_length`) ficam registrados como dívida
  nos TODOs dos testes — a correção muda contrato e merece decisão própria.
- AD-008 preservado: nenhum teste toca Postgres.

---

## AD-016 · Tracing distribuído consolidado (config, resource, sampler, log↔span, filas)

**Status**: current.

**Context**: AD-011 ativava o OTel, mas o app lia `os.environ` **no import** do módulo
de observabilidade (configuração não testável), o resource tinha só `service.name`, não
havia sampler explícito, os logs não carregavam `trace_id`, o job de email enfileirado
perdia o trace (a fila não carregava contexto), o provider nunca era finalizado (spans
morriam no container) e a resposta não trazia identificador de trace.

**Decision**:
- Configuração vem de `Settings` (`otel_exporter_otlp_endpoint`, `otel_traces_sampler`,
  `otel_sample_ratio` — aceita `OTEL_TRACES_SAMPLER_ARG` —, `sentry_dsn`,
  `sentry_traces_sample_rate`), **todos com default**: sem endpoint/DSN o tracing é
  no-op.
- `Resource` com `service.name`, `service.version`, `deployment.environment` e
  `service.namespace`; sampler explícito (`always_on`, `always_off`, `traceidratio`,
  `parentbased_traceidratio` — default parentbased com ratio).
- Propagador W3C composto (`tracecontext` + `baggage`) instalado sempre, mesmo sem
  exporter, para que `traceparent` de entrada alimente logs e spans manuais.
- Correlação log↔span: processor structlog `add_trace_context` anexa `trace_id`/`span_id`
  (hex) do span corrente — `None` quando não há span válido, nunca a string de zeros.
- Propagação para a fila: `inject_trace_context` grava o contexto W3C no payload do
  job; `extract_trace_context` o recupera no worker (job antigo sem `trace_context`
  continua funcionando, virando raiz). Spans manuais existem nas fronteiras
  (`email.enqueue` no endpoint, `email.send` no worker).
- `shutdown_tracing()` no `finally` do lifespan da API e no fim do runner do worker
  (flush + shutdown do provider).
- `X-Trace-Id` na resposta via `TraceIdMiddleware`.

**Consequences**:
- Um request e o job de email correspondente ficam no mesmo trace; os logs do
  caminho carregam `trace_id`/`span_id`.
- Sampling e roteamento de vendor continuam sendo decisão do operador (env vars);
  o app permanece vendor-agnostic (AD-011).
- Sem `OTEL_EXPORTER_OTLP_ENDPOINT`, o custo é praticamente zero.
- known gap: o endpoint grava em `background_jobs`, mas o worker Procrastinate consome
  a fila própria dele — a ponte entre as duas tabelas é pré-existente e segue fora do
  escopo. O payload já carrega `trace_context`, pronto para a ligação.

---

## Future ADs (open questions)

- _(none open — all shipped infra is documented above; product-level decisions like
  2FA enforcement policy and OAuth/SSO live in the project README roadmap)_