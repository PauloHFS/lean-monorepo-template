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

## AD-017 · Passkeys na lib `webauthn` (duo-labs) com credential JSON padrão

**Status**: current.

**Context**: o backend pinava `py_webauthn==0.0.6` — o fork `as207960/python-webauthn`
(MIT, últimos releases 0.0.1–0.0.6, projeto abandonado). Mas o código foi escrito
contra a API moderna: usava `result.credential_id` e `result.new_sign_count`, que
**não existem** na 0.0.6 (lá são `attestation...credential_id` e `sign_count`) →
`AttributeError` em runtime nos dois fluxos de passkey. Pior: em 0.0.6
`result.public_key` é um objeto `cryptography`, não bytes → o insert em
`user_passkeys.public_key` (BYTEA) e o `bytes(pk["public_key"])` no login também
estavam errados. A linha legada ainda exigia `certvalidator`→`oscrypto`, e por causa
de um regex de versão do oscrypto 1.3.0 o repo fixava um tarball do GitHub
(hack que quebrava no Linux).

**Decision**:
- Trocar para `webauthn==3.0.1` (`duo-labs/py_webauthn`, BSD-3, Python >=3.10,
  `py.typed`). Mesmo import name (`webauthn`), mesmas deps sem
  `certvalidator`/`oscrypto` → o tarball do `oscrypto` sai do `pyproject.toml`.
- Contrato: o browser envia o **credential JSON padrão** (`id`, `rawId`, `type`,
  `response.clientDataJSON` e `response.attestationObject`/`authenticatorData`/`signature`,
  tudo em base64url **sem padding** — `btoa` puro gera `+/=` e a lib rejeita) em vez
  de 3-4 campos base64 separados. As options voltam como dict camelCase
  (`options_to_json_dict`).
- Challenge: gerado pela lib, **guardado no pending** (TTL 300s, consumo único) e
  comparado com o enviado no verify — o cliente não é fonte de verdade do challenge.
- Lookup: a passkey é buscada e atualizada **por `credential_id`** (não mais
  `SELECT ... WHERE user_id LIMIT 1` com `UPDATE` por user_id).
- `public_key` passa a ser o COSE cru de `credential_public_key` → continua BYTEA,
  **sem migration**.

**Consequences**:
- A lib mantida tem `py.typed`: os casts/`import_module` do adapter saem e os
  warnings de stub desaparecem.
- Os 4 endpoints de passkey mudam de contrato (schemas Pydantic + payload do
  frontend) → `apps/web/src/api/schema.d.ts` regenerado.
- `expected_origin` passa a ser `settings.web_origin` (igualdade exata) e `rp_id` o
  hostname sem porta — checks independentes, como manda a spec.
- Limite conhecido: attestation/assertion reais não são exercitados em teste
  automatizado (não há authenticator no CI) — o round-trip precisa de validação
  manual no browser.

---

## AD-018 · Contratos tipados ponta a ponta (OpenAPI → TypeScript) e enfileiramento na fila

**Status**: current.

**Context**: a geração de tipos já existia (`just web-types` → `src/api/schema.d.ts`)
e o CI já comparava bytes, mas o **conteúdo** do schema não era verificado: um
`response_model` ausente ou um `dict[str, Any]` produz `Record<string, never>` no
TypeScript e o front seguia consumindo um contrato inexistente. Em quatro rotas isso
acontecia de fato (`POST /auth/login`, `/2fa/verify`, `/passkey/login/verify` e os
options/credentials de passkey). O front ainda redeclarava esses shapes à mão e
castava a resposta (`response as UserOut`), o que zerava `user.email` em runtime.
Em paralelo, `POST /users/enqueue-email` gravava na tabela `background_jobs`, que é
**legada e não é consumida por ninguém** — o worker Procrastinate lê a fila própria,
então o e-mail nunca era enviado.

**Decision**:
- Toda resposta de rota declara um **modelo Pydantic explícito**; `dict[str, Any]`
  como `response_model` está proibido (`Record<string, never>`). `LoginOut` e `OkOut`
  entram em uso; `response_model_exclude_unset=True` no login para o shape não
  ganhar `pending_token: null`/`methods: []`.
- `scripts/check-schema-sync.sh` ganha um **gate semântico**: além do diff de bytes,
  falha se alguma resposta de rota virar `Record<string, never>`/`unknown`.
- O front consome `components["schemas"][...]` (reexportado em `src/api/types.ts`);
  tipos manuais de resposta saem.
- `POST /users/enqueue-email` passa a chamar `send_email.defer_async(...)` — a mesma
  task do worker e do CLI — e `job_id` vira o id do Procrastinate (inteiro).
  `background_jobs` deixa de receber enfileiramentos.

**Consequences**:
- `schema.d.ts` regenerado (`+168/−15`) e o contrato do login/verify passa a ter
  `properties` de verdade; `apps/api/tests/test_contracts.py` fixa esse contrato.
- As options WebAuthn são JSON base64url: o front precisa convertê-las para
  `BufferSource` (`src/lib/webauthn.ts`) — o `navigator.credentials` exige bytes e
  o fluxo de passkey estava quebrado no browser.
- O `job_id` muda de `string` para `number` no TypeScript (quebra compatível: o
  front só exibe o valor).
- `background_jobs` continua no schema (não há migration) mas fica inerte.

---

## AD-019 · Rigor de lint estrito (Biome) e E2E com mock de rede

**Status**: current.

**Context**: o lint do front rodava `biome check` com as regras relevantes em
`warn` — ou seja, nada bloqueava. `noExplicitAny` só avisava. O `files.include`
(`["src/**","e2e/**","*.{ts,tsx,js,jsx,json}"]`) **não casava arquivos da raiz** no
Biome 1.9.4: `vite.config.ts`, `playwright.config.ts`, `tailwind.config.js` e
`postcss.config.js` escapavam do lint (medido: "Checked 0 files"). No lado E2E havia
só 2 specs, ambos exigindo API+DB (o CI não rodava E2E) e o `e2e-full` apontava para
`:5173`, enquanto o compose serve a SPA pela API em `:8000`.

**Decision**:
- `npm run lint` passa a ser `biome check --error-on-warnings` e as regras
  relevantes viram `error` (`noExplicitAny`, `noConsoleLog`, `useImportType`,
  `useExhaustiveDependencies`, `useAwait`, `noUnusedImports`, `noUnusedVariables`,
  `noUnusedFunctionParameters`, `noUndeclaredVariables`, `noNonNullAssertion`,
  `noParameterAssign`, `noUselessElse`). `useNamingConvention` fica `off`: o
  snake_case vem do contrato da API.
- `files.include` vira `["**"]` (o glob da raiz não funciona no 1.9.4) e o schema
  gerado segue ignorado.
- Cenários de falha de autenticação e fluxos assíncronos passam a ser specs com
  `page.route` (mock de rede) em `apps/web/e2e/`: rodam sem API/DB e é isso que o CI
  executa (`just e2e-mock`). Spec que exige backend real **pula** quando ele não
  está disponível.
- `playwright.config.ts` passa a ler `E2E_BASE_URL` e a subir o Vite sozinho quando
  o alvo é a porta do Vite; `just e2e-full` aponta para `:8000` e sempre derruba o
  compose (mesmo em falha).

**Consequences**:
- O job `e2e` do CI roda só os specs mockados (sem Postgres, sem Docker).
- O lint do front passou a pegar arquivos que escapavam; corrigir isso exigiu
  `import type { FormEvent }` em `Security.tsx` (o `React.FormEvent` era o namespace
  UMD, sem import) e a reformatação dos 3 configs da raiz.
- `noDefaultExport`, `useBlockStatements` e `useSortedClasses` ficaram de fora:
  são churn de estilo, não rigor.

---

## AD-020 · Validação de entrada na fronteira (constraints nos schemas)

**Status**: current.

**Context**: os schemas de entrada aceitavam quase tudo. `RegisterIn.password`
tinha `min_length=8` hardcoded (duplicando `settings.password_min_length`),
`LoginIn.password` não tinha limite nenhum, `TotpConfirmIn.code` aceitaria "abc",
`TwoFactorVerifyIn.code` não tinha limites (e precisa aceitar TOTP **ou**
recovery code), `pending_token` não tinha limites, `EnqueueEmailIn.subject/body`
não tinham teto e `list_users` aceitava `limit`/`offset` negativos ou absurdos.
O front já validava senha (mín. 8) e código (mín. 6) no Zod — ou seja, o backend
era a fronteira **mais permissiva**, e um cliente que não passasse pelo front
passaria.

**Decision**:
- Todo schema de entrada declara suas constraints em Pydantic v2
  (`Field(min_length=..., max_length=..., pattern=...)`), e paginação usa
  `Query(ge=..., le=...)`.
- `RegisterIn.password` = `Field(min_length=settings.password_min_length,
  max_length=72)`: a fonte do mínimo é o `Settings` (não um literal) e o teto de
  72 existe porque o bcrypt trunca em 72 **bytes**.
- `LoginIn.password` fica **sem** `max_length`. O truncamento do bcrypt acontece
  nos dois lados, então uma senha de 100 chars gravada antes desta mudança
  continua verificando; limitar o login expulsaria do próprio login usuários
  legados. Endurecer a entrada viraria um outage.
- `TwoFactorVerifyIn.code` aceita 6..64 chars (TOTP de 6 dígitos **ou** recovery
  code de 10 chars) e **não** recebe pattern de 6 dígitos. O pattern `^\d{6}$`
  fica só em `TotpConfirmIn.code`, que é a confirmação de setup do TOTP.
- `pending_token` (16..128), `challenge` de passkey (8..1024), `subject` (≤200),
  `body` (≤100 000), `limit` (1..100) e `offset` (≥0).

**Consequences**:
- Entrada inválida passa a responder **422** em vez de 401. O front já validava
  no cliente, então o fluxo normal não muda.
- As constraints **não** aparecem no `schema.d.ts`: o openapi-typescript descarta
  `minLength`/`maxLength`/`pattern` de campos escalares. Elas ficam no
  `apps/api/openapi.json` e são aplicadas no servidor — o gate de contrato
  (`just check-schema`) continua válido.
- `apps/api/tests/test_validation.py` (20 testes) fixa os limites exatos e
  documenta a armadilha do login; `tests/test_properties_validators.py` passou a
  exigir rejeição.
- `password_min_length` acima de 72 é **configuração impossível**, e por isso
  falha no boot: `Settings` valida `1 <= password_min_length <= 72` e levanta
  `ValidationError` citando `PASSWORD_MIN_LENGTH` e o teto de 72 bytes do
  bcrypt. Sem essa validação, `Field(min_length>72, max_length=72)` só
  apareceria como erro de schema na construção do modelo. O valor nunca é
  capado em silêncio: política impossível de cumprir é erro de config, e erro de
  config deve falhar alto.
- O limite de 72 é contado em CARACTERES, enquanto o truncamento do bcrypt é em
  BYTES: senhas multibyte ainda podem truncar (comportamento pré-existente).

---

## AD-021 · Imagem enxuta non-root, saúde em camadas, boot resiliência e backup com prova

**Status**: current.

**Context**: a imagem final carregava o toolchain de compilação (`build-essential`,
`libpq-dev`, `uv`) e rodava como root; `COPY apps/api` levava `tests/` e
`.hypothesis/`; o `curl` existia só para o healthcheck. O healthcheck do
container chamava `/api/v1/healthz`, que checa o banco — uma queda do Postgres
marcava o container unhealthy e reiniciava um processo saudável; o próprio
endpoint prometia 503 no docstring e devolvia 500, com `degraded`/`db=False`
inalcançável. O boot tinha duas falhas: o loop de espera do Postgres terminava
**sem erro** após 60 tentativas (o Alembic mascarava a causa) e `api` e `worker`
rodavam `alembic upgrade head` ao mesmo tempo. O backup existia (`pg_dump` → R2,
retenção de 14 dias), mas a sanidade era só "arquivo não vazio" — um dump
truncado passava — e **não existia** `restore.sh` nem teste de restauração.

**Decision**:
- **Imagem**: 3 stages (`build-web` → `build-api` → `runtime`) com cache mounts de
  npm e uv (BuildKit); toolchain e uv ficam só no stage de build; a imagem final
  copia apenas `/opt/venv` e roda como `app` (uid 10001, sem shell). O `curl`
  sai: o healthcheck usa o `urllib` do próprio venv. A base do runtime é a
  **mesma** do build porque o venv referencia `/usr/local/bin/python3.12` por
  symlink absoluto — trocar a base quebra o venv.
- **Saúde em camadas**: `/api/v1/livez` (liveness, não toca o banco) e
  `/api/v1/healthz` (readiness, timeout de 2s, 503 + `degraded`/`db=False`
  reais). O HEALTHCHECK do container usa **livez**: é o liveness que decide
  restart, readiness é para proxy/LB. `worker` e `migrate` desligam o healthcheck
  da imagem (não servem HTTP).
- **Boot**: o entrypoint ganha o papel `migrate` (one-shot); api e worker passam a
  depender de `service_completed_successfully` — sem corrida de migrations. A
  espera do Postgres usa `pg_isready` (fallback TCP) e **termina com exit 1** ao
  estourar. `API_INTERNAL_PORT` é a porta interna do container; `API_PORT` é a
  porta publicada no host. O worker ganhou retry com backoff na abertura do app
  (`tenacity`, que já era dependência e não era usado).
- **Backup com prova**: `pg_restore --list` valida o dump (não só o tamanho),
  sidecar `.sha256`, `flock` contra execuções sobrepostas (com degradação no
  macOS, que não tem `flock`), modo local quando não há bucket (mantém o dump) e
  `scripts/restore.sh` + `scripts/test-restore.sh` — o teste cria bancos de
  descarte, faz backup→restore e confere count, `to_regclass`, md5 do conteúdo,
  índice, PK e sequência. O CI ganhou o job `restore-test` com Postgres como
  service container.

**Consequences**:
- O enunciado original da Fase 4 citava **Redis** e um **"daemon Go"**: não
  existem neste repositório (AD-001 é Postgres-only; o daemon real é `uvicorn` +
  o worker Procrastinate, no mesmo binário). O escopo foi adaptado ao stack real.
- A imagem final passa de ~500–800 MB (estimativa) para ~250–450 MB — o número
  real só sai com `docker build`, que não foi executado (sem daemon).
- `docker build`, o HEALTHCHECK real, o drain de 30s do worker e o job
  `restore-test` **não foram validados localmente**: dependem de daemon. O bind
  mount `:ro` com uid 10001 funciona no Docker Desktop; em Linux puro o host
  precisa permitir leitura pelo uid do container.
- O serviço `migrate` roda `alembic upgrade head` a cada `up` — idempotente, mas
  significa que ele sempre roda antes da API.
- A base da imagem ainda não é pinada por digest (exige consultar o registry).

---

## AD-022 · Biome 2.x e react-router 7 (front)

**Status**: current.

**Context**: o front estava no Biome 1.9.4 — a última release 1.x, sem correção
de bug ou segurança desde outubro de 2024 (o `latest` já era o 2.6.3). O
`react-router-dom` 6.30.6 carregava duas CVEs sem patch na linha 6.x
(GHSA-wrjc-x8rr-h8h6, open redirect via `\` em `<Link>`/`useNavigate`,
CVE-2026-53669; e GHSA-337j-9hxr-rhxg, constructor injection no hydration SSR,
CVE-2026-53666): o `npm audit --omit=dev` acusava 2 moderate e o fix exigia v7.

**Decision**:
- **Biome 2.6.3**: `files.include`/`ignore` → `files.includes` (negação `!`),
  `linter.rules.recommended` → `preset: "recommended"`,
  `organizeImports` → `assist.actions.source.organizeImports: "on"`.
  `noConsoleLog` não existe mais: a regra é `noConsole`, que bloqueia todo
  `console.*` por padrão, e o config lista em `options.allow` todos os métodos
  **exceto** `log` — o mapeamento fiel do gate antigo. `vcs.root: "../.."` é
  obrigatório (a 2.x não sobe atrás do `.gitignore` e aborta sem ele) e
  `public/` fica fora do lint (a 2.x parseia SVG e `a11y/noSvgWithoutTitle`
  disparava no favicon). Tailwind 3 exige `css.parser.tailwindDirectives: true` e
  `noUnknownAtRules: "off"`.
- **react-router 7.18.4** no lugar do `react-router-dom` (que sai do
  `package.json`): o pacote `react-router` exige Node ≥20 e React ≥18 — casa com
  o repo. Declarative Mode (`BrowserRouter`/`Routes`/`Route`) continua suportado,
  então **não** precisa de `@react-router/dev` nem de config de Framework Mode; os
  tipos vêm embutidos (sem `@types/react-router`). A única mudança de código são
  5 imports: `react-router-dom` → `react-router`.

**Consequences**:
- O `biome migrate --write` **não** serve sozinho: ele gera
  `noConsole.allow: ["log"]` (inverte a semântica e silencia o gate de
  `console.log`) e não seta `css.parser.tailwindDirectives` (5 parse errors em
  `@apply`). O config foi escrito à mão e validado com
  `biome check --error-on-warnings`.
- O `npm audit --omit=dev --audit-level=high` (gate de produção do CI) passou a dar
  **0 vulnerabilidades**: as 2 moderate do react-router 6 sumiram. As 7 restantes
  do audit completo são todas em devDependencies (vite/esbuild/tailwindcss/
  postcss) e estão fora do gate.
- A 2.x reordena imports (assist) e o `lint:fix` passou a aplicar essa
  reordenação: 4 arquivos de código tiveram diff mecânico, zero mudança de
  comportamento.
- `noFloatingPromises`/`noMisusedPromises` são **nursery** na 2.6.3 (não vêm com
  `recommended`) e `useSortedClasses` foi renomeada (`useTailwindSortedClasses`,
  exige Tailwind 4): nenhuma entra no gate hoje.
- `useNavigate()` passa a retornar uma Promise; no código atual o retorno é
  ignorado, então nada quebra — mas quem chamar `.then()` precisa de `void`/await
  para não gerar promise flutuante.

---

## AD-023 · Vite 8 (Rolldown) e Node 24 no front

**Status**: current.

**Context**: o Vite 5 carregava o advisory GHSA-4w7w-66w2-5vf9 (path traversal em
`.map` dos deps otimizados, dev server) — **todas as 5.x são afetadas e a linha 5
não recebeu patch** (EOL): o fix existe só a partir de 6.4.2 / 7.3.2 / 8.0.5. O
Node usado no build e no CI era o 20, **EOL desde 2026-04-30**. O `npm audit
--omit=dev --audit-level=high` (gate de produção) continuava em 0, então a dívida
era de dev server e de runtime sem patch, não de bundle.

**Decision**:
- **Vite 8.3.5** (Rolldown + Oxc no lugar de Rollup + esbuild; CSS minificado por
  Lightning CSS) e **`@vitejs/plugin-react` 6.1.2** — o 4.x não aceita Vite 8 no
  peer range. O `vite.config.ts` **não mudou**: o repo não usa `define`,
  `esbuild`, `rollupOptions`, `base` nem `assetsDir`, `server.proxy` não mudou
  entre 6/7/8 e `build.target: 'es2022'` está pinado (imune à mudança de default).
  Tailwind 3 continua compatível (é plugin PostCSS, não plugin Vite).
- **Node 24** (Active LTS) no Dockerfile (`node:24-alpine`) e nos 3 jobs do CI que
  rodam Node (`frontend`, `e2e`, `schema-sync`). O Node 26 ainda é "Current" e
  entra em LTS em 2026-10-28 — não foi pinado. O Vite 8 exige
  `^20.19.0 || >=22.12.0`.

**Consequences**:
- O `npm audit --omit=dev --audit-level=high` continua em **0** e o advisory do Vite
  5 saiu do alcance; o audit completo caiu de 5 para 3 moderate, **todas em
  devDependencies** e todas na cadeia do Tailwind 3
  (`postcss-selector-parser` → `postcss-nested` → `tailwindcss`): o fix exige
  Tailwind 4 (breaking), fora do escopo.
- O build ficou mais rápido (220 → 155 módulos, 4,78 s → 916 ms) e o bundle
  encolheu (JS 336,35 → 331,14 kB; CSS 11,83 → 11,67 kB); nenhum chunk novo.
- O risco de interop CJS unificado do Vite 8 (`import QRCode from 'qrcode'` em
  `Security.tsx`) **não se materializou**: build sem warning e o `default` import
  foi validado em Chromium headless. `legacy.inconsistentCjsInterop` não é
  necessário.
- Node <20.19/22.12 deixa de servir: `apps/web/package.json` não declara
  `engines`, então o erro aparece na install, não antes.
- A versão do Node aparece em três lugares (Dockerfile + 3 jobs do CI) — sem
  fonte única dentro do repo (a tag da imagem Docker é por definição externa).

---

## AD-024 · Tailwind 4 (CSS-first) e React 19 no front

**Status**: current.

**Context**: o front estava no Tailwind 3.4.17 e no React 18.3.1. O Tailwind 3
carregava 3 advisories moderate (cadeia `postcss-selector-parser` →
`postcss-nested` → `tailwindcss`) cujo único fix é o Tailwind 4 — breaking, e
portanto nunca ia entrar num bump automático. O React 18 seguia na série
mantida, mas o 19 já era o `latest` e nenhuma dependência do repo o bloqueava.

**Decision**:
- **Tailwind 4.3.3 no modo CSS-first**: o plugin `@tailwindcss/vite` entra no
  `vite.config.ts` e `tailwind.config.js` e `postcss.config.js` são **deletados**
  (o `postcss` e o `autoprefixer` saem do `package.json`: no v4 o import e o
  prefixo de vendor são do próprio Tailwind). O tema sai do JS para o CSS
  (`@theme` com `--color-brand-*` e `--font-sans`) e as 5 classes do design
  system (`.btn`, `.btn-primary`, `.btn-ghost`, `.input`, `.card`) viram
  `@utility` — no v4 `@apply` de classe **customizada** é erro fatal, e
  `@apply` de utility core dentro de `@layer components` continua funcionando.
- **React 19.3.1** (+ `@types/react` 19.3.0, `@types/react-dom` 19.3.0). O repo
  não usa `useRef`, `forwardRef`, `React.FC`, `JSX.Element` global, `useReducer`
  com genérico nem `defaultProps` — que são os breaks reais do 19.
- Bumps menores no mesmo passo: `react-hook-form` 7.91.0, `@hookform/resolvers`
  6.0.0 (o breaking é só no resolver de Effect; usamos `zodResolver`) e
  `@playwright/test` 1.64.1.
- **Ficam de fora, de propósito**: `typescript` (5.9.3 — o 7.0.2 é o port nativo
  em Go sem compiler API e o 6.x muda defaults que exigem revisão do
  `tsconfig`) e `react-router` (7.18.4 — o 8.5.0 saiu há dias e exige React
  ≥19.2.7; a série 7 ainda tem peer React ≥18).

**Consequences**:
- O `npm audit` completo ficou em **0 vulnerabilidades** (as 3 moderate do
  Tailwind 3 sumiram) e o gate de produção segue em 0.
- Paridade visual exige dois ajustes: no v4 `shadow-sm` é o antigo `shadow` (o
  antigo `shadow-sm` virou `shadow-xs`) e `outline-none` agora remove o outline
  de verdade (o antigo virou `outline-hidden`). Ambos foram aplicados nas
  `@utility`.
- O CSS grew (11,67 → 16,20 kB) porque o v4 emite o tema inteiro como custom
  properties; o JS cresceu com o React 19 (331,14 → 413,36 kB; gzip 106,64 →
  130,40 kB).
- O `package.json` ganhou um `overrides` mínimo
  (`{"@hookform/resolvers": {"effect": "4.0.0"}}`): sem ele o npm 11 auto-resolve
  a cadeia opcional `@typeschema/*`/`@effect/schema`, que exige Effect 3.x, e a
  install limpa quebra com `ERESOLVE`. A alternativa seria `--legacy-peer-deps`
  em toda install.
- `useTailwindSortedClasses` (Biome 2.x, nursery) **não** foi ligada: ela passa a
  entender a semântica do v4, mas gera churn de reordenação de classes nos pages.
- O Biome 2.6.3 parseia `@theme`/`@utility` sem config extra
  (`css.parser.tailwindDirectives: true` continua no `biome.json`).

---

## AD-025 · Versão do Node com fonte única (`.node-version`) e `uv` 0.13

**Status**: current.

**Context**: a versão do Node aparecia em três lugares (a tag `node:24-alpine`
do Dockerfile e o `node-version` de 3 jobs do CI) e nenhuma era a fonte de
verdade — trocar o Node exigia três edições e nenhuma detectava drift. O `mise`
existia com `node = "24"` dentro de `[tools]`, o que criava uma quarta cópia. O
`uv` pinado no Dockerfile estava na 0.10.10 com a 0.13.5 já publicada.

**Decision**:
- **`.node-version` (24) é a fonte única.** O `mise.toml` não duplica a versão:
  ele só habilita a leitura do arquivo idiomático
  (`[settings] idiomatic_version_file_enable_tools = ["node"]`) — sem isso o
  mise 2026.5.9 **ignora** o `.node-version`. O CI usa
  `node-version-file: .node-version` nos 3 jobs e o Dockerfile passa
  `NODE_VERSION` como build-arg (`ARG NODE_VERSION=24` é só o fallback).
- Um **guard de drift** no CI compara o `.node-version` com o default do `ARG`
  no Dockerfile e falha se divergirem.
- `apps/web/package.json` declara `engines.node: ">=24"` e `apps/web/.npmrc`
  liga `engine-strict=true`: um dev com Node antigo recebe `EBADENGINE` na
  install, não um stack trace no dev server.
- `uv` 0.13.5 no Dockerfile (`ghcr.io/astral-sh/uv:0.13.5`) e `uv = "0.13"` no
  `mise.toml`.

**Consequences**:
- Trocar a versão do Node é uma edição em um arquivo; mise, Docker e CI leem
  dele. O `ARG NODE_VERSION` continua no repositório (a tag da imagem Docker é
  externa por definição), mas o guard impede que ele vire uma cópia silenciosa.
- `engine-strict` derruba a install se **qualquer** dependência declarar `engines`
  incompatível — hoje nenhuma declara.
- O mise 2026.5.9 não aceita `node = "node:.node-version"` nem `"file:..."`: o
  caminho do request syntax é o prefixo `path:`, que **não** ativa o binário.
  A solução é o setting de version file idiomático.
- uv 0.13.x muda o default do Python para 3.15 quando nenhum é pedido — não
  afeta este projeto, que fixa 3.12 (`.python-version` + `requires-python`).

---

## AD-026 · Dependências do backend atualizadas (bcrypt 5, FastAPI 0.162, SQLAlchemy 2.0.55)

**Status**: current.

**Context**: o backend estava 2 a 6 versões atrás em 18 pacotes: FastAPI 0.142.2
(0.162.0 no `latest`), Pydantic 2.10.3 (2.14.1), SQLAlchemy 2.0.36 (2.0.55 na
série 2.0; 2.1.6 na série 2.1), Alembic 1.14.0 (1.20.1), bcrypt 4.2.1 (5.0.0),
uvicorn 0.32.1 (0.54.0), structlog 24.4.0 (26.1.0), sentry-sdk 2.19.2 (2.73.0),
ruff 0.8.4 (0.17.2), pytest 9.0.3 (9.1.1), bandit 1.8.6 (1.9.4). Duas
dependências estavam **declaradas e sem uso**: `python-multipart` e
`itsdangerous` (esta última é transitiva do Starlette).

**Decision**:
- Subir as 18 versões no `pyproject.toml` (pins exatos) e regerar o `uv.lock`
  (92 → 90 pacotes: 18 upgrades, 2 remoções).
- **Remover `python-multipart` e `itsdangerous`**: nenhum `Form`/`File`/
  `UploadFile` no app (a sessão é um token opaco, não um cookie assinado) e a
  `itsdangerous` chega pelo Starlette.
- **SQLAlchemy 2.0.55, não 2.1.6**: o `opentelemetry-instrumentation-sqlalchemy`
  declara `sqlalchemy<2.1.0` e os autores do instrumentor não testam a série
  2.1 — e o repo instrumenta o engine (AD-016). A série 2.0.x ainda é mantida.
- **Python continua 3.12** (EOL só em out/2028): trocar de interpreter exige
  reescrever `requires-python`, `.python-version`, `ruff.target-version`,
  `pyrightconfig.json` e **os dois** `FROM` do Dockerfile (o venv referencia o
  interpretador por symlink absoluto) — mudança própria, não um bump.
- Alembic 1.16 trocou `version_path_separator` por `path_separator`: o
  `alembic.ini` foi atualizado para não emitir warning.

**Consequences**:
- **bcrypt 5.0.0 agora rejeita senhas acima de 72 bytes** (`ValueError`) em vez
  de truncar em silêncio. O repo **já truncava** em 72 bytes antes de chamar a
  lib (`core/security.py`), então hash e verificação continuam consistentes —
  o que muda é o texto: "o repo trunca; o bcrypt 5.x rejeita acima de 72 bytes".
  Um `hash_password` sem truncamento passaria a estourar `ValueError`.
- O `OpenAPI` gerado ficou **byte-idêntico** (33.514 bytes antes e depois): o
  Pydantic ≥2.11 passou a emitir `additionalProperties: true` para
  `dict[str, Any]`, mas nenhum `response_model` do repo usa `dict` — todos são
  models explícitos (AD-018). `apps/web/src/api/schema.d.ts` não mudou.
- O ruff 0.17.2 promoveu `PLR0917` (too many positional arguments) de preview
  para estável: `app/jobs/tasks/email.py` (6 posicionais: `ctx` + payload da
  fila) ganhou um `per-file-ignore` explícito.
- O pyotp 2.10 tipa `provisioning_uri(**kwargs)` sem anotação → `Unknown` no
  Pyright strict: o `app/core/totp.py` ganhou um
  `# pyright: ignore[reportUnknownMemberType]` na chamada (o `cast` não resolve,
  vira `reportUnnecessaryCast`).
- `pip-audit` continua em "No known vulnerabilities found" e o `uv lock --check`
  passa. A auditoria de produção do front segue em 0.

---

## Future ADs (open questions)

- _(none open — all shipped infra is documented above; product-level decisions like
  2FA enforcement policy and OAuth/SSO live in the project README roadmap)_