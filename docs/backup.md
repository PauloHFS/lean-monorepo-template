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
`pg_dump`/`pg_restore` do host não alcança o banco. Além disso, o Coolify copia
apenas `docker-compose.yaml` e `.env` para `/data/coolify/applications/<uuid>/`
(não mantém um `git clone` completo nem os `.sh` no host, mas os scripts estão
dentro da imagem em `/app/scripts/`).

Para instalar os scripts no host da VPS e agendar o cron diário (3h30 UTC):

```bash
APP_DIR=/data/coolify/applications/<uuid>
API_CT=$(docker ps -qf name=api-<uuid>)
docker cp "${API_CT}:/app/scripts/backup.sh" "${APP_DIR}/scripts/backup.sh"
docker cp "${API_CT}:/app/scripts/restore.sh" "${APP_DIR}/scripts/restore.sh"
docker cp "${API_CT}:/app/scripts/test-restore.sh" "${APP_DIR}/scripts/test-restore.sh"
chmod +x "${APP_DIR}/scripts/"*.sh

# Teste manual (lê .env, docker-compose.yaml e COOLIFY_RESOURCE_UUID automaticamente):
cd "${APP_DIR}" && ./scripts/backup.sh
```

- `POSTGRES_CONTAINER=postgres` (no `.env`) ativa o modo container.
- `backup.sh` e `restore.sh` detectam automaticamente tanto `docker-compose.yml` quanto `docker-compose.yaml` (gerado pelo Coolify) e usam `COOLIFY_RESOURCE_UUID` como `COMPOSE_PROJECT_NAME` quando presente.
- Sem `POSTGRES_CONTAINER`, o script usa o modo host (`pg_dump` local contra `POSTGRES_HOST`/`POSTGRES_PORT`).
- O `.env` tem precedência, mas um valor **vazio** no `.env` não apaga o que veio do shell.
- O `docker compose exec` interpola o compose inteiro: `GRAFANA_ADMIN_PASSWORD` precisa estar no `.env`/ambiente.

Guia extraído do README. Índice e atalhos: [README](../README.md).
