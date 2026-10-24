from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

Day = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


class JobStatus(StrEnum):
    DRAFT = "draft"  # created by the assistant, not sent yet (ADR 0005: two steps)
    OPEN = "open"  # offers sent, waiting for the first accept
    BOOKED = "booked"  # a business took it for a concrete time
    ON_THE_WAY = "on_the_way"
    ARRIVED = "arrived"
    DONE = "done"
    NO_MATCH = "no_match"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


ACTIVE_STATUSES = (JobStatus.BOOKED, JobStatus.ON_THE_WAY, JobStatus.ARRIVED)


class OfferAnswer(StrEnum):
    PROPOSED = "proposed"  # part of a draft, not sent
    WAITING = "waiting"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    TOO_LATE = "too_late"
    EXPIRED = "expired"
    WITHDRAWN = "withdrawn"  # the customer cancelled, or the draft was never confirmed


class EventKind(StrEnum):
    REQUESTED = "requested"
    SENT = "sent"
    NO_MATCH = "no_match"
    BOOKED = "booked"
    ON_THE_WAY = "on_the_way"
    ARRIVED = "arrived"
    CUSTOMER_COMING = "customer_coming"
    DONE = "done"
    EXPIRED = "expired"
    CANCELLED_BY_CUSTOMER = "cancelled_by_customer"
    CANCELLED_BY_BUSINESS = "cancelled_by_business"


class Outcome(StrEnum):
    """The fixed outcome set of ADR 0005."""

    DONE = "DONE"
    NO_CHANGE = "NO_CHANGE"
    NOT_FOUND = "NOT_FOUND"
    REFUSED = "REFUSED"
    INVALID = "INVALID"
    NEEDS_A_DECISION = "NEEDS_A_DECISION"


class BusinessAction(StrEnum):
    ON_THE_WAY = "otw"
    ARRIVED = "here"
    DONE = "done"
    CANCEL = "cancel"


class When(BaseModel):
    asap: bool
    days_of_week: list[Day]
    dates: list[str]  # concrete YYYY-MM-DD
    start_time: str | None  # "HH:MM"
    end_time: str | None  # "HH:MM"; "24:00" = midnight


class ArrivalOption(BaseModel):
    """A time the business can commit to with one tap."""

    label: str
    at: datetime | None = None  # a booked time, or
    minutes: int | None = None  # "can be there in N minutes" for ASAP jobs


class JobRequestIn(BaseModel):
    """What an assistant sends to create a job. Every field is required: the business should
    never need to call the customer to ask."""

    trade: str = Field(description="Kind of tradesperson in plain words, e.g. 'electrician'.")
    when: str = Field(
        description="When it is needed, in the customer's words: 'any weekday after 4pm', 'asap'."
    )
    street_address: str = Field(
        description="Street name AND house number (or a named building / map link). "
        "Not just a district or village."
    )
    unit: str = Field(description="Flat number and floor, or 'house' for a detached house.")
    city: str = Field(description="Town or village.")
    access_notes: str = Field(
        description="How to get in without calling: gate or door code, which bell, parking, "
        "who will be home. 'none' only if the customer says nothing is needed."
    )
    description: str = Field(description="What the job is, in a few words.")
    customer_name: str
    customer_phone: str = Field(description="Used only if the business cannot get in.")


class EventView(BaseModel):
    at: datetime
    kind: EventKind
    text: str


class JobView(BaseModel):
    """A job as the customer (and their assistant) sees it."""

    job_id: int
    token: str
    status: JobStatus
    status_text: str
    trade: str
    when: str
    address: str
    access_notes: str
    description: str
    customer_name: str
    maps_url: str
    business_name: str | None = None
    business_phone: str | None = None
    price_note: str | None = None
    quotes: list[str] = Field(default_factory=list)
    scheduled_for: datetime | None = None
    eta_at: datetime | None = None
    sent_to: int = 0
    timeline: list[EventView] = Field(default_factory=list)
    created_at: datetime


class WriteResult(BaseModel):
    outcome: Outcome
    why: str
    job: JobView | None = None


class OfferAdminView(BaseModel):
    id: int
    job_id: int
    business_id: int
    answer: OfferAnswer
    price_note: str | None
    options: list[str]
    answered_at: datetime | None
