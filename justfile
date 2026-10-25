# Lean Monorepo — atalhos de DX.
# https://just.systems  (instale com `brew install just` ou `cargo install just`)
#
# .env é carregado automaticamente; variáveis ficam acessíveis como $VAR.

set dotenv-load

default:
    @just --list

# Sobe Postgres + API + worker pela primeira vez
init:
    docker compose --profile app up -d --build
    @echo "Aguardando Postgres..."
    @docker compose exec -T postgres pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"

# Sobe toda a stack
up:
    docker compose --profile app up -d

# Derruba a stack (mantém volumes)
down:
    docker compose --profile app down

# Derruba a stack e APAGA volumes (CUIDADO)
down-v:
    docker compose --profile app down -v

# Tail dos logs
logs:
    docker compose --profile app logs -f --tail=100

# Instala deps Python (uv sync a partir de pyproject.toml + uv.lock)
api-install:
    cd apps/api && uv sync

# Roda migrations (alembic upgrade head)
api-migrate:
    cd apps/api && uv run alembic upgrade head

# Cria nova migration: `just api-revision "add foo"`
api-revision message:
    cd apps/api && uv run alembic revision --autogenerate -m "{{message}}"

# Sobe uvicorn em modo dev
api-run:
    cd apps/api && uv run uvicorn app.main:app --reload --port $API_PORT

# Sobe worker em foreground
worker-run:
    cd apps/api && uv run python -m app.jobs.runner

# Sobe api + worker + front em paralelo. Ctrl-C derruba tudo.
dev:
    @echo "api    -> http://localhost:$API_PORT"
    @echo "worker -> rodando em foreground"
    @echo "web    -> http://localhost:5173"
    @echo "Ctrl-C para parar."
    cd apps/api && uv run uvicorn app.main:app --reload --port $API_PORT &
    cd apps/api && uv run python -m app.jobs.runner &
    cd apps/web && npm run dev
    @wait

# Roda testes unitários
test:
    cd apps/api && uv run pytest -q

# Lint do backend (ruff check + formatação)
lint:
    cd apps/api && uv run ruff check . && uv run ruff format --check .

# Typecheck do backend (pyright)
typecheck:
    cd apps/api && uv run pyright app tests

# SAST de seguranca (bandit)
bandit:
    cd apps/api && uv run bandit -r app --severity-level medium

# Scan SAST com as regras do projeto (semgrep.yml); requer `pipx install semgrep`
semgrep:
    SEMGREP_SEND_METRICS=off semgrep scan --config semgrep.yml --error apps/api/app apps/web/src apps/web/e2e

# Audit de dependencias de producao do backend (pip-audit via uvx)
api-audit:
    cd apps/api && UV_PROJECT_ENVIRONMENT=.venv-audit uv sync --frozen --no-dev
    cd apps/api && uvx pip-audit@2.10.1 --path .venv-audit/lib/python3.12/site-packages

# Roda tudo que o CI roda: tests/lint/typecheck/bandit/semgrep do back
# + web typecheck/lint/audit + audit do back + schema + valida o docker compose
ci:
    @echo "==> tests"     && just test
    @echo "==> lint"      && just lint
    @echo "==> pyright"   && just typecheck
    @echo "==> bandit"    && just bandit
    @echo "==> semgrep"  && just semgrep
    @echo "==> web tsc"   && just web-typecheck
    @echo "==> web lint"  && just web-lint
    @echo "==> web audit" && just web-audit
    @echo "==> e2e"       && just e2e-mock
    @echo "==> py audit"  && just api-audit
    @echo "==> schema"    && just check-schema
    @echo "==> compose"   && just validate-compose

# Sobe a stack + Grafana/Tempo/Prometheus (profile observability)
up-obs:
    docker compose --profile observability --profile app up -d

# Typecheck do frontend (separado porque o nome bate com `typecheck` do backend)
web-typecheck:
    cd apps/web && npm run typecheck

# Lint do frontend (Biome)
web-lint:
    cd apps/web && npm run lint

# Audit de dependencias de producao do front
web-audit:
    cd apps/web && npm audit --omit=dev --audit-level=high

# Lint + auto-fix no frontend
web-lint-fix:
    cd apps/web && npm run lint:fix

# Confirma que o compose continua válido
validate-compose:
    docker compose config --quiet

# Instala deps Node
web-install:
    cd apps/web && npm install

# Vite dev server
web-dev:
    cd apps/web && npm run dev

# Build de produção (gera apps/web/dist)
web-build:
    cd apps/web && npm run build

# Regenera src/api/schema.d.ts a partir do OpenAPI do backend
web-types:
    cd apps/api && uv run python -m app.cli dump-openapi > openapi.json
    cd apps/web && npm run gen:api

# Verifica se schema.d.ts está em sync (roda automaticamente no pre-commit)
check-schema:
    bash scripts/check-schema-sync.sh

# E2E (Playwright). Sem API/DB no ar, os testes que dependem do backend sao pulados.
e2e:
    cd apps/web && npm run e2e

# E2E so com os specs mockados (nao precisa de API/DB) — e o que o CI roda
e2e-mock:
    cd apps/web && npm run e2e -- e2e/smoke.spec.ts e2e/auth-failure.spec.ts e2e/async-flow.spec.ts

# Sobe a stack e roda E2E contra a SPA servida pela API em :8000 (sobe e desce o compose)
e2e-full:
    docker compose --profile app up -d --build
    cd apps/web && E2E_BASE_URL=http://localhost:8000 npm run e2e; code=$$?; docker compose --profile app down; exit $$code

# Abre a web UI do Mailpit (precisa do compose up)
mail:
    @open http://localhost:8025 || xdg-open http://localhost:8025 || echo "Acesse http://localhost:8025"

# Abre psql dentro do container
psql:
    docker compose exec -T postgres psql -U $POSTGRES_USER -d $POSTGRES_DB

# Lista extensões instaladas
psql-extensions:
    docker compose exec -T postgres psql -U $POSTGRES_USER -d $POSTGRES_DB -c "\dx"

# Dispara um backup pontual para o R2
backup-now:
    ./scripts/backup.sh

# Lista backups no R2
backup-ls:
    rclone ls $RCLONE_REMOTE_NAME:$RCLONE_BUCKET/

# Prova de restauracao: backup local -> restore -> verificacao (exige Postgres + client no PATH)
test-restore:
    ./scripts/test-restore.sh

# Remove caches e artefatos locais
clean:
    find . -type d -name "__pycache__" -prune -exec rm -rf {} +
    find . -type d -name ".pytest_cache" -prune -exec rm -rf {} +
    find . -type d -name "node_modules" -prune -exec rm -rf {} +
    rm -rf apps/web/dist apps/api/.venv apps/api/.venv-audit apps/api/openapi.json