# Lean Monorepo — atalhos de DX.
# https://just.systems  (instale com `brew install just` ou `cargo install just`)
#
# .env é carregado automaticamente; variáveis ficam acessíveis como $VAR.

set dotenv-load

# A interpolação do Compose é global: sem GRAFANA_ADMIN_PASSWORD o `docker compose`
# recusa QUALQUER comando (até `down` e `psql`), mesmo sem o profile observability.
# Estes recipes usam um valor de validação quando a variável não existe no ambiente
# (o valor real continua valendo quando está setado). `up-obs` NÃO usa o fallback:
# subir o Grafana exige senha de verdade.
compose_env := 'GRAFANA_ADMIN_PASSWORD="${GRAFANA_ADMIN_PASSWORD:-validation-only}"'

default:
    @just --list

# Sobe Postgres + API + worker pela primeira vez
init:
    {{compose_env}} docker compose up -d --build
    @echo "Aguardando Postgres..."
    @{{compose_env}} docker compose exec -T postgres pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"

# Sobe toda a stack
up:
    {{compose_env}} docker compose up -d --build

# Derruba a stack (mantém volumes)
down:
    {{compose_env}} docker compose down

# Derruba a stack e APAGA volumes (CUIDADO)
down-v:
    {{compose_env}} docker compose down -v

# Tail dos logs
logs:
    {{compose_env}} docker compose logs -f --tail=100

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
# Alternativa ao stack em container: não rode os dois juntos (disputa a porta 8000).
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
    cd apps/api && uvx pip-audit@2.10.1 --path .venv-audit/lib/python3.13/site-packages

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
    docker compose --profile observability up -d

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

# Confirma que o compose continua válido. Sem .env, materializa um a partir do
# .env.example (nunca sobrescreve um .env existente) — `env_file: .env` é
# obrigatório. GRAFANA_ADMIN_PASSWORD vira valor de validação se ausente/vazio,
# porque a interpolação do Compose é global mesmo sem o profile observability.
validate-compose:
    @tmp=""; \
    if [ ! -f .env ]; then cp .env.example .env; tmp=1; fi; \
    trap '[ -n "$tmp" ] && rm -f .env' EXIT INT TERM; \
    GRAFANA_ADMIN_PASSWORD="${GRAFANA_ADMIN_PASSWORD:-validation-only}" docker compose config --quiet

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
# Semeia um admin determinístico: POST /users/enqueue-email é superuser-only, e o
# spec de job precisa de um superuser. E2E_ADMIN_EMAIL/E2E_ADMIN_PASSWORD
# sobrescrevem os defaults (o seed e o spec usam os mesmos).
e2e-full:
    {{compose_env}} docker compose up -d --build
    {{compose_env}} docker compose exec -T api python -m app.cli create-user "${E2E_ADMIN_EMAIL:-e2e-admin@example.com}" "${E2E_ADMIN_PASSWORD:-e2e-admin-password-123}" "E2E Admin" --superuser
    cd apps/web && E2E_BASE_URL=http://localhost:8000 E2E_ADMIN_EMAIL="${E2E_ADMIN_EMAIL:-e2e-admin@example.com}" E2E_ADMIN_PASSWORD="${E2E_ADMIN_PASSWORD:-e2e-admin-password-123}" npm run e2e; code=$?; {{compose_env}} docker compose down; exit $code

# Abre a web UI do Mailpit (precisa do compose up)
mail:
    @open http://localhost:8025 || xdg-open http://localhost:8025 || echo "Acesse http://localhost:8025"

# Abre psql dentro do container
psql:
    {{compose_env}} docker compose exec -T postgres psql -U $POSTGRES_USER -d $POSTGRES_DB

# Lista extensões instaladas
psql-extensions:
    {{compose_env}} docker compose exec -T postgres psql -U $POSTGRES_USER -d $POSTGRES_DB -c "\dx"

# Dispara um backup pontual para o R2
backup-now:
    ./scripts/backup.sh

# Lista backups no R2
backup-ls:
    rclone ls $RCLONE_REMOTE_NAME:$RCLONE_BUCKET/

# Prova de restauracao (backup -> restore -> verificacao) dentro do container `postgres`
test-restore:
    {{compose_env}} docker compose up -d --wait postgres
    {{compose_env}} docker compose run --rm --no-deps --entrypoint bash \
        -v "$PWD:/repo:ro" -w /repo \
        -e ENV_FILE=/dev/null \
        -e POSTGRES_HOST=postgres -e POSTGRES_PORT=5432 \
        -e POSTGRES_USER="${POSTGRES_USER:-app}" \
        -e POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-app}" \
        -e POSTGRES_DB="${POSTGRES_DB:-app}" \
        postgres /repo/scripts/test-restore.sh

# Remove caches e artefatos locais
clean:
    find . -type d -name "__pycache__" -prune -exec rm -rf {} +
    find . -type d -name ".pytest_cache" -prune -exec rm -rf {} +
    find . -type d -name "node_modules" -prune -exec rm -rf {} +
    rm -rf apps/web/dist apps/api/.venv apps/api/.venv-audit apps/api/openapi.json