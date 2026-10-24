"""Tables of this module (`business`, `business_*`). See AGENTS.md."""

from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, str_enum
from app.modules.businesses._schemas import BusinessStatus, Trade


class ProposalStatus(StrEnum):
    PENDING = "pending"
    AWAITING_PHONE = "awaiting_phone"
    CONFIRMED = "confirmed"
    SUPERSEDED = "superseded"


class Business(Base):
    __tablename__ = "business"

    id: Mapped[int] = mapped_column(primary_key=True)
    # None once the business is deleted, so the same chat can register again.
    telegram_chat_id: Mapped[int | None] = mapped_column(BigInteger, unique=True)
    phone: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[BusinessStatus] = mapped_column(
        str_enum(BusinessStatus), default=BusinessStatus.DRAFT
    )
    # The confirmed profile (ADR 0003): written only from a confirmed proposal.
    name: Mapped[str | None] = mapped_column(String(200))
    trade: Mapped[Trade | None] = mapped_column(str_enum(Trade), index=True)
    area: Mapped[str | None] = mapped_column(String(200))
    availability_text: Mapped[str | None] = mapped_column(Text)
    availability: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    pricing_text: Mapped[str | None] = mapped_column(Text)
    pricing: Mapped[list[Any] | None] = mapped_column(JSONB)  # PriceRule, amounts in minor units
    quoted_separately: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class BusinessProposal(Base):
    __tablename__ = "business_proposal"

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("business.id"), index=True)
    profile: Mapped[dict[str, Any]] = mapped_column(JSONB)
    source_text: Mapped[str] = mapped_column(Text)
    status: Mapped[ProposalStatus] = mapped_column(
        str_enum(ProposalStatus), default=ProposalStatus.PENDING
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
