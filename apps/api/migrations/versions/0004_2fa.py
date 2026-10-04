"""2FA: TOTP cols em users + recovery codes + WebAuthn passkeys.

Revision ID: 0004_2fa
Revises: 0003_kv_cache
Create Date: 2026-10-03 00:00:00
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0004_2fa"
down_revision: Union[str, None] = "0003_kv_cache"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # TOTP em users
    op.execute("""
        ALTER TABLE users
          ADD COLUMN IF NOT EXISTS totp_enabled     BOOLEAN NOT NULL DEFAULT FALSE,
          ADD COLUMN IF NOT EXISTS totp_secret_enc  BYTEA,
          ADD COLUMN IF NOT EXISTS totp_confirmed_at TIMESTAMPTZ;
    """)

    # Recovery codes (uso único, hashed)
    op.execute("""
        CREATE TABLE IF NOT EXISTS totp_recovery_codes (
            id        UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            user_id   UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            code_hash TEXT NOT NULL,
            used_at   TIMESTAMPTZ
        );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_recovery_codes_user ON totp_recovery_codes (user_id);")

    # Passkeys (WebAuthn)
    op.execute("""
        CREATE TABLE IF NOT EXISTS user_passkeys (
            id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            credential_id BYTEA NOT NULL,
            public_key      BYTEA NOT NULL,
            sign_count    BIGINT NOT NULL DEFAULT 0,
            name          TEXT NOT NULL DEFAULT 'passkey',
            transports    TEXT,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_used_at  TIMESTAMPTZ
        );
    """)
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_passkeys_credential_id ON user_passkeys (credential_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_passkeys_user ON user_passkeys (user_id);")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS user_passkeys;")
    op.execute("DROP TABLE IF EXISTS totp_recovery_codes;")
    op.execute("""
        ALTER TABLE users
          DROP COLUMN IF EXISTS totp_enabled,
          DROP COLUMN IF EXISTS totp_secret_enc,
          DROP COLUMN IF EXISTS totp_confirmed_at;
    """)