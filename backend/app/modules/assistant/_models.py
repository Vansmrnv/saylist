"""Tables of this module (`assistant_*`). See AGENTS.md."""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Conversation(Base):
    """One per seller address. The seam for cross-channel identity: later this row points at
    a seller instead of being the identity itself (see `_identity.py`)."""

    __tablename__ = "assistant_conversation"
    __table_args__ = (UniqueConstraint("channel", "external_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    channel: Mapped[str] = mapped_column(String(32))
    external_id: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Turn(Base):
    """One inbound message and everything it caused: the model transcript and the replies."""

    __tablename__ = "assistant_turn"
    __table_args__ = (UniqueConstraint("conversation_id", "inbound_message_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    # The (conversation_id, inbound_message_id) unique index also serves lookups by conversation.
    conversation_id: Mapped[int] = mapped_column(ForeignKey("assistant_conversation.id"))
    inbound_message_id: Mapped[str] = mapped_column(String(200))
    inbound: Mapped[dict[str, Any]] = mapped_column(JSONB)
    # Anthropic-format messages of this turn: starts with the seller (user), ends with the
    # assistant. Model responses are stored exactly as returned, thinking blocks included.
    transcript: Mapped[list[Any]] = mapped_column(JSONB)
    replies: Mapped[list[Any]] = mapped_column(JSONB)
    failed: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
