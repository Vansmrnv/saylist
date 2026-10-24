"""Business logic. Takes an AsyncSession, flushes, never commits."""

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules import businesses
from app.modules.assistant import _agent, _replies
from app.modules.assistant import _repository as repo
from app.modules.assistant._identity import business_chat_id
from app.modules.assistant._models import Turn
from app.modules.assistant._schemas import InboundKind, InboundMessage, Reply, ReplyKind
from app.modules.assistant._tools import normalize_phone

log = logging.getLogger("assistant")

HISTORY_TURNS = 20


async def handle(session: AsyncSession, inbound: InboundMessage) -> list[Reply]:
    """Answer one seller message. Idempotent per `(channel, external_id, message_id)`: a
    redelivered message gets the replies stored the first time, and nothing runs again."""
    conversation = await repo.lock_conversation(session, inbound.channel, inbound.external_id)
    conversation_id = conversation.id  # read before any savepoint rollback can expire it
    done = await repo.get_turn(session, conversation_id, inbound.message_id)
    if done is not None:
        return [Reply.model_validate(r) for r in done.replies]

    chat_id = business_chat_id(conversation)
    failed = False
    language = _replies.language_picked(inbound.choice_value or "")
    if inbound.kind in (InboundKind.TEXT, InboundKind.VOICE) or (
        inbound.kind == InboundKind.CHOICE and language
    ):
        if language:
            said = f"[The seller chose the language {language}.] {_replies.WELCOME_BRIEF}"
        else:
            said = (inbound.text or "").strip()
            if inbound.kind == InboundKind.VOICE:
                said = f"[Voice note, transcribed] {said}"
        past = await repo.recent_turns(session, conversation_id, HISTORY_TURNS)
        try:
            async with session.begin_nested():  # a failed turn leaves no half-made proposal
                transcript, replies = await _agent.run(
                    session, chat_id, conversation_id, past, said
                )
        except Exception:
            log.exception("assistant turn failed (%s:%s)", inbound.channel, inbound.external_id)
            failed = True
            replies = [_replies.text(_replies.WELCOME if language else _replies.SORRY)]
            transcript = _fixed_transcript(said, replies)
        if language:
            replies = await _with_contact_request(session, chat_id, replies)
    else:
        note, replies = await _fixed_turn(session, chat_id, inbound)
        transcript = _fixed_transcript(note, replies)

    await repo.add_turn(
        session,
        Turn(
            conversation_id=conversation_id,
            inbound_message_id=inbound.message_id,
            inbound=inbound.model_dump(mode="json"),
            transcript=transcript,
            replies=[r.model_dump(mode="json") for r in replies],
            failed=failed,
        ),
    )
    return replies


async def _fixed_turn(
    session: AsyncSession, chat_id: int, inbound: InboundMessage
) -> tuple[str, list[Reply]]:
    """Turns decided by code, not the model: opening the chat, sharing a contact, a choice.
    Confirming is only ever this path (ADR 0003)."""
    if inbound.kind == InboundKind.START:
        return "[The seller opened the chat.]", [_replies.language_choice()]
    if inbound.kind == InboundKind.CONTACT:
        return f"[The seller shared a phone: {inbound.phone}]", await _save_phone(
            session, chat_id, inbound.phone or ""
        )
    value = inbound.choice_value or ""
    note = f"[The seller tapped the choice {value!r}]"
    action, _, arg = value.partition(":")
    if action == _replies.CONFIRM and arg.isdigit():
        outcome = await businesses.confirm(session, chat_id, int(arg))
        return note, [_replies.confirm_outcome(outcome)]
    if action == _replies.CHANGE and arg.isdigit():
        return note, [_replies.text(_replies.ASK_CHANGE)]
    if value == _replies.PHONE_NO:
        return note, [_replies.text("OK, I didn't save it.")]
    if action == _replies.PHONE:
        return note, await _save_phone(session, chat_id, arg)
    return note, [_replies.text(_replies.STALE_CHOICE)]


async def _with_contact_request(
    session: AsyncSession, chat_id: int, replies: list[Reply]
) -> list[Reply]:
    """The welcome asks for the phone: give its last text the channel's share-phone control."""
    business = await businesses.get_by_chat(session, chat_id)
    asks = any(r.kind == ReplyKind.ASK_CONTACT for r in replies)
    if (business and business.phone) or asks or not replies:
        return replies
    last = replies[-1]
    if last.kind != ReplyKind.TEXT:
        return [*replies, _replies.ask_contact()]
    return [*replies[:-1], _replies.ask_contact(last.text)]


async def _save_phone(session: AsyncSession, chat_id: int, raw: str) -> list[Reply]:
    phone = normalize_phone(raw)
    if phone is None:
        return [_replies.text("That doesn't look like a phone number.")]
    outcome = await businesses.set_phone(session, chat_id, phone)
    replies = [_replies.text(f"📞 Saved your phone: {phone}")]
    if outcome is not None:
        replies.append(_replies.confirm_outcome(outcome))
    return replies


def _summary(reply: Reply) -> str:
    """How a fixed reply appears in the model's history."""
    if reply.kind == ReplyKind.CARD:
        return f"[Showed the card: {reply.title}] {reply.text}".strip()
    if reply.kind == ReplyKind.ASK_CONTACT:
        return f"{reply.text} [Asked to share the phone]"
    return reply.text


def _fixed_transcript(note: str, replies: list[Reply]) -> list[dict[str, Any]]:
    return [
        {"role": "user", "content": [{"type": "text", "text": note}]},
        {
            "role": "assistant",
            "content": [{"type": "text", "text": "\n".join(_summary(r) for r in replies)}],
        },
    ]
