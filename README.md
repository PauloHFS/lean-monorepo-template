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
- **Banco único** Postgres (PostGIS, pgvector, ltree, pg_trgm, btree_gist, pgcrypto, citext; baseline sem `uuid-ossp`, `pg_cron` opcional)
- **Backup** automatizado para Cloudflare R2 (via `rclone`), com dump `0600`, cifra opcional e retenção local

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
├── docker-compose.yml        postgres (+ app: api+worker · dev: mailpit · observability)
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
- Health: <http://localhost:8000/api/v1/healthz> (readiness) · <http://localhost:8000/api/v1/livez> (liveness)
- Mailpit (profile `dev`): <http://localhost:8025>  (`docker compose --profile dev up -d mailpit` · `just mail`)

Pra criar um admin e logar:

```bash
docker compose --profile app exec api python -m app.cli seed   # imprime email + senha aleatória
```

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
`GRAFANA_ADMIN_PASSWORD` é **obrigatória** no profile `observability`: o compose usa `${GRAFANA_ADMIN_PASSWORD:?...}` e recusa subir sem ela (o Grafana 11.3.1 cairia em `admin`/`admin`).

Sem Sentry self-hosted (pesado demais). Se precisar de error tracking, use Sentry SaaS via `SENTRY_DSN`.

---

## Produção

O repositório serve **HTTP puro**. **TLS é requisito de deployment**: coloque um reverse proxy/balanceador terminando HTTPS na frente da API. Sem TLS o cookie `Secure` não volta ao navegador e o HSTS não protege nada — o app não embute TLS.

- **Fail-fast de configuração**: com `APP_ENV=prod` o boot aborta se `SECRET_KEY` ainda for o default (ou tiver <32 chars), se `COOKIE_SECURE=false` ou se `WEB_ORIGIN` não começar com `https://`. Config impossível não sobe.
- **Proxy confiável**: `FORWARDED_ALLOW_IPS` deve listar **só** os IPs/redes do seu proxy (default `127.0.0.1`). **Nunca use `*`**: qualquer cliente forjaria `X-Forwarded-For` e ganharia um bucket novo de rate limit.
- **Postgres gerenciado**: defina `DB_SSLMODE` (ex.: `require`) — ele é anexado/sobrescrito na DSN. A baseline não exige `uuid-ossp` (usa `gen_random_uuid()`) e trata `pg_cron` como opcional (RDS/Aurora/Cloud SQL sobem sem ela; a limpeza periódica fica com o operador). `citext` continua obrigatória.
- **Grafana**: `GRAFANA_ADMIN_PASSWORD` é obrigatória no profile `observability`; sem ela o Compose recusa subir.
- **Mailpit**: fica atrás do profile `dev` e não sobe com `--profile app`. Use `docker compose --profile dev up -d mailpit` quando precisar capturar e-mail local.
- **Docs desligados**: em prod `/api/docs`, `/api/redoc` e `/api/openapi.json` não existem. HSTS e CSP só são aplicados em prod.
- **Backup**: `BACKUP_ENCRYPT_PASSPHRASE` cifra o dump (AES-256-CBC/PBKDF2) antes de manter/enviar; sem ela o dump sai em claro e o script avisa. Os dumps são `0600`; `BACKUP_KEEP_COUNT` controla a retenção local (default 14).
- **Entrega**: `.github/workflows/deploy.yml` publica no GHCR a cada push na `main`/tag `v*` e anexa SBOM SPDX (syft) + assinatura keyless (cosign/OIDC). As actions são pinadas por commit SHA; o Dependabot abre PRs semanais para pip, npm, GitHub Actions e Docker.

---

## Email transacional

**SMTP-only.** Um caminho de código, qualquer provedor.

### Dev local (Mailpit)

```bash
docker compose --profile app --profile dev up -d   # Postgres + api + worker + mailpit
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

Os scripts rodam no **host** (precisam de `pg_dump`/`pg_restore`/`psql` no PATH) e usam `flock` para não se sobrepor.

### Restauração (com prova)

```bash
just test-restore                              # backup -> restore -> verificação (exige Postgres + client)
./scripts/restore.sh <dump> --db meu_restore --dry-run
./scripts/restore.sh <dump> --db meu_restore --yes
```

`restore.sh` exige **alvo explícito** (`--db`/`POSTGRES_RESTORE_DB`) e `--yes`: nunca adivinha o banco de destino. `test-restore.sh` cria bancos de descarte (`<db>_restore_test_src/dst`), faz backup→restore e confere count, `to_regclass`, md5 do conteúdo, índice, PK e sequência — e só opera em banco com `restore_test` no nome. O CI roda o mesmo script no job `restore-test`.

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
- **docker**: build da imagem + medição do tamanho real (teto de 700 MB) + Trivy (CRITICAL/HIGH bloqueia)

`.github/workflows/restore-test.yml` roda backup → restore → verificação num Postgres efêmero.

`.github/workflows/deploy.yml` publica a imagem no GHCR em push na `main`/tag `v*`, gera SBOM SPDX com syft e assina imagem + SBOM com cosign keyless (OIDC). As actions do CI e do deploy são pinadas por **commit SHA**; o Dependabot abre PRs semanais para pip, npm, GitHub Actions e Docker.

Local: `just ci` roda os mesmos checks (backend, frontend, semgrep, auditorias, E2E mock, schema e compose). O `validate-compose` interpola `GRAFANA_ADMIN_PASSWORD`, então rode `GRAFANA_ADMIN_PASSWORD=... just ci`. O build da imagem, a medição do tamanho, o Trivy e a prova de restauração só rodam no CI (exigem daemon).

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
- **E2E**: `just e2e-mock` roda só os cenários mockados (`page.route`, sem API/DB — é o que o CI roda); `just e2e` roda a suíte inteira pulando o que precisa de backend; `just e2e-full` sobe o stack e roda contra a SPA servida pela API em `:8000`.

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