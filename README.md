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
├── docs/
│   ├── architecture.md       ADRs
│   ├── auth.md               auth, 2FA e auditoria
│   ├── backup.md             backup e restore do banco
│   ├── deploy.md             deploy (Coolify), produção e borda
│   ├── operacoes.md          observability, email e CI
│   ├── postgres.md           tabelas, extensões e filas
│   └── tuning.md             dimensionamento e knobs por RAM
├── Dockerfile                multi-stage (Node build + Python runtime)
├── docker-compose.yml        postgres + migrate + api + worker (dev: mailpit · observability)
├── docker-compose.override.yml  só dev local: publica 127.0.0.1:8000 e :5432
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

O `docker-compose.yml` é o **artefato de deploy** e não publica porta no host. As portas `127.0.0.1:8000` (app) e `127.0.0.1:5432` (Postgres) do stack local vêm do `docker-compose.override.yml`, que o `docker compose` auto-mescla (sem `-f`). O Coolify e o CI rodam com `-f docker-compose.yml` e **ignoram** o override.

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

## Documentação

Este README é o índice e o caminho feliz. Os guias de fundo vivem em `docs/`:

| Guia | O que tem |
| --- | --- |
| [docs/deploy.md](docs/deploy.md) | Deploy no Coolify (resource, env vars, domínio, borda, pós-deploy), o checklist de produção, Postgres gerenciado, o backup nativo de volume no R2 e o TLS com Cloudflare |
| [docs/backup.md](docs/backup.md) | Dump lógico (`scripts/backup.sh`), cifragem, retenção, o **modo container** (deploy sem porta publicada) e a restauração com prova (`just test-restore`) |
| [docs/postgres.md](docs/postgres.md) | Como cada necessidade vira uma tabela, extensões opt-in, upgrade do Postgres e as filas no Postgres (Procrastinate) |
| [docs/auth.md](docs/auth.md) | Sessão, rate limit, 2FA (TOTP + passkey) e a receita opt-in de auditoria |
| [docs/operacoes.md](docs/operacoes.md) | Observability (OTLP/Grafana), email transacional e o CI/entrega |
| [docs/architecture.md](docs/architecture.md) | As ADRs: Postgres-only, Procrastinate, bcrypt, OpenAPI, SPA mesma origem, Core vs ORM, hardening de produção, supply chain… |
| [docs/tuning.md](docs/tuning.md) | Dimensionamento por faixa de VPS (quando a VPS padrão de 4 vCPU/8 GB começa a apertar, o primeiro gargalo é conexão/pool do banco, não a API), knobs do Postgres por RAM, pgbouncer, uvicorn/bcrypt e a tabela de medição |

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
- **Toolchain do front**: Node 24 com **fonte única** em `.node-version` (o mise, o Docker via build-arg e o CI via `node-version-file`) leem dele; `engines` + `engine-strict` no `package.json` derrubam a install com Node antigo. Tailwind 4 é **CSS-first**: o tema vive em `@theme` no `src/index.css` e as classes do design system em `@utility` — não existe `tailwind.config.js` nem `postcss.config.js`.
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
