"""Tables of this module (`job`, `job_*`). See AGENTS.md."""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, str_enum
from app.modules.jobs._schemas import EventKind, JobStatus, OfferAnswer


class Job(Base):
    __tablename__ = "job"

    id: Mapped[int] = mapped_column(primary_key=True)
    token: Mapped[str] = mapped_column(String(32), unique=True)  # customer tracking link
    channel: Mapped[str] = mapped_column(String(20))
    status: Mapped[JobStatus] = mapped_column(str_enum(JobStatus), index=True)
    trade: Mapped[str] = mapped_column(String(32))
    when_text: Mapped[str] = mapped_column(Text)
    when: Mapped[dict[str, Any]] = mapped_column(JSONB)
    street_address: Mapped[str] = mapped_column(Text)
    unit: Mapped[str] = mapped_column(Text)
    city: Mapped[str] = mapped_column(String(200))
    access_notes: Mapped[str] = mapped_column(Text)
    maps_url: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    customer_name: Mapped[str] = mapped_column(String(200))
    customer_phone: Mapped[str] = mapped_column(String(40))
    business_id: Mapped[int | None] = mapped_column(ForeignKey("business.id"))
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    eta_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # offers went out
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class JobOffer(Base):
    __tablename__ = "job_offer"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("job.id"), index=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("business.id"))
    price_note: Mapped[str | None] = mapped_column(Text)
    options: Mapped[list[Any]] = mapped_column(JSONB)  # ArrivalOption
    answer: Mapped[OfferAnswer] = mapped_column(str_enum(OfferAnswer))
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class JobEvent(Base):
    __tablename__ = "job_event"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("job.id"), index=True)
    kind: Mapped[EventKind] = mapped_column(str_enum(EventKind))
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
