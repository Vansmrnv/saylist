"""Demo data: `make seed` (add 4 businesses) or `make seed-reset` (wipe every table first).

Chat ids are fake (negative) so their offers are logged as failed deliveries; set
SEED_CHAT_ID_1..4 to real, distinct chat ids to receive them in Telegram."""

import asyncio
import os
import sys

from sqlalchemy import text

from app.core.db import get_sessionmaker
from app.modules import businesses, load_all
from app.modules.businesses import Availability, PriceRule, Profile, TimeSlot, Trade

DAYS_WEEK = ["mon", "tue", "wed", "thu", "fri"]
DAYS_WEEKEND = ["sat", "sun"]


def _slots(*items: tuple[list[str], str, str]) -> Availability:
    return Availability(
        always_available=False,
        slots=[TimeSlot.model_validate({"days": d, "start": s, "end": e}) for d, s, e in items],
    )


BUSINESSES = [
    (
        "+357 99 100001",
        Profile(
            name="Andreas Volt Electrics",
            trade=Trade.ELECTRICIAN,
            area="Limassol",
            availability_text="Every day, 24/7",
            availability=Availability(always_available=True),
            pricing_text="€30 minimum callout 08:00–17:00; €150 minimum callout otherwise",
            pricing=[
                PriceRule(
                    applies_when="Every day 08:00–17:00", amount_minor=3000, kind="minimum callout"
                ),
                PriceRule(
                    applies_when="Outside 08:00–17:00", amount_minor=15000, kind="minimum callout"
                ),
            ],
            quoted_separately="Everything else is quoted directly to the client",
        ),
    ),
    (
        "+357 99 100002",
        Profile(
            name="Bright Spark Electrical",
            trade=Trade.ELECTRICIAN,
            area="Limassol",
            availability_text="Mon–Fri 08:00–15:00",
            availability=_slots((DAYS_WEEK, "08:00", "15:00")),
            pricing_text="€40 callout",
            pricing=[PriceRule(applies_when="Any time", amount_minor=4000, kind="callout")],
        ),
    ),
    (
        "+357 99 100003",
        Profile(
            name="Night Owl Electric",
            trade=Trade.ELECTRICIAN,
            area="Limassol",
            availability_text="Mon–Fri 17:00–23:00; Sat–Sun all day",
            availability=_slots((DAYS_WEEK, "17:00", "23:00"), (DAYS_WEEKEND, "00:00", "24:00")),
            pricing_text="€80 callout",
            pricing=[PriceRule(applies_when="Any time", amount_minor=8000, kind="callout")],
        ),
    ),
    (
        "+357 99 100004",
        Profile(
            name="AquaFix Plumbing",
            trade=Trade.PLUMBER,
            area="Limassol",
            availability_text="Every day, 24/7",
            availability=Availability(always_available=True),
            pricing_text="€50 callout",
            pricing=[PriceRule(applies_when="Any time", amount_minor=5000, kind="callout")],
        ),
    ),
]

TABLES = "job_event, job_offer, job, business_proposal, business, messaging_outbox"


async def main(reset: bool) -> None:
    load_all()
    async with get_sessionmaker()() as session, session.begin():
        if reset:
            await session.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
            print("Wiped all tables.")
        for i, (phone, profile) in enumerate(BUSINESSES, start=1):
            chat_id = int(os.getenv(f"SEED_CHAT_ID_{i}") or -1_000_000 - i)
            existing = await businesses.get_by_chat(session, chat_id)
            if existing:
                print(f"#{existing.id} {existing.name} already there")
                continue
            created = await businesses.create_active(session, chat_id, phone, profile)
            print(f"#{created.id} {created.name} ({created.trade}) chat_id={chat_id}")


if __name__ == "__main__":
    asyncio.run(main(reset="--reset" in sys.argv))
