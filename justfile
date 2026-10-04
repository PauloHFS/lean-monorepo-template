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

# Instala deps Python em venv local
api-install:
    cd apps/api && python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt

# Roda migrations (alembic upgrade head)
api-migrate:
    cd apps/api && . .venv/bin/activate && alembic upgrade head

# Cria nova migration: `just api-revision "add foo"`
api-revision message:
    cd apps/api && . .venv/bin/activate && alembic revision --autogenerate -m "{{message}}"

# Sobe uvicorn em modo dev
api-run:
    cd apps/api && . .venv/bin/activate && uvicorn app.main:app --reload --port $API_PORT

# Sobe worker em foreground
worker-run:
    cd apps/api && . .venv/bin/activate && python -m app.jobs.runner

# Sobe api + worker + front em paralelo. Ctrl-C derruba tudo.
dev:
    @echo "api    -> http://localhost:$API_PORT"
    @echo "worker -> rodando em foreground"
    @echo "web    -> http://localhost:5173"
    @echo "Ctrl-C para parar."
    cd apps/api && . .venv/bin/activate && uvicorn app.main:app --reload --port $API_PORT &
    cd apps/api && . .venv/bin/activate && python -m app.jobs.runner &
    cd apps/web && npm run dev
    @wait

# Roda testes unitários
test:
    cd apps/api && . .venv/bin/activate && pytest -q

# Lint do backend
lint:
    cd apps/api && . .venv/bin/activate && ruff check .

# Typecheck do backend (pyright)
typecheck:
    cd apps/api && . .venv/bin/activate && pyright app

# Roda tudo que o CI roda: testes + lint + typecheck do backend
# + typecheck + lint do front + valida o docker compose
ci:
    @echo "==> tests"    && just test
    @echo "==> lint"     && just lint
    @echo "==> pyright"  && just typecheck
    @echo "==> web tsc"  && just web-typecheck
    @echo "==> web lint" && just web-lint
    @echo "==> compose"  && just validate-compose

# Sobe a stack + Grafana/Tempo/Prometheus (profile observability)
up-obs:
    docker compose --profile observability --profile app up -d

# Typecheck do frontend (separado porque o nome bate com `typecheck` do backend)
web-typecheck:
    cd apps/web && npm run typecheck

# Lint do frontend (Biome)
web-lint:
    cd apps/web && npm run lint

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
    cd apps/api && . .venv/bin/activate && python -m app.cli dump-openapi > openapi.json
    cd apps/web && npm run gen:api

# Verifica se schema.d.ts está em sync (roda automaticamente no pre-commit)
check-schema:
    bash scripts/check-schema-sync.sh

# E2E (Playwright) contra a stack local
e2e:
    cd apps/web && npm run e2e

# Sobe stack + roda E2E (sobe e desce o compose)
e2e-full:
    docker compose --profile app up -d
    @just e2e
    @docker compose --profile app down

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

# Remove caches e artefatos locais
clean:
    find . -type d -name "__pycache__" -prune -exec rm -rf {} +
    find . -type d -name ".pytest_cache" -prune -exec rm -rf {} +
    find . -type d -name "node_modules" -prune -exec rm -rf {} +
    rm -rf apps/web/dist apps/api/.venv apps/api/openapi.json