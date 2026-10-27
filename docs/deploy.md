# Deploy: Coolify, produção e borda

Guia de deploy do template: o que o Coolify precisa (resource, env vars, domínio),
o checklist de produção, a troca para Postgres gerenciado, o backup nativo de
volume no R2 e o TLS com Cloudflare. O dump **lógico** do repo está em
[backup.md](backup.md); o índice com todos os guias está no
[README](../README.md).

---

## Checklist de produção

O repositório serve **HTTP puro**. **TLS é requisito de deployment**: coloque um reverse proxy/balanceador terminando HTTPS na frente da API. Sem TLS o cookie `Secure` não volta ao navegador e o HSTS não protege nada — a app não embute TLS e o repo não embute proxy (o caminho Coolify está logo abaixo; contrato em [architecture.md](architecture.md) (AD-036)).

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

O repo **não embute proxy**: a app sobe HTTP puro e o TLS termina no proxy do Coolify (Traefik v3.7 por padrão) ou no Cloudflare. Contrato de cabeçalhos, matriz de responsabilidades e limites em [architecture.md](architecture.md) (AD-036).

1. **Recurso**: build pack **Docker Compose**, Base Directory = raiz do repo, Docker Compose Location = `docker-compose.yml` — **só esse arquivo**. O Coolify roda `docker compose -f docker-compose.yml up -d` **sem `--profile`**, então `postgres`, `migrate`, `api` e `worker` sobem juntos; os perfis `dev` (mailpit) e `observability` continuam opcionais. O `docker-compose.override.yml` da raiz é **dev local** (publica `127.0.0.1:8000`/`127.0.0.1:5432`) e é ignorado aqui, porque o Coolify passa `-f` explícito: o artefato de deploy não publica porta nenhuma.
2. **Env vars**: cole na UI do Coolify (Developer view aceita formato `.env`). Copie o [`.env.example`](../.env.example) e troque o que é de prod:

   ```dotenv
   APP_ENV=prod
   SECRET_KEY=<32+ chars aleatórios>
   COOKIE_SECURE=true
   WEB_ORIGIN=https://app.example.com
   POSTGRES_PASSWORD=<senha forte>
   POSTGRES_SHARED_BUFFERS=2GB            # tuning por RAM (docs/tuning.md §2)
   POSTGRES_EFFECTIVE_CACHE_SIZE=6GB      # 8 GB de RAM; default do compose: 1GB/3GB
   DATABASE_URL=
   FORWARDED_ALLOW_IPS=172.16.0.0/12
   GRAFANA_ADMIN_PASSWORD=<qualquer valor>
   ```

   Preencha `DATABASE_URL` **ou** os `POSTGRES_*` (dentro do compose o host do banco é `postgres`); em Postgres gerenciado, defina `DB_SSLMODE=require`. `GRAFANA_ADMIN_PASSWORD` é exigida **mesmo sem** o profile `observability`: a interpolação `${GRAFANA_ADMIN_PASSWORD:?...}` do Compose é global. O `.env` versionado no repo **não é lido**: o Coolify gera/sobrescreve o `.env` do diretório de deploy e injeta `env_file: ['.env']` — a fonte é a UI.

   `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_USER` e `POSTGRES_DB` **não precisam** ir no `.env` do Coolify: o `environment:` do compose define `POSTGRES_HOST: postgres` e sobrescreve o `env_file` (o mesmo `POSTGRES_PASSWORD` do banco e do app é replicado pelo compose). E **não mude `API_INTERNAL_PORT`** (default 8000): o `expose:` do serviço `api` está acoplado a ele.
3. **Domínio**: só no serviço `api`, com o campo **Port = `8000`** (a porta **do container**). O `docker-compose.yml` não publica porta no host (só `expose:`), então o sufixo é obrigatório — sem ele o proxy procura a app na porta errada e devolve 502. No formulário do Coolify:
   - **Domain**: `app.example.com` (o sufixo `:8000` também é aceito no próprio campo);
   - **Port**: `8000` — **campo explícito**, porque não há `ports:` publicado para o Coolify detectar;
   - **Health Check Path**: `/api/v1/livez` (liveness; não toca o banco) ou vazio — a imagem já tem `HEALTHCHECK`.

   O proxy (Traefik) fala com o container pelo IP da rede Docker, nunca por `127.0.0.1`.
4. **Borda** — escolha uma:
   - **(a) Cloudflare com proxy (nuvem laranja)**: o Traefik precisa confiar nos ranges da Cloudflare para preservar o IP real — `--entrypoints.{http,https}.forwardedHeaders.trustedIPs=<ranges da CF>` (comandos custom do proxy são preservados pelo Coolify). Sem isso a app enxerga só o IP da borda. O certificado vem por **DNS-01** com Cloudflare (ver **TLS com Cloudflare (DNS-01)** abaixo) ou Cloudflare Origin Certificate: HTTP-01 não completa com o proxy da CF ligado.
   - **(b) Cloudflare Tunnel**: crie o recurso pelo template `cloudflared`, roteie o hostname para `http://localhost:80` e **desligue "Redirect HTTP to HTTPS"** no recurso (senão vira loop). Nesse caminho use `FORWARDED_ALLOW_IPS=127.0.0.1`; o ACME HTTP-01 do Traefik também não completa atrás do tunnel — use DNS challenge ou Origin Cert.
5. **Backup**: use o **backup agendado do Coolify** para S3/R2 (passo a passo em **Backup do banco no R2** abaixo). Os `../scripts/backup.sh` do repo são o caminho **fora** do Coolify (rodam no host) — o dump **lógico** está em [backup.md](backup.md). Como o compose de prod não publica a porta 5432, use o **modo container**: `POSTGRES_CONTAINER=postgres` faz o `pg_dump`/`pg_restore` rodarem por `docker compose exec -T` dentro do container do Postgres — sem `pg_dump` no host e sem porta publicada (`BACKUP_COMPOSE_FILE` aponta para o compose implantado).
6. **Gotchas do Coolify**:
   - não passa `--profile` (bug #6395) — por isso os serviços core não têm profile;
   - o deploy é marcado **FINISHED antes do healthcheck** (não espera `--wait`); a saúde real aparece depois;
   - `container_name`, nome do projeto e volumes são renomeados pelo Coolify;
   - Docker Compose não faz rolling update nem réplicas (v4.5.0; `scale`/`replicas` > 1 é rejeitado): cada deploy recria os containers, com downtime curto;
   - o status agregado do resource pode aparecer como `running:unknown` — é **cosmético** (a UI não parseia o health do compose); a saúde real se vê por serviço e por `/api/v1/healthz` (com `db=true`) + `docker compose ps`;
   - `${VAR:?}` é interpolado globalmente (ver `GRAFANA_ADMIN_PASSWORD` acima).
7. **O que NÃO fazer**:
   - não crie um resource separado para o Postgres — o `postgres` do compose é o banco, e o `pgdata` é o volume dele;
   - não adicione `ports:`/`expose` pela UI do Coolify;
   - não marque `migrate`/`worker` com health check — os dois já vêm com `healthcheck: disable: true` (one-shot e processo sem HTTP);
   - não troque o `docker-compose.yml` do repo por uma cópia editada no deploy: um compose por resource é a recipe de drift (o gate de boot do CI deixa de testar o que roda em prod — ver AD-036).
8. **Depois do deploy** (no host, no diretório de deploy):

   ```bash
   docker compose ps          # api/worker/pgbouncer running, migrate exited (0)
   docker compose logs migrate   # "alembic upgrade head" sem erro
   curl -s https://app.example.com/api/v1/healthz   # {"status":"ok","db":true}
   ```

   A saúde real é o `healthz` com `db=true` — o `docker compose ps` sozinho mostra só o processo vivo.
9. **Sem Coolify**: ponha um proxy próprio (Caddy/nginx) no host terminando TLS. O `docker-compose.yml` de deploy **não publica porta** — o proxy fala com o container pelo IP da rede Docker (como o Traefik do Coolify); se preferir `127.0.0.1:${API_PORT}`, suba com o override local (que publica `127.0.0.1:${API_PORT:-8000}:8000`). Use `FORWARDED_ALLOW_IPS=127.0.0.1`.

---

## Trocar para Postgres gerenciado (Neon/RDS/Cloud SQL)

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

**Backup/restore**: com o banco gerenciado o backup é do provedor (RDS tem PITR; no Neon, confirme a retenção do branching) e o backup de volume do Coolify deixa de se aplicar (não há volume). **A Coolify não tem PITR**; se o provedor escolhido também não tiver, o dump lógico do repo — `scripts/backup.sh` (`pg_dump -Fc` + sanidade `pg_restore --list`) e `just test-restore` — continua sendo o caminho de restore confiável (ver [backup.md](backup.md)). Atenção: `scripts/backup.sh`/`restore.sh`/`test-restore.sh` **não leem `DATABASE_URL` nem `DB_SSLMODE`** — só `POSTGRES_HOST/PORT/DB/USER/PASSWORD`; contra um Postgres gerenciado preencha os `POSTGRES_*` e exporte `PGSSLMODE=require` (o `libpq` respeita) ou ajuste os scripts.

---

## Backup do banco no R2

No nosso modelo (compose), o Postgres **não** é um database resource da Coolify: ele aparece como **persistent storage** da application (`pgdata`). Por isso o backup nativo da Coolify para ele é o **backup de volume** — um `tar.gz` do data dir, enviado ao S3/R2.

1. **Destinations/S3**: crie um token no **Cloudflare R2** com permissão **"Object Read & Write"** e configure o destination com **Name**, **Bucket**, **Region** (deixe o default), **Access Key** (`<access-key>`) e **Secret Key** (`<secret-key>`). O endpoint é separado em **Protocol** = `https`, **Host** = hostname do endpoint S3 **sem scheme** (ex.: `<conta>.r2.cloudflarestorage.com`), **Port** e **Path** (a Coolify usa o cliente MinIO `mc`).
2. **Backup schedule** do volume `pgdata`: escolha a frequência, o destination acima e, para consistência, ligue **"Stop during backup"** — a Coolify para os containers que usam o volume durante a cópia (downtime enquanto o backup roda). Sem isso o `tar.gz` do data dir pode sair inconsistente. Configure também a retenção (quantidade de backups, dias e storage máximo).
3. **Back up now**: executa uma cópia imediata, sem esperar o agendamento.
4. **Restore**: o restore do volume é **file-level** — exige o **mesmo major do Postgres** e o banco **parado**. Justamente por isso o caminho de restore **confiável** do repo é o dump **lógico**: `scripts/backup.sh` no host (`pg_dump -Fc`, sanidade `pg_restore --list`, cifra opcional), provado por `just test-restore` (roda em container, sem client no host) e pelo job `restore-test` do CI (ver "Backup (R2)" em [backup.md](backup.md)).

O backup **lógico** da Coolify (`pg_dump` + **"Import Backup"**) só existe para **databases gerenciados** (um recurso Database da Coolify) — não é o caminho do Postgres do compose. E **não há PITR** em nenhum dos dois caminhos: o restore devolve a última cópia, não um momento arbitrário entre execuções. Quem precisar de PITR precisa de outro provedor; o repo não oferece.

---

## TLS com Cloudflare (DNS-01)

O ACME **HTTP-01** padrão exige rota pública (não completa com o proxy laranja da Cloudflare nem atrás do tunnel). Para emitir via **DNS-01** no Traefik da Coolify:

- env `CF_DNS_API_TOKEN=<token do Cloudflare com permissão "Edit zone DNS">`;
- comando custom do proxy `--certificatesresolvers.letsencrypt.acme.dnschallenge.provider=cloudflare`.

---

Guia extraído do README. Índice e atalhos: [README](../README.md).
