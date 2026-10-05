# Lean Monorepo

Template enxuto de monoprojeto com:

- **Backend** Python 3.12 + FastAPI + SQLAlchemy 2.x async + Alembic
- **Worker** [Procrastinate](https://procrastinate.readthedocs.io/) 3.10.0 (Postgres-only, mesma imagem da API)
- **Frontend** React 18 + TypeScript + Vite + Tailwind + React Router
- **Tipos ponta a ponta** via `openapi-typescript` (regenerados com `just web-types`)
- **2FA** opcional: TOTP (Google Authenticator) + passkey (WebAuthn/Touch ID)
- **Rate limit** em `/auth/login` e `/auth/register` (Postgres, sem Redis)
- **Cache, filas, sessões, rate limit** — tudo em Postgres (sem Redis)
- **Limpeza automática** via `pg_cron` (kv_cache, rate_limits, sessions, recovery codes)
- **Email transacional** SMTP (Mailpit em dev, Resend/SES/Postmark/Mailgun/Brevo em prod)
- **Observability** vendor-agnostic via OTLP (Grafana stack self-hosted) + Sentry opcional
- **E2E** com Playwright (smoke + jornada crítica)
- **CI** (backend lint/type/test, frontend lint/type/build, compose validate)
- **Banco único** Postgres (PostGIS, pgvector, ltree, pg_trgm, btree_gist, pgcrypto, uuid-ossp, citext)
- **Backup** automatizado para Cloudflare R2 (via `rclone`)

> Filosofia: **Postgres-only**. Cache, filas, grafos, geo, vetores, sessões — tudo no mesmo banco. Menos infra, menos ops, transações ACID cobrindo o app inteiro.

---

## Estrutura

```
.
├── apps/
│   ├── api/                  FastAPI + worker (Procrastinate) + migrations + CLI
│   │   ├── app/              código
│   │   │   ├── api/          endpoints v1 + deps + schemas
│   │   │   ├── core/         config, logging, security, cache, email, ratelimit,
│   │   │   │                 observability, totp, webauthn, middleware
│   │   │   ├── db/           SQLAlchemy (base, session, models)
│   │   │   ├── jobs/         app.py (Procrastinate) + runner.py (entrypoint) + tasks/
│   │   │   ├── cli.py        dump-openapi, seed, create-user, enqueue-job, db-status
│   │   │   └── main.py       FastAPI app
│   │   ├── migrations/       alembic (1 arquivo: 0001_initial_schema.py)
│   │   └── tests/            pytest (37 testes)
│   └── web/                  React SPA (Vite)
│       ├── e2e/              Playwright specs
│       ├── src/
│       │   ├── api/          client.ts, endpoints.ts, types.ts, schema.d.ts
│       │   ├── lib/          auth provider
│       │   ├── pages/        Login, Dashboard, Security, NotFound
│       │   └── App.tsx, main.tsx, index.css
│       └── dist/             (gerado em build; servido pelo FastAPI)
├── scripts/
│   ├── entrypoint.sh         decide api|worker, roda migrations
│   ├── backup.sh             pg_dump -> R2
│   ├── check-schema-sync.sh  pre-commit: diff schema.d.ts vs backend
│   ├── postgres-init/01-extensions.sql
│   ├── otel-collector.yaml   (profile observability)
│   ├── tempo.yaml
│   └── prometheus.yml
├── docs/architecture.md      ADRs
├── Dockerfile                multi-stage (Node build + Python runtime)
├── docker-compose.yml        postgres + mailpit (+ app profile: api+worker, + observability profile)
├── justfile                  atalhos de DX
├── .env.example              template de variáveis
└── .pre-commit-config.yaml   pre-commit-hooks + schema-sync
```

---

## Subir a stack (Docker, caminho feliz)

```bash
cp .env.example .env
# ajuste SECRET_KEY, POSTGRES_PASSWORD, etc.
just init          # build + up + wait
```

Endpoints:

- App: <http://localhost:8000>  (mesmo host serve SPA + API)
- API: <http://localhost:8000/api/v1>
- Docs: <http://localhost:8000/api/docs>
- Health: <http://localhost:8000/api/v1/healthz>
- Mailpit (dev): <http://localhost:8025>  (`just mail`)

Pra criar um admin e logar:

```bash
just cli seed      # imprime email + senha aleatória
```

## Dev local (Postgres em Docker, app no host)

Útil quando você quer editar o código com HMR sem rebuildar a imagem:

```bash
# 1) Postgres + Mailpit em Docker (app e worker ficam fora)
docker compose up -d postgres mailpit

# 2) API (terminal 1)
just api-install
just api-migrate
just api-run      # http://localhost:8000

# 3) Worker (terminal 2)
just worker-run

# 4) Front (terminal 3)
just web-install
just web-dev      # http://localhost:5173 (proxy /api -> :8000)
```

Pra rodar api+worker+web paralelos num comando só: `just dev`.

> `just` é o command runner — instale com `brew install just` (macOS) ou `cargo install just` (Linux).

---

## Postgres-only: como cada coisa vira uma tabela

| Necessidade                | Solução                                                                                          |
| -------------------------- | ------------------------------------------------------------------------------------------------ |
| **Cache**                  | Tabela `kv_cache` (UNLOGGED + `expires_at`) — mais rápido que Redis, sem infra extra             |
| **Filas / jobs**            | Procrastinate 3.10.0 (Postgres-only, heartbeat/stall built-in, DLQ opcional) — escala, ACID      |
| **Sessões de auth**        | Tabela `sessions` com token opaco + hash — revogação instantânea, sem Redis                      |
| **Rate limiting**          | Tabela `rate_limits` + janela fixa via `INSERT … ON CONFLICT DO UPDATE`                           |
| **Limpeza automática**     | Extensão `pg_cron` — 4 jobs rodando sozinhos (kv_cache, rate_limits, sessions, recovery codes)    |
| **Grafos / hierarquia**    | Extensão `ltree` + CTEs recursivas — paths, subárvores, ancestry                                 |
| **Geolocalização**         | Extensão `postgis` — pontos, polígonos, distâncias, índice GiST                                  |
| **Full-text / fuzzy**      | Extensões `pg_trgm` + `unaccent` — busca tolerante a typo e acentos                              |
| **Embeddings / RAG**       | Extensão `vector` (`pgvector`) — `vector(1536)` etc. com índice ivfflat/hnsw                     |
| **Schedules / cron**       | Extensão `pg_cron` (mesmo do cleanup)                                                             |
| **Lock distribuído**       | `pg_try_advisory_lock` + `pg_advisory_unlock`                                                    |

Quando algum caso *realmente* pede Redis (pub/sub com baixa latência, geofencing com milhões de updates/s), você sabe que é exceção — não o default.

---

## Filas no Postgres — Procrastinate

`apps/api/app/jobs/app.py` configura o [Procrastinate](https://procrastinate.readthedocs.io/) 3.10.0:

- **Async nativo** (psycopg3) — não bloqueia o event loop.
- **Heartbeat / stall recovery** automáticos — jobs travados são re-claimados pela lib.
- **Periodic tasks** built-in (`@app.periodic(cron="*/5 * * * *")`).
- **DLQ opcional** (`dead_letters`) — tarefas que falharam após `max_attempts`.
- **Schema oficial** vem direto da lib (nunca duplicar ~600 linhas de SQL); a migration 0001 aplica via `SchemaManager.apply_schema()`.

Pra criar uma task:

```python
# apps/api/app/jobs/tasks/minha_task.py
from app.jobs.app import app

@app.task(queue="default", name="minha.coisa", retry=True)
async def minha_task(tenant_id: str) -> None:
    # faça trabalho idempotente
    ...
```

Importe o módulo em `app/jobs/tasks/__init__.py` (uma vez, no startup). Procrastinate descobre as tasks via `import_paths=["app.jobs.tasks.email"]` em `app.py`.

A task `email.send` é o exemplo. Em dev → SMTP para o container `mailpit` (UI em <http://localhost:8025>). Em prod → qualquer SMTP-relay.

---

## 2FA — TOTP e Passkey (opcional, opt-in por usuário)

A tabela `users` tem colunas `totp_enabled`/`totp_secret_enc`. O usuário liga quando quiser.

**TOTP (Google Authenticator, 1Password, etc.):**
1. UI chama `/auth/2fa/totp/setup` → recebe `{secret, otpauth_uri}` (mostra QR)
2. UI chama `/auth/2fa/totp/confirm` com o primeiro código → TOTP ativo, recebe 10 recovery codes (mostrar 1x só)
3. Próximo login: senha OK → UI mostra campo de código → `/auth/2fa/verify` → cookie setado

**Passkey (Touch ID, Face ID, chave de segurança):**
1. UI chama `/auth/2fa/passkey/register/options` → `navigator.credentials.create()` → `register/verify`
2. Próximo login: botão "Usar passkey" → `navigator.credentials.get()` → `/auth/2fa/passkey/login/verify` → cookie setado

Recovery codes são aceitos no lugar do TOTP (caso o usuário perca o app).

---

## Auth

- Senha: **bcrypt** (custo 12, via lib `bcrypt` direto).
- Sessão: **token opaco** em cookie `HttpOnly`, `SameSite=Lax`, `Secure` em prod.
- O cookie armazena o token cru; o banco guarda `sha256(token)` em `sessions.token_hash` (índice unique).
- Logout = `DELETE FROM sessions WHERE token_hash = …` → revogação instantânea.
- Endpoints em `/api/v1/auth/{register,login,logout,me}`.

---

## Observability (opcional, vendor-agnostic)

App emite **OTLP** quando `OTEL_EXPORTER_OTLP_ENDPOINT` está setado. Sem env, é no-op.

```bash
# 1) Sobe a stack + Grafana/Tempo/Prometheus/OTel Collector
just up-obs

# 2) Configure .env:
#    OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317
#    SENTRY_DSN=https://...@sentry.io/...

# 3) Restart api/worker
just down && just up
```

URLs:
- Grafana: <http://localhost:3000> (admin/admin)
- Tempo API: <http://localhost:3200>
- Prometheus: <http://localhost:9090>

Sem Sentry self-hosted (pesado demais). Se precisar de error tracking, use Sentry SaaS via `SENTRY_DSN`.

---

## Email transacional

**SMTP-only.** Um caminho de código, qualquer provedor.

### Dev local (Mailpit)

```bash
just up                       # sobe Postgres + api + worker + mailpit
just mail                     # abre http://localhost:8025
```

Quando o worker processar `email.send`, o email aparece na UI do Mailpit. Zero credenciais, zero custo.

### Prod — qualquer provedor SMTP

| Provider | Host | Porta | TLS |
|---|---|---|---|
| Resend | `smtp.resend.com` | 465 | `SMTP_SSL=true` |
| AWS SES | `email-smtp.<region>.amazonaws.com` | 587 | `SMTP_STARTTLS=true` |
| Postmark | `smtp.postmarkapp.com` | 587 | `SMTP_STARTTLS=true` |
| Mailgun | `smtp.mailgun.org` | 587 | `SMTP_STARTTLS=true` |
| Brevo | `smtp-relay.brevo.com` | 587 | `SMTP_STARTTLS=true` |

Exemplo (Resend):
```bash
SMTP_HOST=smtp.resend.com
SMTP_PORT=465
SMTP_SSL=true
SMTP_USERNAME=resend
SMTP_PASSWORD=${RESEND_API_KEY}
EMAIL_FROM="App <noreply@example.com>"
```

Exemplo (SES):
```bash
SMTP_HOST=email-smtp.us-east-1.amazonaws.com
SMTP_PORT=587
SMTP_STARTTLS=true
SMTP_USERNAME=AKIAxxxxxx
SMTP_PASSWORD=<smtp-password>
EMAIL_FROM="App <noreply@example.com>"
```

### Staging/CI sem envio real

```bash
EMAIL_LOG_ONLY=true   # só loga, não envia
```

---

## Backup (R2)

```bash
just backup-now
# Cron: 30 3 * * *  /opt/lean-monorepo/scripts/backup.sh
```

`backup.sh`:
1. `pg_dump -Fc -Z 9` → arquivo local.
2. `rclone copyto` → `rclone:lean-monorepo-backups/db/<db>_<ts>.dump`.
3. `rclone delete --min-age 14d` → retenção.

Para credenciais, prefira `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` de **Scoped Token** do R2 (apenas bucket de backup).

---

## Tipos compartilhados (OpenAPI → TS)

O backend expõe o schema em `/api/openapi.json`. Para o front consumir esses tipos como TS:

```bash
just web-types
# ou, à mão:
cd apps/api && . .venv/bin/activate && python -m app.cli dump-openapi > openapi.json
cd apps/web && npm run gen:api    # openapi-typescript openapi.json → src/api/schema.d.ts
```

O fluxo:
1. `app.cli dump-openapi` importa o FastAPI `app` e imprime `app.openapi()` em JSON.
2. `openapi-typescript` gera `apps/web/src/api/schema.d.ts` (tipos de schemas + paths).
3. `src/api/types.ts` reexporta os types relevantes.
4. `src/api/endpoints.ts` declara helpers tipados por endpoint.

Sempre que você **adicionar/alterar** um endpoint ou Pydantic model, rode `just web-types`. O `pre-commit` recusa o commit se `schema.d.ts` estiver desatualizado (`just check-schema` pra checar manualmente).

---

## CI

`.github/workflows/ci.yml`:
- **backend**: ruff + pyright + pytest
- **frontend**: tsc + lint (Biome) + build
- **compose**: valida que `docker-compose.yml` continua válido

Local: `just ci` roda os mesmos checks.

---

## Convenções

- **Lint/typecheck**:
  - Backend: `ruff` (linter + formatter) + `pyright` (type checker). `just lint`, `just typecheck`.
  - Frontend: `biome` (linter + formatter + import sort, único tool). `just web-lint`, `just web-lint-fix`.
  - Tudo roda em `just ci` (mesmo do GitHub Actions).
- **Editor (VSCode)**: `.vscode/` tem settings compartilhadas (Biome como formatter default, Ruff no Python, Pyright, Tailwind, etc.), launch configs (API, worker, pytest) e tasks (`just init`, `just dev`, `just ci`, etc.). Abre o workspace e o VSCode oferece instalar as extensões recomendadas.
- **Migrações**: `just api-revision "add foo"` → revisar antes de commitar.
- **Segredos**: NUNCA comitar `.env`. Em prod, monte via secret manager do orquestrador.
- **Logs**: `structlog` JSON em prod, console em dev (stderr pra não poluir stdout).
- **Tests**: `just test` roda a suite de 37 testes. Tudo que não precisa de DB.
- **E2E**: `just e2e` (assume stack up) ou `just e2e-full` (sobe stack, roda, derruba).

---

## Decisões de arquitetura (ADRs)

`docs/architecture.md` lista em detalhe cada decisão: Postgres-only, Procrastinate, bcrypt direto (não passlib), OpenAPI pipeline, SPA mesma origem, exception handler, CLI, tests, multi-region seams, observability vendor-agnostic, SQLAlchemy Core para queries (ORM só para schema), etc.

---

## Roadmap honesto

Tudo o que era **infraestrutura de template** está feito. O que sobra é decisão de produto:

- 2FA enforcement policy (sempre? opt-in? por org?)
- OAuth/SSO (Google, GitHub, etc.)
- Frontend com React Hook Form unit tests (vitest + RTL)
- OIDC
- Multi-region (ADR-010 lista onde mexer)
- Migration de autenticação para JWT (se necessário para SPAs separados)