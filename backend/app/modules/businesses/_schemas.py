from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Day = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


class Trade(StrEnum):
    ELECTRICIAN = "electrician"
    PLUMBER = "plumber"
    LOCKSMITH = "locksmith"
    HANDYMAN = "handyman"
    CLEANER = "cleaner"
    AC_TECHNICIAN = "ac_technician"
    OTHER = "other"


def trade_label(trade: str | None) -> str:
    return "AC technician" if trade == Trade.AC_TECHNICIAN else (trade or "other").capitalize()


class BusinessStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    DELETED = "deleted"  # erased at the seller's request; kept only so past jobs still resolve


class ConfirmOutcome(StrEnum):
    LIVE = "live"  # first confirmation: the business now receives jobs
    UPDATED = "updated"  # a live profile was changed
    NEEDS_PHONE = "needs_phone"  # kept; applied as soon as the phone is shared
    NEEDS_BASICS = "needs_basics"  # name or area still missing
    STALE = "stale"  # not the latest proposal, or already handled


class TimeSlot(BaseModel):
    days: list[Day]
    start: str  # "HH:MM"
    end: str  # "HH:MM"; "24:00" = midnight


class Availability(BaseModel):
    always_available: bool  # 24/7
    slots: list[TimeSlot] = Field(default_factory=list)


class PriceRule(BaseModel):
    applies_when: str
    amount_minor: int | None  # ADR 0002
    currency: str = "EUR"
    kind: str


class Profile(BaseModel):
    """What the owner confirms. Stored on the business once confirmed."""

    name: str | None = None
    trade: Trade = Trade.OTHER
    area: str | None = None
    availability_text: str | None = None
    availability: Availability = Field(default_factory=lambda: Availability(always_available=False))
    pricing_text: str | None = None
    pricing: list[PriceRule] = Field(default_factory=list)
    quoted_separately: str | None = None

    def missing_basics(self) -> list[str]:
        return [
            label for key, label in (("name", "name"), ("area", "area")) if not getattr(self, key)
        ]


class BusinessView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    telegram_chat_id: int | None  # None once deleted: the chat is free to start again
    phone: str | None
    status: BusinessStatus
    name: str | None
    trade: Trade | None
    area: str | None
    availability_text: str | None
    availability: Availability | None
    pricing_text: str | None
    pricing: list[PriceRule] | None
    quoted_separately: str | None
    created_at: datetime
    updated_at: datetime

    def profile(self) -> Profile:
        return Profile.model_validate(
            {
                k: v
                for k, v in self.model_dump().items()
                if k in Profile.model_fields and v is not None
            }
        )


class ProposalView(BaseModel):
    proposal_id: int
    business_id: int
    profile: Profile
    phone: str | None
    business_status: BusinessStatus
    missing_basics: list[str]
