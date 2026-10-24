"""Tables of this module (`messaging_*`). See AGENTS.md."""

from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import BigInteger, DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, str_enum


class OutboxKind(StrEnum):
    SEND = "send"
    EDIT = "edit"


class OutboxStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


class OutboxMessage(Base):
    __tablename__ = "messaging_outbox"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Idempotency key chosen by the caller, e.g. "job_offer:12". Edits name the send they change.
    key: Mapped[str] = mapped_column(String(200), unique=True)
    kind: Mapped[OutboxKind] = mapped_column(str_enum(OutboxKind))
    edit_of: Mapped[str | None] = mapped_column(String(200))
    chat_id: Mapped[int] = mapped_column(BigInteger)
    text: Mapped[str] = mapped_column(Text)
    buttons: Mapped[list[Any] | None] = mapped_column(JSONB)
    status: Mapped[OutboxStatus] = mapped_column(
        str_enum(OutboxStatus), default=OutboxStatus.PENDING, index=True
    )
    attempts: Mapped[int] = mapped_column(default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
