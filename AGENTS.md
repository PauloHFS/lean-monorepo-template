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

- O backend roda Pyright em `strict` (`apps/api/pyrightconfig.json`, sem lista de `ignore`). Todo código novo passa em `uv run pyright app tests` com 0 erros; não reintroduza exclusões de arquivo nem `# type: ignore` sem motivo explícito.
- `AsyncSession.execute` é corrotina: isole o `await` (`(await session.execute(...)).mappings().first()`) antes de encadear `.mappings()`/`.first()`/`.scalar*()`. Encadear no `await` quebra em runtime.
- DML precisa de `cast(CursorResult[Any], await session.execute(...))` para ler `.rowcount`; libs sem stubs (instrumentação OTel) se normalizam na fronteira com `cast`, sem espalhar `Unknown` pelo app. A lib de passkey é `webauthn==3.0.1` (tipada, `py.typed`): importe os tipos direto, sem `cast`.
- TypeScript deve permanecer em modo strict e não usar `any`; prefira `unknown` com narrowing. O aviso do Biome sobre `any` não substitui essa regra.
- Toda rota nova deve declarar modelos Pydantic de entrada, `response_model` e tipos explícitos para respostas.
- O `response_model` é um **modelo Pydantic explícito**: `dict[str, Any]` vira `Record<string, never>` no TypeScript e apaga o contrato do front. Na fronteira use `model_validate` (entrada) e `model_dump(exclude_none=True)` (saída).
- Quando o shape da resposta não pode ganhar campos nulos ou listas vazias, use `response_model_exclude_unset=True`.
- `apps/web/src/api/schema.d.ts` é gerado. Nunca o edite manualmente; após mudar schemas ou rotas, rode `just web-types` e versione o resultado.
- Não duplique manualmente contratos que já existem em `src/api/types.ts` ou `src/api/endpoints.ts`. Use Zod para validação de formulários no frontend, não como substituto dos tipos da API.
- No front, os tipos vêm de `components["schemas"][...]` (reexportados em `src/api/types.ts`). Não redeclare shapes de resposta à mão.
- `scripts/check-schema-sync.sh` é o gate de contrato: compara o `schema.d.ts` versionado com o OpenAPI atual e falha se alguma **resposta de rota** virar `Record<string, never>`/`unknown`. Rode `just web-types && just check-schema` depois de mexer em rotas ou schemas.
- WebAuthn: as options chegam em base64url; converta para `BufferSource` com `src/lib/webauthn.ts` (`toRegistrationOptions`/`toAuthenticationOptions`) antes de `navigator.credentials`.

### Lint do frontend (Biome)

- O lint do front é o Biome (`apps/web/biome.json`) e roda como `npm run lint` = `biome check --error-on-warnings`: warning bloqueia igual a erro.
- As regras que importam estão em `error`: `noExplicitAny`, `noConsoleLog`, `useImportType`, `useExhaustiveDependencies`, `useAwait`, `noUnusedImports`, `noUnusedVariables`, `noUnusedFunctionParameters`, `noUndeclaredVariables`, `noNonNullAssertion`, `noParameterAssign`, `noUselessElse`.
- `useNamingConvention` fica `off`: o snake_case vem do contrato da API, não do estilo do código.
- `files.include` é `["**"]`. O glob `*.{ts,tsx,js,jsx,json}` do Biome 1.9.4 **não casa arquivos da raiz** — com ele, `vite.config.ts`, `playwright.config.ts`, `tailwind.config.js` e `postcss.config.js` escapavam do lint.
- `src/api/schema.d.ts` é gerado e fica fora do lint.
- Rode `just web-lint` antes de submeter; `just web-lint-fix` aplica as correções automáticas.

### Banco de dados

- Em runtime, use SQLAlchemy Core com `text()` e bind parameters, conforme a AD-012. Não use `session.query(Model)` nem queries ORM nas rotas.
- Nunca concatene entrada do usuário em SQL. Isso evita SQL Injection mesmo nos pontos de acesso SQL explícito.
- Modelos ORM (`Mapped[]`) servem ao schema e ao Alembic; queries de runtime servem ao Core.
- Gere migrations com `just api-revision`, revise o resultado e não edite uma migration já aplicada.

### Filas e jobs

- Jobs entram pela fila do Procrastinate (`send_email.defer_async(...)`), a mesma task que o worker executa. O `trace_context` viaja no payload (`inject_trace_context`).
- A tabela `background_jobs` é legada e **ninguém consome**: não grave enfileiramentos nela.
- `job_id` é o id do Procrastinate (inteiro), não um UUID.

### Testes

- Testes unitários não tocam Postgres (AD-008): o runner SQL é testado como texto, não executado.
- Validadores, criptografia e rate limiter têm testes de propriedades com Hypothesis (`apps/api/tests/test_properties_*.py`).
- bcrypt custa ~100 ms por hash: use `@settings(deadline=None, max_examples=...)` ou o Hypothesis vira fábrica de flakes.
- Não duplique em Python a semântica que mora no SQL; extraia só a parte pura (chave, decisão) e teste isso.

### E2E (Playwright)

- Specs vivem em `apps/web/e2e/` e rodam com `just e2e` (o `playwright.config.ts` sobe o Vite sozinho quando `E2E_BASE_URL` é a porta do Vite).
- Cenários de falha de autenticação e fluxos assíncronos usam `page.route` (mock): rodam sem API/DB e é isso que o CI executa (`just e2e-mock`).
- Spec que exige a API real deve **pular** quando ela não estiver disponível (`backendAvailable` em `e2e/helpers.ts`) — falhar por falta de stack esconde regressão real.
- `just e2e-full` sobe o compose e roda contra a SPA servida pela API em `:8000` (`E2E_BASE_URL=http://localhost:8000`).
- Use seletores acessíveis (`getByRole`/`getByLabel`); não crie `data-testid` novo.

### Observabilidade e tracing

- Tracing é OpenTelemetry com propagação W3C (`traceparent`); a configuração vem de `Settings` (`otel_*`, `sentry_*`), nunca de `os.environ` lido no import.
- Span manual existe nas fronteiras: enqueue de job e worker. O contexto de trace viaja no payload do job; jobs antigos sem `trace_context` continuam funcionando.
- Logs carregam `trace_id`/`span_id` do span corrente. Span inválido vira `None`, não string de zeros.
- `provider.shutdown()` no shutdown do app: sem flush, os spans morrem no container.

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

- O scan é local e offline: `semgrep scan --config semgrep.yml --error apps/api/app apps/web/src apps/web/e2e`. Não use `--config auto` — ele envia languages, frameworks e a URL do projeto ao registry e muda o resultado entre execuções.
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
| Fluxo E2E | `just e2e` (pula o que exige backend) · `just e2e-mock` (só mocks; é o que o CI roda) · `just e2e-full` (stack real) |
| Schema Pydantic, rota ou contrato OpenAPI | `just web-types && just check-schema` (o `check-schema` falha se alguma resposta de rota ficar sem contrato tipado) |
| Dependências Python ou npm | `just api-audit` e `just web-audit` |
| Qualquer alteração de código coberta pelas regras do `semgrep.yml` | `just semgrep` |

`just ci` inclui `just semgrep` (SAST), as auditorias de dependências e `just e2e-mock`; não inclui build do frontend, E2E contra a stack real, build Docker ou Trivy; rode esses checks quando a mudança os alcançar. O pre-commit não substitui `just ci`.
