# Tuning e escala

Guia de operação para quem já colocou o template em produção e precisa decidir **quando e o que** aumentar. O alvo é o deploy padrão: 1 VPS com Coolify, PostgreSQL 18 no mesmo host, `api` + `worker` + `migrate` em Compose. A aplicação é stateless (a sessão é uma linha na tabela `sessions` e o cookie carrega só o token opaco), então escalar horizontalmente não exige mudança de código nem sticky session — o que muda é o desenho do deploy.

**Fora de escopo**: PITR (a Coolify não oferece; o caminho confiável de restore é o dump lógico do repo), multi-engine (Postgres é a única fonte de estado, por AD-001), multi-node/Kubernetes e tuning interno do planner além dos knobs abaixo. Números de capacidade são **estimativas** para dimensionar, não benchmark assinado: meça no seu workload antes de comprar hardware.

---

## 1. Dimensionar a VPS

Referência medida: 1 VPS **4 vCPU / 8 GB** com o Postgres no mesmo host entrega **300–800 RPS** de endpoint autenticado (session lookup ~0,1–0,5 ms + 1–3 ms de overhead Python), **50–500 usuários concorrentes** e **~5–50 mil MAU** em SaaS low-write, com banco quente de **10–20 GB**. As demais faixas são **regra prática** (metade/dobro da referência), não medição.

| VPS (vCPU / RAM) | RPS autenticado | Concorrentes | MAU (low-write) | Banco quente | Observação |
|---|---|---|---|---|---|
| 2 / 4 GB | ~150–400 (regra prática) | ~20–250 | ~2–25 mil | ~5–10 GB | Piso. Postgres e app disputam 4 GB; qualquer pico de login aperta a CPU. |
| 4 / 8 GB | 300–800 (referência medida) | 50–500 | 5–50 mil | 10–20 GB | Onde o template foi pensado para rodar. |
| 8 / 16 GB | ~600–1500 (regra prática) | ~100–1000 | ~10–100 mil | ~20–40 GB | Ainda 1 host, mas o backup de volume já dói (para o Postgres). |

Três números diferentes que costumam ser confundidos: **cadastros** (linhas na tabela) são baratos — milhões de linhas são triviais em storage e índice; **MAU** é quantos usuários únicos aparecem no mês; **concorrentes** é quantos fazem request ao mesmo tempo; **RPS** é a taxa agregada. Um SaaS com 50 mil cadastros pode ter 50 concorrentes e 100 RPS.

**Gatilhos para mudar de patamar** (sustentados por dias, não por um pico):

- disco do Postgres acima de **70%**;
- RAM do Postgres competindo com a app (pressão de OOM, swap);
- pool de conexões saturando (`pg_stat_activity` perto de `max_connections`, ou `cl_waiting > 0` no pgbouncer);
- o **backup parando a VPS** por tempo inaceitável ("Stop during backup" para o Postgres).
- CPU alta **só durante rajada de login** (ver bcrypt na seção 4).

Quando o gargalo é o banco, a ordem é: primeiro **pgbouncer/pool** (seção 3), depois **sair da caixa** (Postgres vertical ou gerenciado, seção 6), depois **réplica de leitura**, e só no fim **cache**. A API raramente é o primeiro gargalo; colocá-la em mais máquinas sem resolver o banco só move a fila.

---

## 2. Postgres

Knobs por RAM do host (fonte: documentação oficial do PostgreSQL; `shared_buffers` ≈ 25% da RAM, `effective_cache_size` ≈ 50–75%):

| RAM | `shared_buffers` | `effective_cache_size` | `work_mem` | `maintenance_work_mem` | `max_connections` |
|---|---|---|---|---|---|
| 4 GB | 1 GB | 3 GB | 16 MB | 256 MB | 40–50 |
| 8 GB | 2 GB | 6 GB | 32 MB | 512 MB | 50–60 |
| 16 GB | 4 GB | 12 GB | 64 MB | 1 GB | 80–100 (regra prática) |

Comuns a qualquer faixa: `max_wal_size=4GB`, `min_wal_size=1GB`, `checkpoint_completion_target=0.9`, `random_page_cost=1.1`, `effective_io_concurrency=200` (estes dois assumem SSD/NVMe), `log_min_duration_statement=500ms` e `jit=off` (OLTP curto; o JIT gasta mais do que economiza em query de milissegundos).

O que cada um faz, em uma linha:

- `shared_buffers`: cache de páginas do próprio Postgres; o primeiro lugar onde uma leitura bate.
- `effective_cache_size`: estimativa (não alocação) do cache total disponível — OS + `shared_buffers`; guia o planner a preferir índice.
- `work_mem`: memória **por operação** de sort/hash antes de derramar em disco; multiplica por conexão e por nó do plano — não exagere.
- `maintenance_work_mem`: memória de `VACUUM`, `CREATE INDEX` e afins.
- `max_connections`: teto de backends; cada um custa RAM. É o número que o pgbouncer existe para não precisar aumentar.
- `max_wal_size`/`min_wal_size`: quanto WAL acumular antes de forçar checkpoint; maior = menos checkpoints, mais disco.
- `checkpoint_completion_target`: espalha a escrita do checkpoint para não gerar pico de I/O.
- `random_page_cost`: custo relativo de leitura aleatória; em SSD, perto de 1,1.
- `effective_io_concurrency`: requisições de I/O simultâneas que o disco aguenta.
- `log_min_duration_statement`: loga query acima de 500 ms — o começo de qualquer investigação.
- `jit`: compilação em tempo de execução; desligado para OLTP curto.

**Onde aplicar**: já está no `command:` do serviço `postgres` do **compose**, versionado junto do projeto (sobrevive a recreate e o Coolify não sobrescreve). Os dois knobs que dependem da RAM vêm do `.env` (a tabela acima é a referência):

```yaml
  postgres:
    image: postgres:18-alpine
    command:
      - postgres
      - -c
      - shared_buffers=${POSTGRES_SHARED_BUFFERS:-1GB}
      - -c
      - effective_cache_size=${POSTGRES_EFFECTIVE_CACHE_SIZE:-3GB}
      - -c
      - work_mem=16MB
      - -c
      - maintenance_work_mem=256MB
      - -c
      - max_wal_size=4GB
      - -c
      - min_wal_size=1GB
      - -c
      - checkpoint_completion_target=0.9
      - -c
      - random_page_cost=1.1
      - -c
      - effective_io_concurrency=200
      - -c
      - log_min_duration_statement=500ms
      - -c
      - jit=off
```

- `POSTGRES_SHARED_BUFFERS` e `POSTGRES_EFFECTIVE_CACHE_SIZE`: defaults `1GB`/`3GB` no compose (valem de 2 GB de RAM para cima). Na VPS de 8 GB do repo, defina `2GB`/`6GB` no `.env`.
- `work_mem` e `maintenance_work_mem` estão fixos no valor da faixa de 4 GB (`16MB`/`256MB`) — suba-os no `command:` se a sua faixa for maior.
- `max_connections` fica no default (100): o pgbouncer existe justamente para não precisar subir esse teto, e a API sem pooler ainda pode abrir `DB_POOL_SIZE` + `DB_MAX_OVERFLOW` = 30 conexões por processo.

**Não use `ALTER SYSTEM`** para isso: o valor fica preso no `postgresql.auto.conf` dentro do volume `pgdata`, fora do Git, e some/diverge quando o volume é recriado ou o banco é restaurado em outro host. `command:` é a fonte de verdade versionada.

**`pg_stat_statements`** é o que permite ranquear query por tempo total. Exige `shared_preload_libraries=pg_stat_statements` **no start** (mesma via `command: postgres -c shared_preload_libraries=pg_stat_statements`) e `CREATE EXTENSION pg_stat_statements` uma vez. O custo é memória compartilhada pequena e um overhead por statement (baixo, mas não zero) — vale a pena em qualquer produção; sem ele você mede conexão, não query.

---

## 3. pgbouncer

**Quando ligar**: quando a soma das conexões do app chega perto de `max_connections`. Cada processo do uvicorn pode abrir até `pool_size + max_overflow` (hoje **10 + 20 = 30**), mas a conta de trabalho com o pool parcialmente quente é da ordem de **~15 por processo**. Com **4 workers** de uvicorn + o worker do Procrastinate, isso dá **~75 conexões** contra um `max_connections=100` — e **8 workers estoura**. Além disso, cada worker novo multiplica o pool: o número de conexões cresce com workers × (pool + overflow), não com a carga.

Knobs (o outro agente implementa no compose; estes são os valores de referência):

| Knob | Valor | Por quê |
|---|---|---|
| `pool_mode` | `transaction` | Uma conexão do servidor é devolvida ao pool a cada transação; é o modo que faz sentido para HTTP. |
| `max_client_conn` | 1000 | Teto de clientes (app) conectados ao pgbouncer. |
| `default_pool_size` | 20–30 | Conexões por par (banco, usuário) no servidor. |
| `max_db_connections` | 50 | Teto por banco — o número que precisa caber em `max_connections`. |
| `min_pool_size` | 2–5 | Conexões mantidas quentes. |
| `reserve_pool_size` / `reserve_pool_timeout` | 5 / 5 | Reserva para quando o pool principal enche. |
| `query_wait_timeout` | 30–60 | Quanto uma query espera por conexão livre antes de falhar. |
| `ignore_startup_parameters` | `extra_float_digits` | Parâmetro que o cliente manda e o pooler não repassa. |
| `auth_type` | `scram-sha-256` | Compatível com o `pg_hba` do compose. |
| `max_prepared_statements` | 200 (default desde 1.24) | Resolve prepared statements do asyncpg em transaction mode. |

**Incompatibilidades do `transaction` mode** — o pooler não garante que você fique na mesma conexão entre transações:

| Recurso | Transaction mode | Consequência |
|---|---|---|
| `LISTEN` | **nunca** | Falha **silenciosa**: o `LISTEN` “funciona” e nunca notifica. O worker do Procrastinate depende de `LISTEN/NOTIFY` — **worker e Alembic nunca vão pelo pooler**. |
| `SET` / `RESET` de sessão | nunca | O estado vaza/perde entre transações. |
| Advisory lock | nunca | A sessão dona do lock pode ser outra na volta. |
| Temp table com `PRESERVE ROWS` | nunca | Some com a troca de conexão. |
| `SET LOCAL` | ok | Vale só dentro da transação corrente. |

Só a **API** usa o pooler, via DSN separada (`DATABASE_URL_POOLER`). Sem essa env, o app fala direto no Postgres — comportamento padrão do template. **`worker` e `migrate` sempre no endpoint direto**, senão o `LISTEN` do Procrastinate morre em silêncio (o worker fica vivo e não acorda) e o Alembic pode rodar DDL em conexões trocadas.

**Depois de DDL** (migration aplicada por fora do pooler), emita `RECONNECT` no console admin do pgbouncer. Sem isso o pooler mantém o plano em cache e o próximo acesso falha com `cached plan must not change result type`.

**A armadilha do `max_connections`**: o teto real não é o do app. Some **pooler** (`max_db_connections`) + **worker** (conexão persistente, fora do pooler) + **`migrate`** (one-shot, mas abre conexão) + acesso administrativo. Se `max_connections=100` e `max_db_connections=50`, sobram 50 para worker, migrate e psql — e o pg_cron/cleanup entra nessa conta também.

---

## 4. Backend

**Workers do uvicorn**: regra prática é **1 worker por core** (4 vCPU → 4). O entrypoint roda **1 processo hoje** (não passa `--workers`). Para I/O-bound, worker extra é desperdício de RAM e **multiplica o pool** — cada worker tem o próprio pool de conexões. Meça antes de subir: se a CPU do `api` não satura e o tempo está no banco, mais worker só aumenta a pressão no Postgres. Subir workers exige editar o entrypoint (fora do escopo deste guia de doc).

**Pool do app**:

| Cenário | `db_pool_size` | `db_max_overflow` | Observação |
|---|---|---|---|
| **Com** pgbouncer na frente | 5 | 5–10 | O pool do app é a 2ª camada; 10/20 é generoso demais e só ocupa `max_client_conn`. |
| **Sem** pgbouncer | 10 | 20 | Default do template (`db_pool_size=10`, `db_max_overflow=20`). |
| `db_pool_timeout` | 30 s | — | Tempo esperando conexão livre antes de erro. |
| `pool_pre_ping` | `True` (fixo) | — | Descarta conexão morta antes de usar; já ligado no engine. |
| `pool_recycle` | — | — | Defina (ex.: 300 s, regra prática) quando há pgbouncer na frente: reiniciar o pooler invalida as conexões do app. |

**bcrypt custa CPU de propósito**: cost **12** leva **~100–160 ms por hash**; em ~3 vCPU são **~12 hashes/s** no total. O rate limit de login (**IP 5/60 s + conta 10/300 s**) mantém o login normal longe desse teto — só uma rajada de **credential stuffing** aperta a CPU. Não baixe o cost para “ganhar performance”: o rate limit é a proteção, e abaixo de 12 o custo de quebrar hash offline cai junto.

**Timeouts**: `db_pool_timeout=30` (acima). `uvicorn` mantém **keep-alive de 5 s** (default) — ok atrás de proxy. Se o proxy do Coolify/Cloudflare tem timeout menor que isso, o keep-alive é irrelevante; se for maior, 5 s evita segurar conexão ociosa.

---

## 5. Medir e decidir

**Conexões e espera** — quem está esperando o quê:

```sql
SELECT state, wait_event_type, wait_event, count(*)
FROM pg_stat_activity
WHERE datname = current_database()
GROUP BY 1, 2, 3
ORDER BY 4 DESC;

SHOW max_connections;
```

Procure: muito `idle` (pool grande demais para a carga), `active` com `wait_event` de I/O ou lock, e o total perto de `max_connections`.

**Cache hit** — se o Postgres está lendo do disco:

```sql
SELECT datname,
       blks_hit, blks_read,
       round(100.0 * blks_hit / nullif(blks_hit + blks_read, 0), 2) AS hit_pct
FROM pg_stat_database
WHERE datname = current_database();
```

`hit_pct` abaixo de ~99% em regime (regra prática) é sinal de cache insuficiente (subir `shared_buffers`/RAM) ou de índice faltando (aí o `pg_stat_statements` mostra a query).

**Queries** (com `pg_stat_statements` habilitado):

```sql
SELECT calls, round(total_exec_time::numeric, 1) AS total_ms,
       round(mean_exec_time::numeric, 2) AS mean_ms, query
FROM pg_stat_statements
ORDER BY total_exec_time DESC
LIMIT 20;
```

Ranqueie por **tempo total**, não só por média: uma query de 2 ms chamada 10 mil vezes pesa mais que uma de 500 ms chamada uma vez.

**pgbouncer** (console admin, `psql -p 6432 pgbouncer`):

```text
SHOW POOLS;      -- cl_waiting > 0 = faltou pool
SHOW STATS;      -- throughput e tempo de espera
SHOW SERVERS;    -- conexões ao Postgres
SHOW CLIENTS;    -- conexões do app
SHOW CONFIG;     -- valores efetivos
RECONNECT;       -- após DDL
PAUSE; RESUME;   -- manutenção
RELOAD;          -- recarrega a config
```

**Sinal → significado → ação**:

| Sinal | Significado | Ação |
|---|---|---|
| `cl_waiting > 0` no `SHOW POOLS` | Cliente esperando conexão do pooler | Aumentar `default_pool_size` **ou** reduzir o pool do app |
| `pool_timeout` estourando na app | O pool do app não conseguiu conexão no prazo | Idem; verificar se o pooler está saturado antes de subir o pool |
| Conexões do app perto de `max_connections` | workers × (pool + overflow) + worker sem folga | Ligar/ajustar pgbouncer; reduzir `pool_size` atrás dele |
| `hit_pct` baixo | Cache insuficiente ou índice faltando | Subir RAM/`shared_buffers`; investigar query no `pg_stat_statements` |
| Disco do PG > 70% | WAL, bloat ou crescimento real | `VACUUM`/`pg_repack` se for bloat; senão mover o banco ou aumentar disco |
| RAM do PG competindo com a app | Os 8 GB não cabem os dois | Mover o Postgres para fora da caixa (seção 6) |
| Backup demora e para a VPS | "Stop during backup" no volume | Backup lógico (`scripts/backup.sh`) ou banco gerenciado |
| CPU do `api` alta só em login | bcrypt sob credential stuffing | O rate limit já limita; se persistir, mais vCPU ou proteção de borda |

---

## 6. Ordem de investimento + limites da plataforma

1. **Pool/pgbouncer** — o primeiro gargalo real é conexão, não CPU. Ajustar o pool do app e pôr o pgbouncer na frente da API custa pouco e compra muito.
2. **Postgres vertical ou gerenciado** — mais RAM/CPU para o banco, ou tirar o banco da VPS (Neon/RDS/Cloud SQL). O app já aceita `DATABASE_URL` (precedência sobre `POSTGRES_*`) e `DB_SSLMODE`.
3. **Réplicas de leitura** — só quando a leitura é o gargalo e o write já está resolvido. Não há código de roteamento no template: é mudança de deploy e de acesso.
4. **Cache** — último recurso. Cache é estado duplicado e invalidação; o Postgres já é a fonte única e o hit ratio alto costuma resolver antes.

**A alavanca é o banco, nunca a API.** Como a API é stateless, colocá-la em outra máquina é seguro; mas sem resolver o Postgres você só distribui a mesma fila.

### O que a Coolify v4.5.0 não dá

- **Rolling update nem réplicas** em Compose: `scale`/`replicas` > 1 é rejeitado; cada deploy recria os containers e há **downtime curto**.
- **Deploy marcado FINISHED antes do healthcheck**: o painel diz que terminou antes de a app estar saudável; confirme por `/api/v1/healthz` (`db=true`) e `docker compose ps`.
- **Sem PITR**: o restore devolve a última cópia.
- **Saúde por resource é cosmética**: o status agregado pode aparecer `running:unknown` porque a UI não parseia o health do compose.

### O que ela dá

- **Backup nativo de Database** (S3/R2 via `pg_dump`), configurável direto na aba Backups do recurso PostgreSQL (com agendamento cron, sem derrubar o banco e sem "Stop during backup");
- **Backup de volume** (S3/R2 para outros serviços);
- **proxy e certificados** (Traefik), inclusive DNS-01;
- **log drains**;
- **Sentinel**.

O backup nativo do Coolify para Databases gera dumps lógicos via `pg_dump` para o R2/S3. Em paralelo, o repositório mantém seus scripts de restauração e prova de integridade (`scripts/backup.sh`, `restore.sh` e `test-restore.sh`), provados por `just test-restore` e pelo job `restore-test` do CI.

### Postgres gerenciado e serverless

- **Alembic e worker precisam de `?sslmode=require` dentro do `DATABASE_URL`**: o `apply_sslmode` só cobre o engine da API; esses dois consumidores usam a DSN crua.
- **Neon (serverless)**: o pooler vem gerenciado, mas toda request autenticada paga **RTT (30–100+ ms cross-region)**, o **cold start** (desligue scale-to-zero) e o **endpoint pooler quebra o worker** (transaction mode + `LISTEN`) — worker no endpoint **direct**.
- **RDS** tem PITR; **Cloud SQL** tem read pools.
- **Custo escondido**: sem peering/VPN, cada query paga RTT público. Banco no mesmo host é mais rápido; banco fora da VPS é mais caro por request e mais seguro contra OOM.

### Postgres no mesmo host

Simples e rápido (sem RTT), mas o banco é o gargalo e divide a RAM com a app; o backup de volume exige **parar o Postgres**. É o ponto de partida do template, não o destino final.

---

## 7. Checklist antes de aumentar a VPS

- [ ] Disco do Postgres < 70%; sem bloat evidente (`VACUUM`/`pg_repack` considerados).
- [ ] `pg_stat_activity` sem fila em `wait_event` de I/O/lock; conexões com folga em `max_connections`.
- [ ] pgbouncer: `cl_waiting` = 0 e `SHOW STATS` estável; worker e migrate **fora** do pooler.
- [ ] `hit_pct` ≥ ~99% em regime; top queries do `pg_stat_statements` revisadas.
- [ ] CPU do `api` não satura; se satura só em login, o rate limit está ativo (IP 5/60 s + conta 10/300 s).
- [ ] RAM do host sem swap/OOM; banco quente dentro da faixa da tabela da seção 1.
- [ ] Backup recente **e** restore provado (`just test-restore`); janela de backup aceitável.
- [ ] Se o gargalo é conexão: ajustar pool/pgbouncer **antes** de comprar vCPU.
- [ ] Se o gargalo é RAM/disco do banco: avaliar mover o Postgres para fora antes de aumentar a app.
