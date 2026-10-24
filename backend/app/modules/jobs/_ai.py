"""LLM prompts for jobs: read the request, check the address, work out each business's price."""

import json
from typing import Literal

from pydantic import BaseModel

from app.core import llm
from app.core.money import format_minor
from app.modules.businesses import BusinessView
from app.modules.jobs._schemas import JobRequestIn, When


class RequestOut(BaseModel):
    trade: (
        Literal[
            "electrician", "plumber", "locksmith", "handyman", "cleaner", "ac_technician", "other"
        ]
        | None
    )
    when_text: str | None
    when: When | None
    address_specific: bool
    address_problem: str | None
    maps_query: str


class _Quote(BaseModel):
    business_id: int
    price_note: str


class _Quotes(BaseModel):
    quotes: list[_Quote]


REQUEST_RULES = """You check a customer's request for a local tradesperson before it is sent.
The goal is that the tradesperson never has to call the customer: they must be able to drive to
the exact door, at an agreed time, knowing how to get in.

- trade: map the requested trade onto exactly one of electrician, plumber, locksmith, handyman,
  cleaner, ac_technician, other (any language or slang; use the job description if needed).
  null only if you cannot tell at all.
- when_text: short English summary of when, e.g. "Any weekday after 16:00" or "Today, ASAP".
- when: resolve against the current date and time. days_of_week: the matching days. dates: the
  concrete upcoming dates (YYYY-MM-DD) in the next 7 days that match, including today only if the
  window has not passed. start_time/end_time: the window ("after 4pm" -> 16:00-24:00, "morning" ->
  08:00-12:00, "evening" -> 17:00-22:00, "at 3pm" -> 15:00-16:00, whole day -> 08:00-20:00).
  "now", "asap", "urgent" -> asap=true with today's date. null if no time is given.
- address_specific: true only if street_address + city identify ONE building: a street name with a
  house/building number, a named building or complex on a named street, GPS coordinates, or a map
  link. false for a village, district, neighbourhood or landmark alone ("Mouttagiaka", "near the
  church", "Limassol centre"), or a street without a number. Also false if unit does not say a
  flat/floor or that it is a house.
- address_problem: when address_specific is false, one instruction to the assistant naming exactly
  what to ask the customer, e.g. "Ask for the street name and house number in Mouttagiaka."
  Otherwise null.
- maps_query: the full address for a map search, e.g. "Agias Fylaxeos 45, Limassol, Cyprus"."""


async def read_request(request: JobRequestIn) -> RequestOut:
    content = json.dumps(
        request.model_dump(exclude={"customer_name", "customer_phone"}), ensure_ascii=False
    )
    return await llm.structured("read_job_request", REQUEST_RULES, content, RequestOut)


PRICE_RULES = """For each business, write the price that applies to this job during the requested
time window, from the business's own pricing rules, as short text, e.g. "€30 minimum callout
16:00-17:00, €150 minimum callout after 17:00". If several bands fall in the window, give each with
its hours. Mention when other work is quoted separately only if the business says so. Return one
entry for every business, using its business_id."""


async def price_notes(when_text: str, when: When, businesses: list[BusinessView]) -> dict[int, str]:
    if not businesses:
        return {}
    candidates = [
        {
            "business_id": b.id,
            "pricing_text": b.pricing_text,
            "pricing": [
                {
                    "applies_when": p.applies_when,
                    "price": "not stated"
                    if p.amount_minor is None
                    else format_minor(p.amount_minor, p.currency),
                    "kind": p.kind,
                }
                for p in b.pricing or []
            ],
            "quoted_separately": b.quoted_separately,
        }
        for b in businesses
    ]
    content = (
        f"Requested time: {when_text}\n{when.model_dump_json()}\n\n"
        "Businesses:\n"
        f"{json.dumps(candidates, ensure_ascii=False, indent=2)}"
    )
    out = await llm.structured("price_notes", PRICE_RULES, content, _Quotes)
    return {q.business_id: q.price_note for q in out.quotes}
