"""All LLM calls. Each call asks Claude for JSON matching a schema
(structured outputs), validates it with pydantic and retries once."""
import json
import logging
from typing import Literal, Optional

import anthropic
from pydantic import BaseModel, ValidationError

import config

log = logging.getLogger("llm")

Trade = Literal["electrician", "plumber", "locksmith", "handyman", "cleaner", "ac_technician", "other"]
Day = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

# Models that accept the server-side refusal fallback beta.
FALLBACK_MODELS = {"claude-sonnet-5-5", "claude-opus-5-5", "claude-opus-5", "claude-fable-5-1"}

_client: anthropic.AsyncAnthropic | None = None


def client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY or None)
    return _client


class LLMError(Exception):
    pass


# --- output models -------------------------------------------------------------

class TimeSlot(BaseModel):
    days: list[Day]
    start: str  # "HH:MM", 24h
    end: str  # "HH:MM", 24h; "24:00" = midnight


class Availability(BaseModel):
    always_available: bool  # true = 24/7
    slots: list[TimeSlot]


class PriceRule(BaseModel):
    applies_when: str
    amount_eur: Optional[float]
    kind: str


class BusinessProfile(BaseModel):
    name: Optional[str]
    trade: Trade
    area: Optional[str]
    availability_text: str
    availability_json: Availability
    pricing_text: str
    pricing_json: list[PriceRule]
    quoted_separately: Optional[str]
    missing: list[str]


class When(BaseModel):
    asap: bool
    days_of_week: list[Day]
    dates: list[str]  # concrete YYYY-MM-DD dates
    start_time: Optional[str]  # "HH:MM"
    end_time: Optional[str]  # "HH:MM"


class ClientRequest(BaseModel):
    trade: Optional[Trade]
    when_text: Optional[str]
    when_json: Optional[When]
    area: Optional[str]
    description: Optional[str]
    missing: list[Literal["trade", "when", "area"]]


class Match(BaseModel):
    business_id: int
    available: bool
    price_note: str
    reason: str


class MatchList(BaseModel):
    matches: list[Match]


# --- core call -------------------------------------------------------------------

def _strict_schema(model: type[BaseModel]) -> dict:
    """Pydantic JSON schema -> structured-outputs schema: every property
    required, no extra properties, no titles/defaults."""

    def fix(node):
        if isinstance(node, dict):
            node.pop("title", None)
            node.pop("default", None)
            if node.get("type") == "object" and "properties" in node:
                node["required"] = list(node["properties"])
                node["additionalProperties"] = False
            for v in node.values():
                fix(v)
        elif isinstance(node, list):
            for v in node:
                fix(v)
        return node

    return fix(model.model_json_schema())


def _time_context() -> str:
    now = config.now_local()
    return (
        f"Current local date and time: {now:%A %Y-%m-%d %H:%M} ({config.TIMEZONE}). "
        "Use 24-hour HH:MM times. Days of week are mon, tue, wed, thu, fri, sat, sun."
    )


async def _create(**kwargs):
    if config.LLM_MODEL in FALLBACK_MODELS:
        return await client().beta.messages.create(
            betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs
        )
    return await client().messages.create(**kwargs)


async def _structured(task: str, instructions: str, user_content: str, model: type[BaseModel]):
    system = f"{instructions}\n\n{_time_context()}"
    schema = _strict_schema(model)
    log.info("[%s] INPUT:\n%s", task, user_content)
    error = None
    for attempt in (1, 2):
        resp = await _create(
            model=config.LLM_MODEL,
            max_tokens=16000,
            system=system,
            messages=[{"role": "user", "content": user_content}],
            output_config={"effort": config.LLM_EFFORT, "format": {"type": "json_schema", "schema": schema}},
        )
        text = next((b.text for b in resp.content if b.type == "text"), "")
        log.info("[%s] OUTPUT (attempt %d, stop=%s):\n%s", task, attempt, resp.stop_reason, text)
        try:
            return model.model_validate_json(text)
        except ValidationError as e:
            error = e
            log.warning("[%s] invalid output, %s", task, "retrying" if attempt == 1 else "giving up")
    raise LLMError(f"{task}: invalid output after retry: {error}")


# --- public functions -------------------------------------------------------------

TRADE_RULE = (
    "trade must be exactly one of: electrician, plumber, locksmith, handyman, cleaner, "
    "ac_technician, other. Map whatever the user says (any language, slang, a description of "
    "the problem) onto this list; use other only if nothing fits."
)

PROFILE_RULES = f"""Field rules:
- {TRADE_RULE}
- name: the business or person name if stated, else null. area: the city/district they serve if
  stated, else null. Never invent a name or area.
- availability_json: always_available=true for 24/7 (slots may then be empty). Otherwise one slot per
  set of days with the same hours. "24:00" means midnight; split overnight ranges into two slots.
- availability_text: short human summary, e.g. "Every day, 24/7" or "Mon–Fri 08:00–15:00".
- pricing_json: one entry per price rule. applies_when states the time window/condition in plain words
  with 24h times (e.g. "Every day 08:00–17:00", "Outside 08:00–17:00"); amount_eur is a number (null if
  not stated); kind is e.g. "minimum callout", "callout", "hourly", "fixed".
- pricing_text: short summary, e.g. "€30 minimum callout 08:00–17:00; €150 minimum callout otherwise".
- quoted_separately: what the owner says is quoted directly to the client, else null.
- missing: the fields still unknown, from: name, area, availability, pricing.
- Write the summaries in English, even if the owner spoke another language."""


async def extract_business_profile(transcript: str) -> BusinessProfile:
    instructions = (
        "You turn a tradesperson's description of their business (often a transcribed voice note in "
        "imperfect English or another language) into a structured profile for a local-services "
        "marketplace.\n\n" + PROFILE_RULES
    )
    return await _structured("extract_business_profile", instructions, transcript, BusinessProfile)


async def update_business_profile(current_profile: dict, correction: str) -> BusinessProfile:
    instructions = (
        "You maintain a tradesperson's structured profile for a local-services marketplace. You get the "
        "current profile as JSON and a message from the owner (a correction, an addition such as their "
        "name or area, or a full new description). Apply it and return the complete updated profile. "
        "Keep every field the message does not change exactly as it is.\n\n" + PROFILE_RULES
    )
    current = {k: current_profile.get(k) for k in BusinessProfile.model_fields if k != "missing"}
    content = (
        f"Current profile:\n{json.dumps(current, ensure_ascii=False, indent=2)}\n\n"
        f"Owner's message:\n{correction}"
    )
    return await _structured("update_business_profile", instructions, content, BusinessProfile)


async def extract_client_request(conversation_so_far: str) -> ClientRequest:
    instructions = f"""You help clients book a local tradesperson. Read the conversation so far and extract the request.
Field rules:
- {TRADE_RULE} null if not clear yet.
- when_text: short English summary of when they need it, e.g. "Any weekday after 16:00" or "Today ASAP". null if not given.
- when_json: resolve the time against the current date and time. days_of_week: the matching days.
  dates: the concrete upcoming dates (YYYY-MM-DD) in the next 7 days that match, including today only if
  the window has not passed yet. start_time/end_time: the window ("after 4pm" -> 16:00–24:00, "morning" ->
  08:00–12:00, "evening" -> 17:00–22:00, a single time like "at 3pm" -> 15:00–16:00, whole day ->
  00:00–24:00). "now"/"asap"/"urgent" -> asap=true, today, from now for 3 hours. null if no time given.
- area: the place where the job is (city, district or address), else null.
- description: short English description of the job if given, else null.
- missing: which of trade, when, area are still unknown."""
    return await _structured("extract_client_request", instructions, conversation_so_far, ClientRequest)


async def match_businesses(request: dict, candidate_businesses: list[dict]) -> list[Match]:
    if not candidate_businesses:
        return []
    instructions = """You decide which businesses can take a job at the requested time and what price applies to each.
Rules:
- available=true if the business's availability overlaps the requested time window on at least one of the
  requested days/dates. Partial overlap counts. always_available means 24/7. Ignore area.
- price_note: the price(s) that apply during the overlapping part of the requested window only, using the
  business's own pricing rules, in short text, e.g. "€30 minimum callout 16:00–17:00, €150 minimum callout
  after 17:00". If several bands apply, mention each with its hours. Empty string if not available.
- reason: one short sentence.
Return exactly one entry for every candidate, using its business_id."""
    req = {k: request.get(k) for k in ("trade", "when_text", "when_json", "area", "description")}
    cands = [
        {k: b.get(k) for k in ("id", "name", "availability_text", "availability_json", "pricing_text",
                               "pricing_json", "quoted_separately")}
        for b in candidate_businesses
    ]
    for c in cands:
        c["business_id"] = c.pop("id")
    content = (
        f"Request:\n{json.dumps(req, ensure_ascii=False, indent=2)}\n\n"
        f"Candidate businesses:\n{json.dumps(cands, ensure_ascii=False, indent=2)}"
    )
    result = await _structured("match_businesses", instructions, content, MatchList)
    known = {b["id"] for b in candidate_businesses}
    return [m for m in result.matches if m.business_id in known]

