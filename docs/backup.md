# Backup e Restore do Banco de Dados

Guia de backup e restore do Postgres: o backup nativo do Coolify (para produção) e os scripts do repositório (`backup.sh` / `restore.sh` / `test-restore.sh`).

---

## 1. Em Produção (Coolify): Backup Nativo no Recurso PostgreSQL

Como agora usamos a **arquitetura modular** (PostgreSQL como um **Resource Database nativo** no Coolify, desacoplado da aplicação):

> **O backup de produção pertence ao recurso do Banco de Dados no Coolify!**

### Como Configurar no Coolify:
1. Abra o recurso do seu banco de dados no Coolify (ex: `app-postgres`).
2. Acesse a aba **Backups**.
3. Configure o agendamento e armazenamento:
   - **Frequency**: `30 3 * * *` (todos os dias às 03:30 UTC).
   - **Retention**: Ex: `14 days` ou `30 days`.
   - **Storage Engine**: Selecione **S3 Storage** (Cloudflare R2, AWS S3, MinIO, etc.).
   - Preencha:
     - `Bucket Name`: seu bucket (ex: `meu-app-backups`)
     - `Endpoint`: URL do S3/R2 (ex: `https://<account_id>.r2.cloudflarestorage.com`)
     - `Access Key` e `Secret Key`
4. Clique em **Save** e depois em **Backup Now** para testar.
5. **Vantagens**:
   - Roda via `pg_dump` diretamente no container do banco.
   - Zero dependência da aplicação estar viva.
   - Histórico com status de sucesso/falha e notificações (Discord/Telegram/Email) gerenciadas pelo próprio Coolify.

---

## 2. Scripts do Repositório (`scripts/backup.sh` e `test-restore.sh`)

Os scripts em `scripts/` servem para:
- **Testes locais e CI**: Provar a integridade dos dados (`just test-restore`).
- **Automação via CLI / Cron do Host**: Se você quiser rodar dumps manuais fora da interface do Coolify.

### Como funciona o `backup.sh`:
1. `pg_dump -Fc -Z 9` → Gera dump compactado em formato custom com permissão `0600` + checksum sidecar `.sha256`.
2. **Validação de Sanidade**: Roda `pg_restore --list` (um dump corrompido ou truncado é descartado imediatamente antes de qualquer envio).
3. **Cifragem opcional**: Se `BACKUP_ENCRYPT_PASSPHRASE` estiver definida, cifra o arquivo com AES-256-CBC via PBKDF2 (`.dump.enc`).
4. **Envio / Retenção**: Se `RCLONE_BUCKET` estiver configurado, envia via `rclone` para o bucket remoto e limpa arquivos mais antigos que `BACKUP_KEEP_DAYS`. Se não, salva localmente em `BACKUP_DIR`.

---

## 3. Restauração e Prova de Integridade

### A. Prova Automatizada (`test-restore.sh`)
O teste de restauração não apenas valida se o arquivo descompacta, mas cria bancos temporários de origem e destino, faz o dump, restaura e compara **contagem de linhas, schemas, sequências e MD5 dos dados**:

```bash
just test-restore   # Sobe container isolado e roda a bateria completa de restauração
```
*(Esse mesmo teste roda no CI do GitHub Actions no job `restore-test`).*

### B. Restauração Manual com `restore.sh`
O script de restore possui travas de segurança rigorosas: exige alvo explícito e confirmação com `--yes`:

```bash
# Simular restauração sem tocar no banco:
./scripts/restore.sh caminho/do/arquivo.dump --db meu_db_destino --dry-run

# Executar a restauração real:
./scripts/restore.sh caminho/do/arquivo.dump --db meu_db_destino --yes
```

---

Guia extraído do README. Índice e atalhos: [README](../README.md).
