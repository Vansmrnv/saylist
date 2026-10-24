"""The assistant's tools: thin wrappers over the businesses contract.

None of them confirms anything. Proposing shows a card whose Correct choice only the seller can
pick (ADR 0003); offering a phone shows a Yes/No choice. Tool results tell the model what the
seller now sees, so it does not repeat it.
"""

import inspect
import json
import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules import businesses
from app.modules.assistant import _replies
from app.modules.assistant._schemas import Reply


def _tool(name: str, description: str, properties: dict[str, Any] | None = None) -> dict[str, Any]:
    props = properties or {}
    return {
        "name": name,
        "description": description,
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": props,
            "required": list(props),
            "additionalProperties": False,
        },
    }


TOOLS: list[dict[str, Any]] = [
    _tool(
        "get_profile",
        "Read the seller's live profile (what customers are matched against), their phone, their "
        "status (draft or active) and the open proposal waiting for their confirmation, if any. "
        "Use it to answer questions about their profile. Shows nothing to the seller.",
    ),
    _tool(
        "propose_profile_change",
        "Turn what the seller said about their business into a proposed profile (a first "
        "description or an edit) and show it to them as a card with Correct / Change buttons. "
        "Nothing is saved until the seller taps Correct; you cannot do that for them.",
        {
            "text": {
                "type": "string",
                "description": "The seller's own words, verbatim. If the message only makes "
                "sense with earlier context ('make it 40'), a self-contained restatement in the "
                "seller's voice ('My minimum callout is €40').",
            }
        },
    ),
    _tool(
        "show_profile",
        "Show the seller their current live (or draft) profile as a card.",
    ),
    _tool(
        "show_pending_proposal",
        "Show the open proposal again with its Correct / Change buttons. Use it when the seller "
        "says in words that the proposal is right: they still have to tap Correct themselves.",
    ),
    _tool(
        "offer_phone",
        "The seller typed or said a phone number for their business. Shows a Yes/No question to "
        "save it; it is saved only if they tap Yes.",
        {"phone": {"type": "string", "description": "The number as given, with country code."}},
    ),
    _tool(
        "request_phone",
        "Ask the seller to share their phone number (with the channel's share-contact control).",
    ),
]


def normalize_phone(raw: str) -> str | None:
    """`+35799123456` from '+357 99-123 456' or '35799123456'; None if it is not a number."""
    digits = re.sub(r"[\s\-().]", "", raw.strip())
    if digits.startswith("00"):
        digits = digits[2:]
    digits = digits.removeprefix("+")
    return f"+{digits}" if re.fullmatch(r"\d{7,15}", digits) else None


@dataclass
class Toolbox:
    """Runs tool calls for one turn. Cards and questions it produces collect in `replies`."""

    session: AsyncSession
    chat_id: int
    replies: list[Reply] = field(default_factory=list)

    async def run(self, name: str, args: dict[str, Any]) -> tuple[str, bool]:
        """Returns (result for the model, is_error)."""
        handler = getattr(self, f"_{name}", None)
        if handler is None or name not in {t["name"] for t in TOOLS}:
            return f"Unknown tool {name}.", True
        try:
            inspect.signature(handler).bind(**args)
        except TypeError:
            return f"Bad arguments for {name}: {args}.", True
        result: dict[str, Any] = await handler(**args)
        return json.dumps(result, ensure_ascii=False), bool(result.get("error"))

    async def _get_profile(self) -> dict[str, Any]:
        business = await businesses.get_by_chat(self.session, self.chat_id)
        proposal = await businesses.latest_proposal(self.session, self.chat_id)
        if business is None:
            return {"status": "none", "note": "No profile yet: the seller has not described it."}
        return {
            "status": business.status.value,
            "phone": business.phone,
            "live_profile": business.profile().model_dump(mode="json")
            if business.status == businesses.BusinessStatus.ACTIVE
            else None,
            "open_proposal": proposal.profile.model_dump(mode="json") if proposal else None,
            "note": "Prices are in minor units (cents): amount_minor 3000 = €30.",
        }

    async def _propose_profile_change(self, text: str) -> dict[str, Any]:
        if not text.strip():
            return {"error": "Empty text."}
        proposal = await businesses.propose(self.session, self.chat_id, text)
        self.replies.append(_replies.proposal_card(proposal))
        if proposal.missing_basics:
            return {
                "shown": "The proposed profile card, asking for: "
                + " and ".join(proposal.missing_basics),
                "can_confirm": False,
            }
        return {
            "shown": "The proposed profile card with Correct / Change buttons.",
            "can_confirm": True,
            "phone_on_file": bool(proposal.phone),
        }

    async def _show_profile(self) -> dict[str, Any]:
        business = await businesses.get_by_chat(self.session, self.chat_id)
        if business is None or business.trade is None:
            return {"error": "No profile yet. Ask the seller to describe their business."}
        self.replies.append(_replies.live_card(business))
        return {"shown": "The profile card."}

    async def _show_pending_proposal(self) -> dict[str, Any]:
        proposal = await businesses.latest_proposal(self.session, self.chat_id)
        if proposal is None:
            return {"error": "There is no open proposal."}
        self.replies.append(_replies.proposal_card(proposal))
        return {"shown": "The open proposal card.", "can_confirm": not proposal.missing_basics}

    async def _offer_phone(self, phone: str) -> dict[str, Any]:
        normalized = normalize_phone(phone)
        if normalized is None:
            return {"error": f"{phone!r} is not a phone number. Ask again with country code."}
        self.replies.append(_replies.phone_offer(normalized))
        return {"shown": f"A question: save {normalized}? Yes / No."}

    async def _request_phone(self) -> dict[str, Any]:
        self.replies.append(_replies.ask_contact("Please share your phone number."))
        return {"shown": "A request to share the phone number."}
