"""The LLM side of a turn: prompt, history and the tool-use loop.

The system prompt and the tool list never change within a conversation, and per-turn facts (the
time, the seller's status) go into that turn's user message. Earlier turns are replayed without
their thinking blocks (removing every earlier thinking block is a removal from the front, which
the API accepts); the turn in progress is replayed exactly as returned.
"""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import llm
from app.modules import businesses
from app.modules.assistant import _replies
from app.modules.assistant._models import Turn
from app.modules.assistant._schemas import Reply
from app.modules.assistant._tools import TOOLS, Toolbox

MAX_STEPS = 6
_REPLAYED = {"text", "tool_use", "tool_result"}

SYSTEM = """You are the saylist assistant of one tradesperson (the seller): an electrician, \
plumber, locksmith, handyman, cleaner or AC technician working around Limassol. saylist brings \
them jobs from local customers with the exact address, a booked time and how to get in. You talk \
with the seller in a chat; everything you write is sent to them as a message.

What you do:
- Build and maintain their profile: business name, trade, area, availability, prices, what they \
quote separately, and their phone number.
- When they describe their business or ask to change something, call propose_profile_change. It \
shows them a card with Correct / Change buttons. Nothing is saved until the seller taps Correct, \
and you cannot confirm for them: never say the profile is saved or live after proposing.
- If they say in words that the proposal is right ("yes", "correct"), call show_pending_proposal \
and ask them to tap Correct.
- Answer questions about their profile with get_profile. Never guess what is on it.
- If they give a phone number in text, call offer_phone. If they still need to share one, \
request_phone. You cannot save a phone yourself.
- If they ask to delete their profile or account: say plainly what will be erased (profile, \
phone, this conversation) and that they will stop getting jobs, and ask them to confirm. Call \
delete_profile only when their next message clearly says yes. Never suggest deleting yourself.
- Job requests reach them as separate messages with their own buttons. You cannot accept, \
decline or change jobs; tell them to use the buttons on the job message.

Style: short and plain. One or two sentences; no markdown, no HTML. A card already shows the \
profile, so do not repeat its contents. Reply in the language the seller writes in. If a \
message is not about their saylist profile or jobs, say briefly what you can help with.

Lines in [square brackets] are notes from the system (context, button taps, shared contacts), \
not the seller's words."""


def _replayable(message: dict[str, Any]) -> dict[str, Any]:
    content = [b for b in message["content"] if b.get("type") in _REPLAYED]
    return {"role": message["role"], "content": content or [{"type": "text", "text": "…"}]}


def history(turns: list[Turn]) -> list[dict[str, Any]]:
    return [_replayable(m) for turn in turns for m in turn.transcript]


async def context_note(session: AsyncSession, chat_id: int) -> str:
    business = await businesses.get_by_chat(session, chat_id)
    proposal = await businesses.latest_proposal(session, chat_id)
    status = business.status.value if business else "no profile yet"
    phone = "yes" if business and business.phone else "no"
    return (
        f"[Context: {llm.time_context()} Profile status: {status}. Phone on file: {phone}. "
        f"Open proposal waiting for Correct: {'yes' if proposal else 'no'}.]"
    )


async def run(
    session: AsyncSession, chat_id: int, conversation_id: int, past: list[Turn], user_text: str
) -> tuple[list[dict[str, Any]], list[Reply]]:
    """One seller message through the model. Returns this turn's transcript and replies."""
    note = await context_note(session, chat_id)
    turn: list[dict[str, Any]] = [
        {"role": "user", "content": [{"type": "text", "text": f"{note}\n{user_text}"}]}
    ]
    prior = history(past)
    toolbox = Toolbox(session, chat_id, conversation_id)
    replies: list[Reply] = []
    for _ in range(MAX_STEPS):
        step = await llm.tool_step("seller_assistant", SYSTEM, prior + turn, TOOLS)
        turn.append({"role": "assistant", "content": step.content})
        replies.extend(_replies.text(t.strip()) for t in step.texts)
        if not step.tool_calls:
            break
        results: list[dict[str, Any]] = []
        for call in step.tool_calls:
            shown = len(toolbox.replies)
            output, is_error = await toolbox.run(call.name, call.input)
            replies.extend(toolbox.replies[shown:])
            result: dict[str, Any] = {
                "type": "tool_result",
                "tool_use_id": call.id,
                "content": output,
            }
            if is_error:
                result["is_error"] = True
            results.append(result)
        turn.append({"role": "user", "content": results})
    else:
        turn.append({"role": "assistant", "content": [{"type": "text", "text": "(stopped)"}]})
    if not replies:
        replies.append(
            _replies.text("Tell me about your business, or ask me anything about your profile.")
        )
    return turn, replies
