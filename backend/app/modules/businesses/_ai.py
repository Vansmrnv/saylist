"""Profile extraction prompts. The model proposes; the owner confirms. (ADR 0003)"""

import json
from typing import Literal

from pydantic import BaseModel

from app.core import llm
from app.core.money import exponent, to_minor
from app.modules.businesses._schemas import Availability, PriceRule, Profile, Trade


class _PriceRuleOut(BaseModel):
    applies_when: str
    amount: float | None
    currency: str
    kind: str


class _ProfileOut(BaseModel):
    name: str | None
    trade: Literal[
        "electrician", "plumber", "locksmith", "handyman", "cleaner", "ac_technician", "other"
    ]
    area: str | None
    availability_text: str
    availability: Availability
    pricing_text: str
    pricing: list[_PriceRuleOut]
    quoted_separately: str | None

    def to_profile(self) -> Profile:
        return Profile(
            name=self.name,
            trade=Trade(self.trade),
            area=self.area,
            availability_text=self.availability_text,
            availability=self.availability,
            pricing_text=self.pricing_text,
            pricing=[
                PriceRule(
                    applies_when=p.applies_when,
                    amount_minor=None if p.amount is None else to_minor(p.amount, p.currency),
                    currency=p.currency.upper(),
                    kind=p.kind,
                )
                for p in self.pricing
            ],
            quoted_separately=self.quoted_separately,
        )


def _for_llm(profile: Profile) -> dict[str, object]:
    """The profile in the output's own shape (amounts in currency units), so edits round-trip."""
    data = profile.model_dump(mode="json")
    data["pricing"] = [
        {
            "applies_when": p.applies_when,
            "amount": None
            if p.amount_minor is None
            else p.amount_minor / 10 ** exponent(p.currency),
            "currency": p.currency,
            "kind": p.kind,
        }
        for p in profile.pricing
    ]
    return data


RULES = """Field rules:
- trade must be exactly one of: electrician, plumber, locksmith, handyman, cleaner,
  ac_technician, other. Map whatever the owner says (any language, slang) onto this list;
  other only if nothing fits.
- name: the business or person name if stated, else null. area: the city/district they serve if
  stated, else null. Never invent a name or area.
- availability: always_available=true for 24/7 (slots may then be empty). Otherwise one slot
  per set of days with the same hours. "24:00" means midnight; split overnight ranges into two.
  If the owner gives a price for weekends, evenings or "after hours", they work then too: include
  those times (all day for weekends, until 24:00 for evenings, unless they say otherwise).
- availability_text: short human summary, e.g. "Every day, 24/7" or "Mon–Fri 08:00–15:00".
- pricing: one entry per price rule. applies_when states the time window or condition in plain
  words with 24h times ("Every day 08:00–17:00", "Outside 08:00–17:00"); amount is a number in
  currency units (null if not stated); currency is an ISO 4217 code (EUR unless another is said);
  kind is e.g. "minimum callout", "callout", "hourly", "fixed".
- pricing_text: short summary, e.g. "€30 minimum callout 08:00–17:00; €150 otherwise".
- quoted_separately: what the owner says is quoted directly to the client, else null.
- Write the summaries in English, even if the owner spoke another language."""


async def extract(text: str) -> Profile:
    instructions = (
        "You turn a tradesperson's description of their business (often a transcribed voice "
        "note in imperfect English or another language) into a structured profile for a "
        "local-services marketplace.\n\n" + RULES
    )
    out = await llm.structured("extract_business_profile", instructions, text, _ProfileOut)
    return out.to_profile()


async def update(current: Profile, text: str) -> Profile:
    instructions = (
        "You maintain a tradesperson's structured profile for a local-services marketplace. "
        "You get the current profile as JSON and a message from the owner: a correction, an "
        "addition such as their name or area, or a full new description. Return the complete "
        "updated profile. Keep every field the message does not change exactly as it is.\n\n"
        + RULES
    )
    content = (
        f"Current profile:\n{json.dumps(_for_llm(current), ensure_ascii=False, indent=2)}"
        f"\n\nOwner's message:\n{text}"
    )
    out = await llm.structured("update_business_profile", instructions, content, _ProfileOut)
    return out.to_profile()
