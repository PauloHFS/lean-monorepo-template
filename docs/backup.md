# Backup e restore do banco

Dump lógico do Postgres: cifragem, retenção no R2 e restauração com prova.
No deploy do Coolify (sem porta publicada), o dump roda dentro do container.

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

Os scripts de backup/restore rodam no **host** (precisam de `pg_dump`/`pg_restore`/`psql` no PATH) e usam `flock` para não se sobrepor. Dentro do Coolify, o caminho é o backup agendado do Coolify para S3/R2 (ver [Implantar no Coolify](deploy.md)).

### Restauração (com prova)

```bash
just test-restore                              # backup -> restore -> verificação (roda em container, sem client no host)
../scripts/restore.sh <dump> --db meu_restore --dry-run
../scripts/restore.sh <dump> --db meu_restore --yes
```

`restore.sh` exige **alvo explícito** (`--db`/`POSTGRES_RESTORE_DB`) e `--yes`: nunca adivinha o banco de destino. `test-restore.sh` cria bancos de descarte (`<db>_restore_test_src/dst`), faz backup→restore e confere count, `to_regclass`, md5 do conteúdo, índice, PK e sequência — e só opera em banco com `restore_test` no nome. `just test-restore` sobe o `postgres` do compose e roda o script dentro desse container; não exige `psql`/`pg_dump`/`pg_restore` no host. O CI roda o mesmo script no job `restore-test`.

Para credenciais, prefira `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` de **Scoped Token** do R2 (apenas bucket de backup).

### Agendamento via Coolify (Scheduled Tasks — Recomendado)

Como o `docker-compose.yml` monta `./scripts:/app/scripts:ro` no container `postgres` e o Coolify injeta o `.env` nos serviços, você pode agendar o backup diretamente pela interface do Coolify (**Application -> Scheduled Tasks**), com histórico de execução e alertas sem precisar de `crontab` ou `rclone.conf` manual na VPS:

- **Name**: `Backup Postgres (Lógico)`
- **Command**: `/app/scripts/backup.sh`
- **Frequency**: `30 3 * * *` (diário às 03:30 UTC)
- **Container**: `postgres`
- **Timeout**: `300`

Para ativar criptografia e envio para o **Cloudflare R2**, basta definir no **Environment Variables** da aplicação no Coolify:
- `BACKUP_ENCRYPT_PASSPHRASE` (chave forte para cifrar em `.dump.enc`)
- `RCLONE_BUCKET` (nome do bucket no R2)
- `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID` e `R2_SECRET_ACCESS_KEY` (o `backup.sh` converte automaticamente para `RCLONE_CONFIG_R2_*` e instala `openssl`/`rclone` sob demanda no container Alpine).
- Quando `RCLONE_BUCKET` está vazio, os backups locais ficam salvos no volume persistente `/var/lib/postgresql/backups` (mantendo os últimos 14 dumps).

### Modo container via Host (alternativa via SSH/CLI)

No deploy do Coolify o compose não publica porta do Postgres no host, então o
`pg_dump`/`pg_restore` do host não alcança o banco. Com **"Preserve Repository"**
ativo na aplicação (ou copiando `scripts/` para `/data/coolify/applications/<uuid>/scripts/`),
você também pode rodar a partir do host da VPS:

```bash
cd /data/coolify/applications/<uuid> && ./scripts/backup.sh
```

- `POSTGRES_CONTAINER=postgres` (no `.env`) ativa o modo container quando rodado no host; quando rodado **dentro** do container `postgres` (ex.: Scheduled Task), o script detecta `/.dockerenv` + `pg_dump` local e executa diretamente via socket local.
- `backup.sh` e `restore.sh` detectam automaticamente tanto `docker-compose.yml` quanto `docker-compose.yaml` (gerado pelo Coolify) e usam `COOLIFY_RESOURCE_UUID` como `COMPOSE_PROJECT_NAME` quando presente.
- Sem `POSTGRES_CONTAINER`, o script usa o modo host (`pg_dump` local contra `POSTGRES_HOST`/`POSTGRES_PORT`).
- O `.env` tem precedência, mas um valor **vazio** no `.env` não apaga o que veio do shell.
- O `docker compose exec` interpola o compose inteiro: `GRAFANA_ADMIN_PASSWORD` precisa estar no `.env`/ambiente.

Guia extraído do README. Índice e atalhos: [README](../README.md).
