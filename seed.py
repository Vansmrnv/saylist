"""Insert 4 active demo businesses: python seed.py   (python seed.py --reset also wipes all tables)

Chat ids are fake unless SEED_CHAT_ID_1..4 are set, so offers to them are only logged."""
import os
import sys

import db

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri"]
WEEKEND = ["sat", "sun"]
ALL_DAYS = WEEKDAYS + WEEKEND

BUSINESSES = [
    {
        "name": "Andreas Volt Electrics",
        "trade": "electrician",
        "area": "Limassol",
        "phone": "+357 99 100001",
        "transcript": ("I am electrician, I am available 24/7, during 8am-5pm it costs 30 eur minimum callout and "
                       "otherwise 150 eur minimum callout. Everything else will be quoted directly to client."),
        "availability_text": "Every day, 24/7",
        "availability_json": {"always_available": True, "slots": []},
        "pricing_text": "€30 minimum callout 08:00–17:00; €150 minimum callout otherwise",
        "pricing_json": [
            {"applies_when": "Every day 08:00–17:00", "amount_eur": 30, "kind": "minimum callout"},
            {"applies_when": "Outside 08:00–17:00", "amount_eur": 150, "kind": "minimum callout"},
        ],
        "quoted_separately": "Everything else is quoted directly to the client",
    },
    {
        "name": "Bright Spark Electrical",
        "trade": "electrician",
        "area": "Limassol",
        "phone": "+357 99 100002",
        "transcript": "Electrician, weekdays 8 to 3, 40 euro callout.",
        "availability_text": "Mon–Fri 08:00–15:00",
        "availability_json": {"always_available": False,
                              "slots": [{"days": WEEKDAYS, "start": "08:00", "end": "15:00"}]},
        "pricing_text": "€40 callout",
        "pricing_json": [{"applies_when": "Any time", "amount_eur": 40, "kind": "callout"}],
        "quoted_separately": None,
    },
    {
        "name": "Night Owl Electric",
        "trade": "electrician",
        "area": "Limassol",
        "phone": "+357 99 100003",
        "transcript": "Electrician, weekday evenings 5pm to 11pm and all weekend, 80 euro callout.",
        "availability_text": "Mon–Fri 17:00–23:00; Sat–Sun all day",
        "availability_json": {"always_available": False, "slots": [
            {"days": WEEKDAYS, "start": "17:00", "end": "23:00"},
            {"days": WEEKEND, "start": "00:00", "end": "24:00"},
        ]},
        "pricing_text": "€80 callout",
        "pricing_json": [{"applies_when": "Any time", "amount_eur": 80, "kind": "callout"}],
        "quoted_separately": None,
    },
    {
        "name": "AquaFix Plumbing",
        "trade": "plumber",
        "area": "Limassol",
        "phone": "+357 99 100004",
        "transcript": "Plumber, 24/7, 50 euro callout.",
        "availability_text": "Every day, 24/7",
        "availability_json": {"always_available": True, "slots": []},
        "pricing_text": "€50 callout",
        "pricing_json": [{"applies_when": "Any time", "amount_eur": 50, "kind": "callout"}],
        "quoted_separately": None,
    },
]


def main() -> None:
    db.init_db()
    if "--reset" in sys.argv:
        for table in ("offers", "requests", "businesses"):
            db.execute(f"DELETE FROM {table}")
        print("Wiped all tables.")
    names = tuple(b["name"] for b in BUSINESSES)
    db.execute(f"DELETE FROM businesses WHERE name IN ({','.join('?' * len(names))})", names)
    for i, business in enumerate(BUSINESSES, start=1):
        chat_id = int(os.getenv(f"SEED_CHAT_ID_{i}") or -1000000 - i)
        now = db.utcnow()
        business_id = db.insert("businesses", {**business, "telegram_chat_id": chat_id, "status": "active",
                                               "created_at": now, "updated_at": now})
        print(f"#{business_id} {business['name']} ({business['trade']}) chat_id={chat_id}")


if __name__ == "__main__":
    main()
