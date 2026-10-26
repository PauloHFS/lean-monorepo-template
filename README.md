# Lean Monorepo

Template enxuto de monoprojeto com:

- **Backend** Python 3.13 + FastAPI 0.162 + SQLAlchemy 2.0 async + Alembic 1.20
- **Worker** [Procrastinate](https://procrastinate.readthedocs.io/) 3.10.0 (Postgres-only, mesma imagem da API)
- **Frontend** React 19 + TypeScript + Vite 8 + Tailwind 4 + React Router 8
- **Tipos ponta a ponta** via `openapi-typescript` (regenerados com `just web-types`)
- **2FA** opcional: TOTP (Google Authenticator) + passkey (WebAuthn/Touch ID)
- **Rate limit** por IP e por conta em `/auth/login` e `/auth/register`, com limites próprios nos endpoints de 2FA (Postgres, sem Redis)
- **Cache, filas, sessões, rate limit** — tudo em Postgres (sem Redis)
- **Limpeza automática** via `pg_cron` opcional (kv_cache, rate_limits, job_rate_limits, dead_letters, recovery codes, sessions)
- **Email transacional** SMTP (Mailpit em dev, Resend/SES/Postmark/Mailgun/Brevo em prod)
- **Observability** vendor-agnostic via OTLP (Grafana stack self-hosted) + Sentry opcional
- **E2E** com Playwright (smoke + jornada crítica)
- **CI + entrega** (backend lint/type/test, frontend lint/type/build, SAST, auditorias, E2E mock, SBOM/assinatura no deploy)
- **Banco único** PostgreSQL 18 (`postgres:18-alpine`): `citext` é a única extensão exigida pelo schema (criada pela migration); as contrib (`pg_trgm`, `unaccent`, `ltree`, `btree_gist`, `pgcrypto`) vêm na imagem oficial, e extras como PostGIS/pgvector/pg_cron são **opt-in por projeto** (provider ou imagem própria)
- **Backup** automatizado para Cloudflare R2 (via `rclone`), com dump `0600`, cifra opcional e retenção local

> Filosofia: **Postgres-only**. Cache, filas, sessões e rate limit — tudo no mesmo banco. Geo e vetores são possíveis com extensão opt-in, mas não são o default. Menos infra, menos ops, transações ACID cobrindo o app inteiro.

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
│   │   │   ├── cli.py        dump-openapi, seed, create-user, enqueue-job,
│   │   │   │                 dead-letters (list/retry/discard), db-status
│   │   │   └── main.py       FastAPI app
│   │   ├── migrations/       alembic (1 arquivo: 0001_initial_schema.py)
│   │   └── tests/            pytest (169 testes)
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
├── docker-compose.yml        postgres + migrate + api + worker (dev: mailpit · observability)
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

`env_file: .env` é obrigatório em `migrate`, `api` e `worker`. Em clone fresco, `just validate-compose` (e o job `compose` do CI) materializam um `.env` temporário a partir do `.env.example`; para subir a stack, faça o `cp` acima e preencha os segredos.

Endpoints:

- App: <http://localhost:8000>  (mesmo host serve SPA + API)
- API: <http://localhost:8000/api/v1>
- Docs: <http://localhost:8000/api/docs>
- Health: <http://localhost:8000/api/v1/healthz> (readiness) · <http://localhost:8000/api/v1/livez> (liveness)
- Mailpit (profile `dev`): <http://localhost:8025>  (`docker compose --profile dev up -d mailpit` · `just mail`)

Pra criar um admin e logar:

```bash
docker compose exec api python -m app.cli seed   # imprime email + senha aleatória
```

Para um admin com senha conhecida (útil em E2E/local):

```bash
docker compose exec api python -m app.cli create-user admin@example.com minha-senha "Admin" --superuser
```

`create-user` é idempotente: se o e-mail já existe, atualiza a senha e garante o papel —
`--superuser` promove, mas nunca rebaixa um admin existente.

## Dev local (Postgres em Docker, app no host)

Útil quando você quer editar o código com HMR sem rebuildar a imagem:

```bash
# 1) Postgres + Mailpit em Docker (app e worker ficam fora)
docker compose --profile dev up -d postgres mailpit

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
>
> O Python do backend é gerenciado por `uv` — instale com `brew install uv` ou `curl -LsSf https://astral.sh/uv/install.sh | sh`. As deps ficam em `apps/api/pyproject.toml` (pins exatos) e `apps/api/uv.lock` é a fonte de verdade das versões.
>
> O front usa **Node 24**, e a versão mora só no `.node-version` — o mise, o Docker (build-arg) e o CI (`node-version-file`) leem dele. O Node 20 está EOL e o Vite 8 exige `^20.19 || >=22.12`. As demais ferramentas de dev estão no `mise.toml` — `mise install` prepara Node, just e uv na versão certa.

---

## Postgres-only: como cada coisa vira uma tabela

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

### Extensões opt-in (PostGIS, pgvector, pg_cron)

O init `scripts/postgres-init/01-extensions.sql` é tolerante: cada extensão roda num bloco `DO`/`EXCEPTION` e, se a imagem não tiver o pacote, vira `NOTICE` em vez de abortar. Então habilitar uma extensão extra é usar uma imagem que a tenha (`pg_cron` também exige `shared_preload_libraries=pg_cron` no start):

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

### Upgrade do Postgres (volume de major antigo)

O major novo muda o `PGDATA` (no PG18 é `/var/lib/postgresql/18/docker`), então **um volume de PG16/17 não sobe no PG18**. O sintoma é o container do Postgres em **loop de restart** com `mkdir: can't create directory '/var/lib/postgresql/18/': Permission denied` — o volume antigo pertence ao uid 999 (Debian) e o Alpine do PG18 roda como uid 70. O caminho é:

1. **Dump no major antigo** — `just backup-now` (ou `scripts/backup.sh` no host; o `pg_dump` precisa ser do major do servidor).
2. **Volume novo** — no Coolify, o volume é do resource: esvazie/recrie antes do novo deploy (`docker run --rm -v <volume>:/v alpine sh -c 'rm -rf /v/* /v/.[!.]*'` deixa o cluster se inicializar no path novo). Em dado descartável, pular o restore é suficiente.
3. **Restore** com o client do **major novo** (o `pg_restore` exige client ≥ servidor): `scripts/restore.sh <dump> --db app --yes`.
4. **Deploy de novo** — o container `migrate` aplica a baseline no banco novo.

Quando algum caso *realmente* pede Redis (pub/sub com baixa latência, geofencing com milhões de updates/s), você sabe que é exceção — não o default.

---

## Filas no Postgres — Procrastinate

`apps/api/app/jobs/app.py` configura o [Procrastinate](https://procrastinate.readthedocs.io/) 3.10.0:

- **Async nativo** (psycopg3) — não bloqueia o event loop.
- **Heartbeat / stall recovery** automáticos — jobs travados são re-claimados pela lib.
- **Periodic tasks** built-in (`@app.periodic(cron="*/5 * * * *")`).
- **Schema oficial** vem direto da lib (nunca duplicar ~600 linhas de SQL); a migration 0001 aplica via `SchemaManager.apply_schema()`.
- **Nomes padronizados**: `register_task(queue, action)` registra `name=f"{queue}.{action}"` e valida que queue/action são minúsculos, sem ponto/espaço.
- **Retry com teto**: `register_task(..., max_retries=3)` limita as tentativas; sem teto a falha nunca vira dead letter.
- **Rate limit por job** (`job_rate_limits`) e **DLQ** (`dead_letters`) no próprio Postgres.

Pra criar uma task:

```python
# apps/api/app/jobs/tasks/minha_task.py
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

- Senha: **bcrypt** (custo 12, via lib `bcrypt` direto). Register e login rejeitam senhas acima de 72 **bytes UTF-8** na fronteira (Pydantic) e no hash — nada é truncado em silêncio.
- Sessão: **token opaco** em cookie `HttpOnly`, `SameSite=Lax`, `Secure` em prod.
- O cookie armazena o token cru; o banco guarda `sha256(token)` em `sessions.token_hash` (índice unique).
- Logout = `DELETE FROM sessions WHERE token_hash = …` → revogação instantânea.
- Endpoints em `/api/v1/auth/{register,login,logout,me}`.
- `/auth/login` responde no mesmo tempo para e-mail inexistente e senha errada (verificação contra um hash dummy de custo equivalente) e emite log de auditoria com um fingerprint do e-mail — nunca o endereço cru.
- `GET /users` e `POST /users/enqueue-email` são **superuser-only** (403 para os demais). `DELETE /users/{id}` permite o próprio usuário ou um superuser.

---

## Auditoria (receita opt-in)

O template **não** grava `created_by`/`updated_by` em todas as tabelas. O que existe por default:

- `created_at`/`updated_at` com default do banco. O trigger `set_updated_at()` existe **só** em `users`; as outras tabelas não têm `updated_at`.
- O audit de auth (`auth.login`/`auth.register`/`auth.logout`) é **log estruturado** (structlog): `outcome`, fingerprint sha256 truncado do e-mail e `trace_id`. Serve para observabilidade; **não** é trilha de auditoria consultável — não guarda IP/UA, não é transacional e não sobrevive ao delete do usuário.

Por que não `created_by`/`updated_by` por default: nas tabelas de hoje o ator é sempre o próprio usuário (register, 2FA, passkey) — a coluna seria tautológica; `DELETE /users/{id}` é hard delete com `ON DELETE CASCADE`, então a autoria morre junto (e `ON DELETE RESTRICT` quebraria o delete); nas tabelas de sistema (`kv_cache`, `rate_limits`, `job_rate_limits`, `dead_letters`) não há ator humano. A coluna só faz sentido em **tabelas de negócio futuras** (multi-tenant, admin editando recurso de outro). O padrão da indústria é timestamp automático + **uma** tabela de log opt-in com o ator vindo do contexto do request (Django `admin.LogEntry`, Rails PaperTrail, Laravel `spatie/laravel-activitylog`, Prisma/Supabase) — nenhum framework grava `created_by` em todas as tabelas por default.

Quando o projeto precisar de trilha real (append-only), a receita é **opt-in e por tabela auditada**. Ela não mexe no `UserOut` nem no contrato OpenAPI.

### 1. Tabela e trigger

Exemplo para uma tabela `pedidos` com PK `id UUID` (troque os nomes pela tabela real):

```sql
CREATE TABLE pedidos_audit (
  id        BIGSERIAL PRIMARY KEY,
  thing_id  UUID NOT NULL,
  action    TEXT NOT NULL CHECK (action IN ('insert', 'update', 'delete')),
  actor_id  UUID,                          -- NULL = sistema
  row_data  JSONB NOT NULL,                -- delta, não o before/after completo
  ts        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE FUNCTION audit_pedidos() RETURNS trigger AS $$
DECLARE
  v_actor UUID := current_setting('app.actor_id', true)::uuid;
BEGIN
  INSERT INTO pedidos_audit (thing_id, action, actor_id, row_data)
  VALUES (
    COALESCE(NEW.id, OLD.id),
    lower(TG_OP),
    v_actor,
    CASE TG_OP
      WHEN 'INSERT' THEN to_jsonb(NEW)
      WHEN 'DELETE' THEN to_jsonb(OLD)
      ELSE (
        SELECT COALESCE(jsonb_object_agg(n.key, n.value), '{}'::jsonb)
        FROM jsonb_each(to_jsonb(NEW)) AS n
        JOIN jsonb_each(to_jsonb(OLD)) AS o USING (key)
        WHERE n.value IS DISTINCT FROM o.value
      )
    END
  );
  RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_pedidos_audit
AFTER INSERT OR UPDATE OR DELETE ON pedidos
FOR EACH ROW EXECUTE FUNCTION audit_pedidos();
```

O trigger cobre `INSERT`/`UPDATE`/`DELETE`, não `SELECT` nem DDL. `app.actor_id` ausente vira `NULL` (sistema); não sete a variável com string vazia (o cast para `uuid` falha).

### 2. Ator: `SET LOCAL` na mesma transação

```sql
BEGIN;
SELECT set_config('app.actor_id', $1, true);  -- $1 = UUID do ator
-- <DML na tabela auditada>
COMMIT;
```

A transação explícita é obrigatória: `set_config(..., true)` é local e morre no fim da transação (no SQLAlchemy, `begin` → `set_config` → DML → `commit`). Com `DATABASE_URL_POOLER` e pgbouncer em `pool_mode=transaction` isso é seguro por construção, porque o estado nunca atravessa a transação (AD-037).

O ator vem do **servidor** — a sessão opaca validada no cookie —, **nunca** do body da request. Aceitar um `updated_by` enviado pelo cliente é deixar qualquer um forjar a trilha.

### 3. Privilégios

A role da aplicação precisa de `INSERT` (e `SELECT`, se for consultar) na tabela de auditoria, mas **não** de `UPDATE`/`DELETE`:

```sql
REVOKE UPDATE, DELETE ON pedidos_audit FROM app;
```

O trigger roda como invoker; sem o `INSERT` a DML na tabela auditada falha. Se a role da app for **owner** da tabela de auditoria, o `REVOKE` não a limita (owner pode se re-conceder) — crie a tabela com outro owner (o role das migrations) para o append-only valer.

### 4. LGPD e retenção

- Grave o **delta** (o que mudou), não before/after completo — duplicar PII no log amplia o escopo da LGPD. No `INSERT`/`DELETE` a linha inteira é o delta; omita colunas sensíveis (ex.: `to_jsonb(NEW) - 'campo_sensivel'`).
- Para identificar o titular use hash/fingerprint do e-mail (o repo já faz sha256 truncado no audit de auth), não o endereço cru.
- Retenção **menor** que a dos dados de negócio e documentada. A limpeza pode seguir o padrão dos jobs de cleanup do template quando `pg_cron` está disponível.

---

## Observability (opcional, vendor-agnostic)

App emite **OTLP** quando `OTEL_EXPORTER_OTLP_ENDPOINT` está setado. Sem env, é no-op.

```bash
# 1) Sobe a stack + Grafana/Tempo/Prometheus/OTel Collector
just up-obs

# 2) Configure .env:
#    OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317
#    OTEL_TRACES_SAMPLER=parentbased_traceidratio
#    OTEL_SAMPLE_RATIO=1.0
#    SENTRY_DSN=https://...@sentry.io/...

# 3) Restart api/worker
just down && just up
```

Amostragem: `OTEL_TRACES_SAMPLER` aceita `always_on`, `always_off`, `traceidratio`
ou `parentbased_traceidratio` (default); o ratio vem de `OTEL_SAMPLE_RATIO`
(alias `OTEL_TRACES_SAMPLER_ARG`), default `1.0`.

Cada resposta traz `X-Trace-Id` quando há span; logs incluem `trace_id`/`span_id`
e o worker continua o trace do job (request → `email.enqueue` → `email.send`).

URLs:
- Grafana: <http://localhost:3000> (user `admin`; senha = `GRAFANA_ADMIN_PASSWORD`)
- Tempo API: <http://localhost:3200>
- Prometheus: <http://localhost:9090>

Credenciais default do compose (Postgres `app`/`app`) são só para dev local.
`GRAFANA_ADMIN_PASSWORD` precisa de um valor sempre que o Compose for interpolado: o compose usa `${GRAFANA_ADMIN_PASSWORD:?...}` e a interpolação é global — `docker compose up` falha sem ela mesmo sem o profile `observability` (o Grafana 11.3.1 cairia em `admin`/`admin`). Qualquer valor satisfaz o `config`; o valor real só importa quando o stack de observability sobe. `just validate-compose` (e o job do CI) injeta um valor de validação quando a variável está ausente, então não é preciso passá-la na invocação.

Sem Sentry self-hosted (pesado demais). Se precisar de error tracking, use Sentry SaaS via `SENTRY_DSN`.

---

## Produção

O repositório serve **HTTP puro**. **TLS é requisito de deployment**: coloque um reverse proxy/balanceador terminando HTTPS na frente da API. Sem TLS o cookie `Secure` não volta ao navegador e o HSTS não protege nada — a app não embute TLS e o repo não embute proxy (o caminho Coolify está logo abaixo; contrato em AD-036).

- **Fail-fast de configuração**: com `APP_ENV=prod` o boot aborta se `SECRET_KEY` ainda for o default (ou tiver <32 chars), se `COOKIE_SECURE=false` ou se `WEB_ORIGIN` não começar com `https://`. Config impossível não sobe.
- **Proxy confiável**: `FORWARDED_ALLOW_IPS` deve listar **só** os IPs/redes do seu proxy (default `127.0.0.1`). **Nunca use `*`**: qualquer cliente forjaria `X-Forwarded-For` e ganharia um bucket novo de rate limit. No Coolify o Traefik tem IP dinâmico na rede do recurso: use `172.16.0.0/12`, nunca o IP exato.
- **Postgres gerenciado**: defina `DB_SSLMODE` (ex.: `require`) — ele é anexado/sobrescrito na DSN. A baseline não exige `uuid-ossp` (usa `gen_random_uuid()`) e trata `pg_cron` como opcional (RDS/Aurora/Cloud SQL sobem sem ela; a limpeza periódica fica com o operador). `citext` continua obrigatória.
- **Grafana**: `GRAFANA_ADMIN_PASSWORD` precisa de um valor sempre que o Compose for interpolado (interpolação global do `${VAR:?}`, mesmo sem o profile `observability`); o valor real só importa quando o stack de observability roda. `just validate-compose` e o CI usam um valor de validação automaticamente.
- **Mailpit**: fica atrás do profile `dev` e não sobe no `docker compose up` padrão. Use `docker compose --profile dev up -d mailpit` quando precisar capturar e-mail local.
- **Docs desligados**: em prod `/api/docs`, `/api/redoc` e `/api/openapi.json` não existem. HSTS e CSP só são aplicados em prod.
- **Backup**: `BACKUP_ENCRYPT_PASSPHRASE` cifra o dump (AES-256-CBC/PBKDF2) antes de manter/enviar; sem ela o dump sai em claro e o script avisa. Os dumps são `0600`; `BACKUP_KEEP_COUNT` controla a retenção local (default 14).
- **Entrega**: `.github/workflows/deploy.yml` publica no GHCR a cada push na `main`/tag `v*` e anexa SBOM SPDX (syft) + assinatura keyless (cosign/OIDC). As actions são pinadas por commit SHA; o Dependabot abre PRs semanais para pip, npm, GitHub Actions e Docker.

---

## Implantar no Coolify (VPS)

O repo **não embute proxy**: a app sobe HTTP puro e o TLS termina no proxy do Coolify (Traefik v3.7 por padrão) ou no Cloudflare. Contrato de cabeçalhos, matriz de responsabilidades e limites em `docs/architecture.md` (AD-036).

1. **Recurso**: build pack **Docker Compose**, Base Directory = raiz do repo, Docker Compose Location = `docker-compose.yml`. O Coolify roda `docker compose up -d` **sem `--profile`**, então `postgres`, `migrate`, `api` e `worker` sobem juntos; os perfis `dev` (mailpit) e `observability` continuam opcionais.
2. **Env vars**: cole na UI do Coolify (Developer view aceita formato `.env`). Copie o `.env.example` e troque o que é de prod:

   ```dotenv
   APP_ENV=prod
   SECRET_KEY=<32+ chars aleatórios>
   COOKIE_SECURE=true
   WEB_ORIGIN=https://app.example.com
   POSTGRES_PASSWORD=<senha forte>
   DATABASE_URL=
   FORWARDED_ALLOW_IPS=172.16.0.0/12
   GRAFANA_ADMIN_PASSWORD=<qualquer valor>
   ```

   Preencha `DATABASE_URL` **ou** os `POSTGRES_*` (dentro do compose o host do banco é `postgres`); em Postgres gerenciado, defina `DB_SSLMODE=require`. `GRAFANA_ADMIN_PASSWORD` é exigida **mesmo sem** o profile `observability`: a interpolação `${GRAFANA_ADMIN_PASSWORD:?...}` do Compose é global. O `.env` versionado no repo **não é lido**: o Coolify gera/sobrescreve o `.env` do diretório de deploy e injeta `env_file: ['.env']` — a fonte é a UI.
3. **Domínio**: só no serviço `api` e com o sufixo da porta interna (`app.example.com:8000`). O `8000` é a porta do container; a publicada no host é só `127.0.0.1:${API_PORT}` e o proxy fala pelo IP da rede Docker.
4. **Borda** — escolha uma:
   - **(a) Cloudflare com proxy (nuvem laranja)**: o Traefik precisa confiar nos ranges da Cloudflare para preservar o IP real — `--entrypoints.{http,https}.forwardedHeaders.trustedIPs=<ranges da CF>` (comandos custom do proxy são preservados pelo Coolify). Sem isso a app enxerga só o IP da borda. O certificado vem por **DNS-01** com Cloudflare (ver **TLS com Cloudflare (DNS-01)** abaixo) ou Cloudflare Origin Certificate: HTTP-01 não completa com o proxy da CF ligado.
   - **(b) Cloudflare Tunnel**: crie o recurso pelo template `cloudflared`, roteie o hostname para `http://localhost:80` e **desligue "Redirect HTTP to HTTPS"** no recurso (senão vira loop). Nesse caminho use `FORWARDED_ALLOW_IPS=127.0.0.1`; o ACME HTTP-01 do Traefik também não completa atrás do tunnel — use DNS challenge ou Origin Cert.
5. **Backup**: use o **backup agendado do Coolify** para S3/R2 (passo a passo em **Backup do banco no R2** abaixo). Os `scripts/backup.sh` do repo são o caminho **fora** do Coolify (rodam no host e exigem `pg_dump`).
6. **Gotchas do Coolify**:
   - não passa `--profile` (bug #6395) — por isso os serviços core não têm profile;
   - o deploy é marcado **FINISHED antes do healthcheck** (não espera `--wait`); a saúde real aparece depois;
   - `container_name`, nome do projeto e volumes são renomeados pelo Coolify;
   - Docker Compose não faz rolling update nem réplicas (v4.5.0; `scale`/`replicas` > 1 é rejeitado): cada deploy recria os containers, com downtime curto;
   - o status agregado do resource pode aparecer como `running:unknown` — é **cosmético** (a UI não parseia o health do compose); a saúde real se vê por serviço e por `/api/v1/healthz` (com `db=true`) + `docker compose ps`;
   - `${VAR:?}` é interpolado globalmente (ver `GRAFANA_ADMIN_PASSWORD` acima).
7. **Sem Coolify**: ponha um proxy próprio (Caddy/nginx) no host terminando TLS em `127.0.0.1:${API_PORT}`. API e Postgres já publicam só em loopback; use `FORWARDED_ALLOW_IPS=127.0.0.1`.

### Trocar para Postgres gerenciado (Neon/RDS/Cloud SQL)

**Quando trocar** — por métrica sustentada por dias, não por feeling: disco do Postgres acima de 70%, RAM do Postgres competindo com a app (pressão de OOM), `pg_stat_activity` saturando o pool, ou o backup parando a VPS. Antes disso, 1 VPS (4 vCPU/8 GB) com Postgres local cobre bem: a API é stateless (a sessão é uma linha em `sessions`; o cookie é só o token opaco), então escala horizontal sem sticky session — o primeiro gargalo é disco/RAM do Postgres na mesma caixa, não a API.

**Como trocar**:

1. Crie o Postgres gerenciado e guarde host, porta, banco, usuário e senha.
2. No resource da Coolify (ou no `.env` local), defina `DATABASE_URL` com o esquema `postgresql+asyncpg://`, usuário/senha e `?sslmode=require`. Esse é o único caminho que cobre os **três** consumidores: o `apply_sslmode`, que anexa/sobrescreve `DB_SSLMODE` na DSN, só roda no **engine da API** — o **Alembic** (`migrations/env.py`) e o **Procrastinate/worker** usam a DSN **sem** `sslmode`. O esquema importa: sem `+asyncpg`, o `create_async_engine` recebe um driver síncrono e falha. `DATABASE_URL` tem precedência sobre os `POSTGRES_*`.
3. **Edite o `docker-compose.yml` do projeto** (não o template): remova o serviço `postgres`, a entrada `postgres` do `depends_on` (`condition: service_healthy`) de `migrate`, `api` e `worker`, e o `POSTGRES_HOST: postgres` do `environment:` dos três — o `environment:` vence o `env_file`. Sem isso o app continua apontando para o banco do compose.
4. O `migrate` continua one-shot: roda `alembic upgrade head` contra o banco externo antes de `api`/`worker` (`service_completed_successfully`).
5. O `worker` deve usar o **endpoint direto**, não o pooler/PgBouncer: o Procrastinate mantém conexão persistente e o pooler em transaction mode quebra o worker.
6. Confirme que o schema subiu: `alembic_version` existe no banco externo e `/api/v1/healthz` responde `db=true`.

**O que muda e o que não muda**: é o mesmo código — o `DATABASE_URL` já tem precedência sobre `POSTGRES_*`. O `docker-compose.yml` **do repo continua com o `postgres`**, porque é isso que o CI prova (o job `docker` boota a stack com `db=true`) e o que o e2e local usa; a mudança é no deploy do projeto, não no template. Fila, sessão, cache e rate limit continuam no mesmo banco (AD-001), então **não** há Redis.

**Extensões**: `citext` é obrigatória e a migration a cria (se o provedor exigir, habilite antes). `pg_cron` é opcional — a baseline tolera a falta e você perde só o cleanup agendado de `rate_limits`/`dead_letters`, que passa a ser tarefa do operador. As 9 extensões de `scripts/postgres-init/01-extensions.sql` são affordance do template (o init do container não roda num PG gerenciado) e **nada no app as usa hoje**: se o projeto precisar de geo ou embeddings, provisione a extensão no provedor.

**Backup/restore**: com o banco gerenciado o backup é do provedor (RDS tem PITR; no Neon, confirme a retenção do branching) e o backup de volume do Coolify deixa de se aplicar (não há volume). **A Coolify não tem PITR**; se o provedor escolhido também não tiver, o dump lógico do repo — `scripts/backup.sh` (`pg_dump -Fc` + sanidade `pg_restore --list`) e `just test-restore` — continua sendo o caminho de restore confiável. Atenção: `scripts/backup.sh`/`restore.sh`/`test-restore.sh` **não leem `DATABASE_URL` nem `DB_SSLMODE`** — só `POSTGRES_HOST/PORT/DB/USER/PASSWORD`; contra um Postgres gerenciado preencha os `POSTGRES_*` e exporte `PGSSLMODE=require` (o `libpq` respeita) ou ajuste os scripts.

### Backup do banco no R2

No nosso modelo (compose), o Postgres **não** é um database resource da Coolify: ele aparece como **persistent storage** da application (`pgdata`). Por isso o backup nativo da Coolify para ele é o **backup de volume** — um `tar.gz` do data dir, enviado ao S3/R2.

1. **Destinations/S3**: crie um token no **Cloudflare R2** com permissão **"Object Read & Write"** e configure o destination com **Name**, **Bucket**, **Region** (deixe o default), **Access Key** (`<access-key>`) e **Secret Key** (`<secret-key>`). O endpoint é separado em **Protocol** = `https`, **Host** = hostname do endpoint S3 **sem scheme** (ex.: `<conta>.r2.cloudflarestorage.com`), **Port** e **Path** (a Coolify usa o cliente MinIO `mc`).
2. **Backup schedule** do volume `pgdata`: escolha a frequência, o destination acima e, para consistência, ligue **"Stop during backup"** — a Coolify para os containers que usam o volume durante a cópia (downtime enquanto o backup roda). Sem isso o `tar.gz` do data dir pode sair inconsistente. Configure também a retenção (quantidade de backups, dias e storage máximo).
3. **Back up now**: executa uma cópia imediata, sem esperar o agendamento.
4. **Restore**: o restore do volume é **file-level** — exige o **mesmo major do Postgres** e o banco **parado**. Justamente por isso o caminho de restore **confiável** do repo é o dump **lógico**: `scripts/backup.sh` no host (`pg_dump -Fc`, sanidade `pg_restore --list`, cifra opcional), provado por `just test-restore` (roda em container, sem client no host) e pelo job `restore-test` do CI (ver "Backup (R2)").

O backup **lógico** da Coolify (`pg_dump` + **"Import Backup"**) só existe para **databases gerenciados** (um recurso Database da Coolify) — não é o caminho do Postgres do compose. E **não há PITR** em nenhum dos dois caminhos: o restore devolve a última cópia, não um momento arbitrário entre execuções. Quem precisar de PITR precisa de outro provedor; o repo não oferece.

### TLS com Cloudflare (DNS-01)

O ACME **HTTP-01** padrão exige rota pública (não completa com o proxy laranja da Cloudflare nem atrás do tunnel). Para emitir via **DNS-01** com a Cloudflare no Traefik da Coolify:

- env `CF_DNS_API_TOKEN=<token do Cloudflare com permissão "Edit zone DNS">`;
- comando custom do proxy `--certificatesresolvers.letsencrypt.acme.dnschallenge.provider=cloudflare`.

Funciona em self-hosted (Lego) e permite wildcard; o storage do ACME é `/traefik/acme.json`. O `coolify-proxy` é 1 por servidor em 80/443 e roteia por `Host`, então vários apps com subdomínios convivem; o toggle "Redirect HTTP to HTTPS" é o `is_force_https_enabled`, e certificado custom/self-signed vai em `/data/coolify/proxy/certs/`. No caminho **Cloudflare Tunnel** (item 4b) o "Redirect HTTP to HTTPS" fica desligado, `FORWARDED_ALLOW_IPS=127.0.0.1` e DNS-01 ou Origin Cert resolvem o certificado.

---

## Tuning e escala

Quando a VPS padrão (4 vCPU/8 GB, Postgres no mesmo host) começa a apertar, o primeiro gargalo é conexão/pool do banco, não a API. `docs/tuning.md` traz o dimensionamento por faixa de VPS, os knobs do Postgres por RAM, quando ligar o pgbouncer (e as incompatibilidades do transaction mode), o tuning do uvicorn/bcrypt e a tabela de medição (sinal → ação) — além do que a Coolify v4.5.0 não oferece (rolling update, réplicas, PITR).

---

## Email transacional

**SMTP-only.** Um caminho de código, qualquer provedor.

### Dev local (Mailpit)

```bash
docker compose --profile dev up -d   # Postgres + migrate + api + worker + mailpit
just mail                                          # abre http://localhost:8025
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
1. `pg_dump -Fc -Z 9` → arquivo local `0600` + sidecar `.sha256`.
2. Sanidade real: `pg_restore --list` (um dump truncado **não** passa só por ter tamanho).
3. Cifra opcional: com `BACKUP_ENCRYPT_PASSPHRASE` o dump vira `<db>_<ts>.dump.enc` (`openssl enc -aes-256-cbc -pbkdf2`); sem ela o script avisa que o dump (hashes de senha, TOTP e PII) sai em claro.
4. `rclone copyto` → `r2:<bucket>/db/<arquivo>` (sem `RCLONE_BUCKET` roda em modo local e **mantém** o dump).
5. `rclone delete --min-age 14d` → retenção remota; no modo local, `BACKUP_KEEP_COUNT` (default 14) mantém os últimos dumps.

Os scripts de backup/restore rodam no **host** (precisam de `pg_dump`/`pg_restore`/`psql` no PATH) e usam `flock` para não se sobrepor. Dentro do Coolify, o caminho é o backup agendado do Coolify para S3/R2 (ver "Implantar no Coolify").

### Restauração (com prova)

```bash
just test-restore                              # backup -> restore -> verificação (roda em container, sem client no host)
./scripts/restore.sh <dump> --db meu_restore --dry-run
./scripts/restore.sh <dump> --db meu_restore --yes
```

`restore.sh` exige **alvo explícito** (`--db`/`POSTGRES_RESTORE_DB`) e `--yes`: nunca adivinha o banco de destino. `test-restore.sh` cria bancos de descarte (`<db>_restore_test_src/dst`), faz backup→restore e confere count, `to_regclass`, md5 do conteúdo, índice, PK e sequência — e só opera em banco com `restore_test` no nome. `just test-restore` sobe o `postgres` do compose e roda o script dentro desse container; não exige `psql`/`pg_dump`/`pg_restore` no host. O CI roda o mesmo script no job `restore-test`.

Para credenciais, prefira `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` de **Scoped Token** do R2 (apenas bucket de backup).

---

## Tipos compartilhados (OpenAPI → TS)

O backend expõe o schema em `/api/openapi.json`. Para o front consumir esses tipos como TS:

```bash
just web-types
# ou, à mão:
cd apps/api && uv run python -m app.cli dump-openapi > openapi.json
cd apps/web && npm run gen:api    # openapi-typescript openapi.json → src/api/schema.d.ts
```

O fluxo:
1. `app.cli dump-openapi` importa o FastAPI `app` e imprime `app.openapi()` em JSON.
2. `openapi-typescript` gera `apps/web/src/api/schema.d.ts` (tipos de schemas + paths).
3. `src/api/types.ts` reexporta os types relevantes.
4. `src/api/endpoints.ts` declara helpers tipados por endpoint.

Sempre que você **adicionar/alterar** um endpoint ou Pydantic model, rode `just web-types`. O `pre-commit` recusa o commit se `schema.d.ts` estiver desatualizado (`just check-schema` pra checar manualmente).

Duas regras para o contrato não se degradir:

- **Toda resposta de rota declara um model Pydantic explícito.** `dict[str, Any]` como `response_model` vira `Record<string, never>` no TypeScript — o front fica sem contrato nenhum. Use `model_validate` (entrada) e `model_dump(exclude_none=True)` (saída); `response_model_exclude_unset=True` quando o shape não pode ganhar campos nulos.
- **`just check-schema` também é gate semântico**: além do diff de bytes, ele falha se alguma resposta de rota virar `Record<string, never>`/`unknown`. Rodar `just web-types` sem modelar a resposta não passa no CI.

No front, os tipos vêm de `components["schemas"][...]` (reexportados em `src/api/types.ts`) — não redeclare shape de resposta à mão.

---

## CI e entrega

`.github/workflows/ci.yml`:
- **backend**: ruff + pyright + bandit + pytest
- **frontend**: tsc + lint (Biome) + build + `npm audit --omit=dev --audit-level=moderate`
- **sast**: semgrep com as regras locais de `semgrep.yml`
- **dependency-audit**: pip-audit (via `uvx`) nas deps de produção do backend
- **e2e**: Playwright nos cenários mockados (`page.route`), sem API/DB
- **schema-sync**: regenera `schema.d.ts` e falha se estiver desatualizado
- **compose**: valida que `docker-compose.yml` continua válido
- **docker**: build da imagem + medição do tamanho real (teto de 700 MB) + **boot do stack** (readiness `db=true`, `alembic_version`, worker vivo) + Trivy (CRITICAL/HIGH bloqueita)

`.github/workflows/restore-test.yml` roda backup → restore → verificação num Postgres efêmero.

`.github/workflows/deploy.yml` publica a imagem no GHCR em push na `main`/tag `v*`, gera SBOM SPDX com syft e assina imagem + SBOM com cosign keyless (OIDC). As actions do CI e do deploy são pinadas por **commit SHA**; o Dependabot abre PRs semanais para pip, npm, GitHub Actions e Docker.

Local: `just ci` roda os mesmos checks (backend, frontend, semgrep, auditorias, E2E mock, schema e compose). O `validate-compose` materializa um `.env` a partir do `.env.example` se não houver um e usa `GRAFANA_ADMIN_PASSWORD=validation-only` quando a variável está ausente/vazia — não é preciso passá-la na invocação. O build da imagem, a medição do tamanho, o Trivy e a prova de restauração só rodam no CI (exigem daemon).

---

## Convenções

- **Lint/typecheck**:
  - Backend: `ruff` (linter + formatter) + `pyright` (type checker). `just lint`, `just typecheck`.
  - Frontend: `biome` 2.x (linter + formatter + import sort, único tool). `just web-lint`, `just web-lint-fix`. Roda com `--error-on-warnings`: warning bloqueia igual a erro, e as regras relevantes (`noExplicitAny`, `noConsole`, `useImportType`, `noUnusedImports`, `noUnusedVariables`, `noUndeclaredVariables`, `noNonNullAssertion`...) estão em `error`. Na 2.x a regra de console é `noConsole` (bloqueia tudo por padrão; o config libera explicitamente tudo **exceto** `console.log`).
  - **SAST**: `just bandit` (backend) + `just semgrep` (regras do projeto em `semgrep.yml`; requer `pipx install semgrep`).
  - Tudo roda em `just ci` (mesmo do GitHub Actions).
- **Editor (VSCode)**: `.vscode/` tem settings compartilhadas (Biome como formatter default, Ruff no Python, Pyright, Tailwind, etc.), launch configs (API, worker, pytest) e tasks (`just init`, `just dev`, `just ci`, etc.). Abre o workspace e o VSCode oferece instalar as extensões recomendadas.
- **Migrações**: `just api-revision "add foo"` → revisar antes de commitar.
- **Saúde**: liveness (`/api/v1/livez`, não toca o banco) ≠ readiness (`/api/v1/healthz`, 503 + `degraded` quando o banco cai). O HEALTHCHECK do container usa o **livez**; `worker` e `migrate` desligam o healthcheck (não servem HTTP).
- **Boot**: papéis `migrate` (one-shot, roda a migration) | `api` | `worker`. Só o `migrate` roda `alembic upgrade head` — api/worker esperam ele terminar.
- **Backup/restore**: `just backup-now` (host, exige `pg_dump`/`rclone`), `just test-restore` (prova de restauração), `./scripts/restore.sh <dump> --db <alvo> --yes`.
- **Dependências Python**: `uv` + `apps/api/uv.lock` (fonte de verdade); pins exatos em `apps/api/pyproject.toml`. `apps/api/requirements.txt` não existe mais. `just api-install` roda `uv sync`; `just api-audit` audita as deps de produção (pip-audit via `uvx`).
- **Toolchain do front**: Node 24 com **fonte única** em `.node-version` (o mise, o Docker via build-arg e o CI via `node-version-file` leem dele; `engines` + `engine-strict` no `package.json` derrubam a install com Node antigo). Tailwind 4 é **CSS-first**: o tema vive em `@theme` no `src/index.css` e as classes do design system em `@utility` — não existe `tailwind.config.js` nem `postcss.config.js`.
- **Segredos**: NUNCA comitar `.env`. Em prod, monte via secret manager do orquestrador.
- **Logs**: `structlog` JSON em prod, console em dev (stderr pra não poluir stdout).
- **Tests**: `just test` roda a suite de 169 testes. Tudo que não precisa de DB.
- **E2E**: `just e2e-mock` roda só os cenários mockados (`page.route`, sem API/DB — é o que o CI roda); `just e2e` roda a suíte inteira pulando o que precisa de backend; `just e2e-full` sobe o stack e roda contra a SPA servida pela API em `:8000` (semeia um superuser determinístico, porque `POST /users/enqueue-email` é superuser-only).

---

## Decisões de arquitetura (ADRs)

`docs/architecture.md` lista em detalhe cada decisão: Postgres-only, Procrastinate, bcrypt direto (não passlib), OpenAPI pipeline, SPA mesma origem, exception handler, CLI, tests, multi-region seams, observability vendor-agnostic, SQLAlchemy Core para queries (ORM só para schema), hardening de produção/2FA, backup e supply chain, etc.

---

## Roadmap honesto

Tudo o que era **infraestrutura de template** está feito. O que sobra é decisão de produto:

- 2FA enforcement policy (sempre? opt-in? por org?)
- OAuth/SSO (Google, GitHub, etc.)
- Frontend com React Hook Form unit tests (vitest + RTL)
- OIDC
- Multi-region (ADR-010 lista onde mexer)
- Migration de autenticação para JWT (se necessário para SPAs separados)