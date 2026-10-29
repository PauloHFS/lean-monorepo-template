# Auth, 2FA e auditoria

Guia de autenticação do monorepo: sessão opaca com bcrypt, 2FA opcional (TOTP e Passkey) e a receita opt-in de auditoria. O índice com links e atalhos vive no README.

## 2FA — TOTP e Passkey (opcional, opt-in por usuário)

A tabela `users` tem colunas `totp_enabled`/`totp_secret_enc`. O usuário liga quando quiser.

**TOTP (Google Authenticator, 1Password, etc.):**
1. UI chama `/auth/2fa/totp/setup` → recebe `{secret, otpauth_uri}` (mostra QR)
2. UI chama `/auth/2fa/totp/confirm` com o primeiro código → TOTP ativo, recebe 10 recovery codes (mostrar 1x só)
3. Próximo login: senha OK → UI mostra campo de código → `/auth/2fa/verify` → cookie setado
4. Gestão em `/security`: `/auth/2fa/status` informa estado atual e códigos restantes; `/auth/2fa/totp/recovery-codes/regenerate` gera 10 novos códigos e `/auth/2fa/totp/disable` desativa o TOTP.

**Passkey (Touch ID, Face ID, chave de segurança):**
1. UI chama `/auth/2fa/passkey/register/options` → `navigator.credentials.create()` → `register/verify` (aceita `name` opcional do dispositivo)
2. Login 2FA (após senha): botão "Usar passkey" → `navigator.credentials.get()` → `/auth/2fa/passkey/login/verify` → cookie setado
3. Login direto sem senha (passwordless / discoverable credential): botão "Entrar com passkey" em `/login` → `/auth/2fa/passkey/passwordless/options` → `navigator.credentials.get()` → `/auth/2fa/passkey/passwordless/verify` → cookie setado
4. Gestão em `/security`: lista passkeys cadastradas e permite remover via `DELETE /auth/2fa/passkey/{passkey_id}`.

Recovery codes são aceitos no lugar do TOTP (caso o usuário perca o app).

---

## Auth

- Senha: **bcrypt** (custo 12, via lib `bcrypt` direto). Register e login rejeitam senhas acima de 72 **bytes UTF-8** na fronteira (Pydantic) e no hash — nada é truncado em silêncio.
- Sessão: **token opaco** em cookie `HttpOnly`, `SameSite=Lax`, `Secure` em prod.
- O cookie armazena o token cru; o banco guarda `sha256(token)` em `sessions.token_hash` (índice unique).
- Logout = `DELETE FROM sessions WHERE token_hash = …` → revogação instantânea.
- Endpoints em `/api/v1/auth/{register,login,logout,me}` e gestão de senha em `/api/v1/auth/password/{change,forgot,reset}` (com envio de link de recuperação via fila `email.send` e revogação de sessões ao redefinir/alterar senha).
- `/auth/login` responde no mesmo tempo para e-mail inexistente e senha errada (verificação contra um hash dummy de custo equivalente) e emite log de auditoria com um fingerprint do e-mail — nunca o endereço cru.
- **Autorização (ABAC):** toda regra de permissão vive em `apps/api/app/core/authz.py` (`Action` + `POLICIES` + `can/authorize/require/scope_for`). Endpoints nunca fazem `if user.is_superuser`; novas ações = novo `Action` + política + teste em `tests/test_authz.py`. Deny-by-default.
- `GET /users` e `POST /users/enqueue-email` são **superuser-only** (403 para os demais). `DELETE /users/{id}` permite o próprio usuário (em `/security`) ou um superuser (no `/dashboard`).

---

## Auditoria (receita opt-in)

O template **não** grava `created_by`/`updated_by` em todas as tabelas. O que existe por default:

- `created_at`/`updated_at` com default do banco. O trigger `set_updated_at()` existe **só** em `users`; as outras tabelas não têm `updated_at`.
- O audit de auth (`auth.login`/`auth.register`/`auth.logout`) é **log estruturado** (structlog): `outcome`, fingerprint sha256 truncado do e-mail e `trace_id`. Serve para observabilidade; **não** é trilha de auditoria consultável — não guarda IP/UA, não é transacional e não sobrevive ao delete do usuário.

Por que não `created_by`/`updated_by` por default: nas tabelas de hoje o ator é sempre o próprio usuário (register, 2FA, passkey) — a coluna seria tautológica; `DELETE /users/{id}` é hard delete com `ON DELETE CASCADE`, então a autoria morre junto (e `ON DELETE RESTRICT` quebraria o delete); nas tabelas de sistema (`kv_cache`, `rate_limits`, `job_rate_limits`, `dead_letters`) não há ator humano. A coluna só faz sentido em **tabelas de negócio futuras** (multi-tenant, admin editando recurso de outro). O padrão da indústria é timestamp automático + **uma** tabela de log opt-in com o ator vindo do contexto do request (Django `admin.LogEntry`, Rails PaperTrail, Laravel `spatie/laravel-activitylog`, Prisma/Supabase) — nenhum framework grava `created_by` em todas as tabelas por default.

Quando o projeto precisar de trilha real (append-only), a receita é **opt-in e por tabela auditada**. Ela não mexe no `UserOut` nem no contrato OpenAPI.

### 1. Tabela e trigger

Exemplo para uma tabela `pedidos` com PK `id UUID` (troque os nomes pela tabela real):

```sql
CREATE TABLE pedidos_audit (
  id        BIGSERIAL PRIMARY KEY,
  thing_id  UUID NOT NULL,
  action    TEXT NOT NULL CHECK (action IN ('insert', 'update', 'delete')),
  actor_id  UUID,                          -- NULL = sistema
  row_data  JSONB NOT NULL,                -- delta, não o before/after completo
  ts        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE FUNCTION audit_pedidos() RETURNS trigger AS $$
DECLARE
  v_actor UUID := current_setting('app.actor_id', true)::uuid;
BEGIN
  INSERT INTO pedidos_audit (thing_id, action, actor_id, row_data)
  VALUES (
    COALESCE(NEW.id, OLD.id),
    lower(TG_OP),
    v_actor,
    CASE TG_OP
      WHEN 'INSERT' THEN to_jsonb(NEW)
      WHEN 'DELETE' THEN to_jsonb(OLD)
      ELSE (
        SELECT COALESCE(jsonb_object_agg(n.key, n.value), '{}'::jsonb)
        FROM jsonb_each(to_jsonb(NEW)) AS n
        JOIN jsonb_each(to_jsonb(OLD)) AS o USING (key)
        WHERE n.value IS DISTINCT FROM o.value
      )
    END
  );
  RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_pedidos_audit
AFTER INSERT OR UPDATE OR DELETE ON pedidos
FOR EACH ROW EXECUTE FUNCTION audit_pedidos();
```

O trigger cobre `INSERT`/`UPDATE`/`DELETE`, não `SELECT` nem DDL. `app.actor_id` ausente vira `NULL` (sistema); não sete a variável com string vazia (o cast para `uuid` falha).

### 2. Ator: `SET LOCAL` na mesma transação

```sql
BEGIN;
SELECT set_config('app.actor_id', $1, true);  -- $1 = UUID do ator
-- <DML na tabela auditada>
COMMIT;
```

A transação explícita é obrigatória: `set_config(..., true)` é local e morre no fim da transação (no SQLAlchemy, `begin` → `set_config` → DML → `commit`). Com `DATABASE_URL_POOLER` e pgbouncer em `pool_mode=transaction` isso é seguro por construção, porque o estado nunca atravessa a transação (AD-037).

O ator vem do **servidor** — a sessão opaca validada no cookie —, **nunca** do body da request. Aceitar um `updated_by` enviado pelo cliente é deixar qualquer um forjar a trilha.

### 3. Privilégios

A role da aplicação precisa de `INSERT` (e `SELECT`, se for consultar) na tabela de auditoria, mas **não** de `UPDATE`/`DELETE`:

```sql
REVOKE UPDATE, DELETE ON pedidos_audit FROM app;
```

O trigger roda como invoker; sem o `INSERT` a DML na tabela auditada falha. Se a role da app for **owner** da tabela de auditoria, o `REVOKE` não a limita (owner pode se re-conceder) — crie a tabela com outro owner (o role das migrations) para o append-only valer.

### 4. LGPD e retenção

- Grave o **delta** (o que mudou), não before/after completo — duplicar PII no log amplia o escopo da LGPD. No `INSERT`/`DELETE` a linha inteira é o delta; omita colunas sensíveis (ex.: `to_jsonb(NEW) - 'campo_sensivel'`).
- Para identificar o titular use hash/fingerprint do e-mail (o repo já faz sha256 truncado no audit de auth), não o endereço cru.
- Retenção **menor** que a dos dados de negócio e documentada. A limpeza pode seguir o padrão dos jobs de cleanup do template quando `pg_cron` está disponível.

Guia extraído do README. Índice e atalhos: [README](../README.md).


## Sistema de Autorização ABAC (Padrão Ouro)

O projeto adota o padrão de Attribute-Based Access Control (ABAC) com **Single Source of Truth (SSOT)**:

1. **Definição de Regras (`apps/api/app/permissions/rules.py`):**
   - As regras são declarativas e residem exclusivamente neste arquivo.
   - Suporte a granularidade de campos (`fields`: colunas liberadas para leitura/mutação).
   - Condições avaliadas sobre o Ator, o Recurso e o Ambiente.

2. **Database Pushdown (`apps/api/app/permissions/sql.py`):**
   - Compila regras diretamente para predicados `WHERE` parametrizados com bind params (`to_sql()`).
   - Garante que listagens em lote retornem apenas o que o ator tem direito de enxergar antes de chegar na memória.

3. **Service Layer Desacoplada (`apps/api/app/services/`):**
   - Os endpoints HTTP apenas validam esquemas e repassam a execução para os serviços (`users`, `outbound_email`).
   - Toda checagem e mutação passa por `authorize()`.

4. **Frontend em Paridade Estrita (`apps/web/src/lib/permissions/`):**
   - O backend expõe o endpoint `GET /api/v1/permissions/me` com o manifesto de políticas do usuário.
   - O frontend avalia as mesmas regras usando o motor em `src/lib/permissions/engine.ts` e o hook `usePermissions()`.
   - O componente `<Can action="..." resource="...">` condiciona elementos visuais sem divergência de regra.
   - Paridade 100% garantida pela suíte de conformance compartilhada (`permissions_conformance.json`).
