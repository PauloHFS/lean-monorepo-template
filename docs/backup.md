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

### Modo container (deploy sem porta publicada no host)

No deploy do Coolify o compose não publica porta do Postgres no host, então o
`pg_dump`/`pg_restore` do host não alcança o banco. Com `POSTGRES_CONTAINER`
preenchido, os scripts rodam o dump **dentro** do container:

```bash
cd <diretório-de-deploy>
POSTGRES_CONTAINER=postgres POSTGRES_USER=app POSTGRES_DB=app \
BACKUP_COMPOSE_FILE=$PWD/docker-compose.yml \
BACKUP_ENCRYPT_PASSPHRASE=<senha> ./scripts/backup.sh
```

- `POSTGRES_CONTAINER` = nome do **serviço** no compose (`postgres`).
- `BACKUP_COMPOSE_FILE` = caminho do compose implantado (default `<repo>/docker-compose.yml`).
- Sem `POSTGRES_CONTAINER`, o script usa o modo host (`pg_dump` local contra `POSTGRES_HOST`/`POSTGRES_PORT`).
- O `.env` tem precedência, mas um valor **vazio** no `.env` não apaga o que veio do shell.
- O `docker compose exec` interpola o compose inteiro: `GRAFANA_ADMIN_PASSWORD` precisa estar no ambiente.
- Se o Coolify renomeou o projeto do compose, use `COMPOSE_PROJECT_NAME=<projeto>` (veja `docker compose ls`).

Guia extraído do README. Índice e atalhos: [README](../README.md).
