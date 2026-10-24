"""Live check of the prompts on the fixtures (costs a few API calls): `make try-llm`."""

import asyncio

from app.modules.businesses import _ai as business_ai
from app.modules.jobs import JobRequestIn
from app.modules.jobs import _ai as jobs_ai

TRANSCRIPT = (
    "I am electrician, I am available 24/7, during 8am-5pm it costs 30 eur minimum callout and "
    "otherwise 150 eur minimum callout. Everything else will be quoted directly to client."
)
REQUEST = JobRequestIn(
    trade="electrician",
    when="any weekday after 4pm",
    street_address="Agias Fylaxeos 45",
    unit="Flat 3, 2nd floor",
    city="Limassol",
    access_notes="Gate code 1234",
    description="Kitchen sockets dead",
    customer_name="Alex",
    customer_phone="+357 99 123456",
)
# A price for weekends / after hours means they work then (a real onboarding that went wrong).
AFTER_HOURS = (
    "i am an electrician Xaris Electrician. I work all over limassol weekdays 8am-4pm callout fee "
    "60 eur then 30/h weekends and after hours 150 callout and 50/h. Phone 99123456"
)
ADDRESSES = [  # (street_address, unit, city) -> expected address_specific
    (("Agias Fylaxeos 45", "Flat 3, 2nd floor", "Limassol"), True),
    (("Mouttagiaka", "house", "Limassol"), False),
    (("near the church", "house", "Mouttagiaka"), False),
    (("Makariou Avenue", "Flat 2", "Limassol"), False),
    (("Agias Fylaxeos 45", "?", "Limassol"), False),
    (("34.6923, 33.1101", "house", "Mouttagiaka"), True),
]


async def main() -> None:
    profile = await business_ai.extract(TRANSCRIPT)
    print("profile:", profile.model_dump_json(indent=2))
    assert profile.trade == "electrician" and profile.availability.always_available
    assert sorted(p.amount_minor or 0 for p in profile.pricing) == [3000, 15000]

    after_hours = await business_ai.extract(AFTER_HOURS)
    print("after hours:", after_hours.availability_text, after_hours.availability)
    works_saturday = after_hours.availability.always_available or any(
        "sat" in slot.days for slot in after_hours.availability.slots
    )
    assert works_saturday, "priced weekend work must count as available on weekends"

    failures = []
    for (street, unit, city), expected in ADDRESSES:
        read = await jobs_ai.read_request(
            REQUEST.model_copy(update={"street_address": street, "unit": unit, "city": city})
        )
        ok = read.address_specific == expected
        print(f"{'ok ' if ok else 'BAD'} {street!r} / {unit!r} / {city!r}: {read.address_problem}")
        if not ok:
            failures.append(street)
    assert not failures, f"address check wrong for {failures}"
    print("All fixture checks passed.")


if __name__ == "__main__":
    asyncio.run(main())
