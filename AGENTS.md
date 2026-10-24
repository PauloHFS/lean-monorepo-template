# AGENTS.md — Governança de IA para o Lean Monorepo

## 1. Escopo e fontes de verdade

Este arquivo se aplica à raiz do repositório e a todos os diretórios abaixo dela.

- `README.md`: setup, comandos e visão geral.
- `docs/architecture.md`: decisões arquiteturais vigentes (ADRs).
- Manifests e configurações: versões e comandos efetivamente instalados.
- Em caso de conflito, a ADR vigente e o código executável prevalecem. Atualize a documentação correspondente junto com a mudança; não contorne a arquitetura existente.

## 2. Arquitetura

- **Backend (`/apps/api`)**: Python 3.12 gerenciado por `uv`, FastAPI, Pydantic v2, SQLAlchemy 2.0 assíncrono/Core, Alembic, Procrastinate e PostgreSQL.
- **Frontend (`/apps/web`)**: TypeScript strict, React 18, Vite, Tailwind CSS, Biome e tipos gerados do OpenAPI.
- **Princípio arquitetural**: PostgreSQL é a única fonte de estado do backend. Cache, filas, sessões e rate limiting pertencem ao PostgreSQL; não introduza Redis, Celery ou outro serviço sem uma nova ADR.
- **Princípio de interface**: toda rota nova possui contrato Pydantic de entrada e saída; o frontend consome os tipos gerados pelo OpenAPI.

## 3. Regras estritas de geração de código

### Dependências

- Antes de adicionar um pacote npm ou PyPI, confirme no registro oficial a existência, a versão, a procedência, a licença e a manutenção do projeto.
- Prefira a biblioteca padrão, uma dependência já instalada ou um helper local. Não crie abstração ou dependência especulativa.
- O gerenciador de pacotes Python é o `uv`: dependências ficam em `apps/api/pyproject.toml` (pins exatos) e as versões resolvidas em `apps/api/uv.lock`. Não reintroduza `pip install`, `requirements.txt` nem venv manual.
- Use `uv sync` para preparar `apps/api/.venv` e `uv run <comando>` para executar ferramentas e scripts. Em CI use `uv sync --locked`; rode `uv lock` e versione o `uv.lock` junto de qualquer mudança no `pyproject.toml`.
- Mantenha o lockfile `apps/web/package-lock.json` atualizado ao mexer em dependências npm.
- Rode a auditoria após mudar dependências: `just api-audit` (pip-audit via `uvx`, dependências de produção do backend) e `just web-audit` (npm audit de produção).

### Tipagem e contratos

- Funções Python novas ou alteradas devem ter type hints completos. Não amplie a lista de exclusões do Pyright e não adicione `type: ignore` sem motivo explícito.
- TypeScript deve permanecer em modo strict e não usar `any`; prefira `unknown` com narrowing. O aviso do Biome sobre `any` não substitui essa regra.
- Toda rota nova deve declarar modelos Pydantic de entrada, `response_model` e tipos explícitos para respostas.
- `apps/web/src/api/schema.d.ts` é gerado. Nunca o edite manualmente; após mudar schemas ou rotas, rode `just web-types` e versione o resultado.
- Não duplique manualmente contratos que já existem em `src/api/types.ts` ou `src/api/endpoints.ts`. Use Zod para validação de formulários no frontend, não como substituto dos tipos da API.

### Banco de dados

- Em runtime, use SQLAlchemy Core com `text()` e bind parameters, conforme a AD-012. Não use `session.query(Model)` nem queries ORM nas rotas.
- Nunca concatene entrada do usuário em SQL. Isso evita SQL Injection mesmo nos pontos de acesso SQL explícito.
- Modelos ORM (`Mapped[]`) servem ao schema e ao Alembic; queries de runtime servem ao Core.
- Gere migrations com `just api-revision`, revise o resultado e não edite uma migration já aplicada.

### Segurança

- Preserve a autenticação vigente: sessão opaca revogável em cookie `HttpOnly`, hash de senha com `bcrypt` e 2FA opcional por TOTP e WebAuthn. JWT e Argon2 não fazem parte da arquitetura atual; não os introduza sem ADR.
- Valide entrada na fronteira, use bind parameters no SQL e preserve as proteções contra XSS existentes no React e na API.
- Nunca versione `.env`, credenciais, tokens ou chaves. Use `.env.example` apenas para nomes de variáveis sem segredos.

### SAST automatizado (Semgrep)

As regras acima que dá para checar mecanicamente estão em `semgrep.yml` (raiz). `just semgrep` roda o gate local; o CI roda o mesmo scan no job `sast`.

| Regra (`semgrep.yml`) | Regra que ela cobre |
|---|---|
| `no-orm-query-in-routes` | AD-012: runtime usa Core, nunca `session.query()`/`select()` ORM |
| `no-dynamic-sql-text` | `text()` recebe literal; entrada do usuário nunca entra no SQL |
| `fastapi-response-model-required` | Toda rota declara `response_model` |
| `no-wildcard-cors` | CORS sem origem curinga |
| `ts-no-explicit-any` | TypeScript strict, sem `any` |

- O scan é local e offline: `semgrep scan --config semgrep.yml --error apps/api/app apps/web/src`. Não use `--config auto` — ele envia languages, frameworks e a URL do projeto ao registry e muda o resultado entre execuções.
- Semgrep é ferramenta de análise, não dependência da aplicação: mantenha fora de `apps/api/pyproject.toml` e instale com `pipx install semgrep` (ou rode via `uvx semgrep`).
- Ao criar, alterar ou remover uma regra, atualize `semgrep.yml` e esta tabela na mesma mudança.
- Falso positivo legítimo: suprima com `# nosemgrep: <rule-id>` na linha ou na linha anterior e explique o motivo.

## 4. Fluxo de trabalho

1. **Investigue**: leia o código relevante, o `README.md` e as ADRs afetadas; verifique todos os chamadores de uma função antes de alterá-la.
2. **Planeje**: antes de editar, apresente um plano curto com objetivo, arquivos afetados, decisões e validação. Para mudanças amplas, destrutivas ou que alterem arquitetura, autenticação, contratos ou dependências, aguarde aprovação explícita.
3. **Implemente**: faça a menor mudança completa que atenda ao objetivo, sem refatorações ou formatações não relacionadas.
4. **Valide**: rode os checks correspondentes e registre qualquer comando que não possa ser executado por indisponibilidade do ambiente.
5. **Commit**: quando solicitado, mantenha o commit isolado por assunto e marque-o como `[AI-assisted] feat(api): ...`. Não faça commit ou push sem pedido explícito.

## 5. Validação local

Use a menor matriz que cubra a mudança e rode `just ci` antes de submeter alterações de código:

| Mudança | Checks necessários |
|---|---|
| Backend | `just test && just lint && just typecheck` |
| Auth, segurança ou código sensível |Checks anteriores + `just bandit` |
| Frontend | `just web-typecheck && just web-lint` |
| Build, bundle ou rotas do frontend | Checks do frontend + `just web-build` |
| Fluxo E2E | `just e2e` ou `just e2e-full` |
| Schema Pydantic, rota ou contrato OpenAPI | `just web-types && just check-schema` |
| Dependências Python ou npm | `just api-audit` e `just web-audit` |
| Qualquer alteração de código coberta pelas regras do `semgrep.yml` | `just semgrep` |

`just ci` inclui `just semgrep` (SAST) e as auditorias de dependências, mas não inclui build do frontend, E2E, build Docker ou Trivy; rode esses checks quando a mudança os alcançar. O pre-commit não substitui `just ci`.
