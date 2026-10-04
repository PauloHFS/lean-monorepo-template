"""Modelos de 2FA: recovery codes (TOTP) e WebAuthn passkeys."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, LargeBinary, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UuidPK


class TotpRecoveryCode(Base):
    """Códigos de recuperação de uso único para quando o user perde o TOTP."""

    __tablename__ = "totp_recovery_codes"

    id: Mapped[UuidPK]
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code_hash: Mapped[str] = mapped_column(Text, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class UserPasskey(Base):
    """Credencial WebAuthn registrada para o user."""

    __tablename__ = "user_passkeys"

    id: Mapped[UuidPK]
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    credential_id: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, unique=True)
    public_key: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    sign_count: Mapped[int] = mapped_column(default=0, server_default="0")
    name: Mapped[str] = mapped_column(Text, nullable=False, default="passkey", server_default="passkey")
    transports: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)