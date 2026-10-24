"""Business logic. Takes an AsyncSession, flushes, never commits."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules import assistant, messaging
from app.modules.assistant import InboundKind, InboundMessage, Reply
from app.modules.channels import _render
from app.modules.channels._telegram import TELEGRAM

COULD_NOT_HEAR = "Sorry, I couldn't hear that. Please try again or send text."


async def receive(session: AsyncSession, inbound: InboundMessage) -> list[Reply]:
    """The one door from any channel to the seller assistant.

    Returns the replies. For push channels (Telegram) they are also queued in the outbox, in
    the caller's transaction, keyed by the inbound message: a redelivered update queues
    nothing new (ADR 0004). Request/response channels (the dev CLI, a future web chat) show the
    returned replies themselves.
    """
    if inbound.kind == InboundKind.VOICE and not (inbound.text or "").strip():
        replies = [Reply(text=COULD_NOT_HEAR)]  # nothing to give the assistant
    else:
        replies = await assistant.handle(session, inbound)
        if inbound.kind == InboundKind.VOICE:
            replies = [Reply(text=f"🎙 I heard: {inbound.text}"), *replies]
    if inbound.channel == TELEGRAM:
        await _queue_telegram(session, inbound, replies)
    return replies


def outbox_key(inbound: InboundMessage, index: int) -> str:
    return f"seller:{inbound.channel}:{inbound.external_id}:{inbound.message_id}:{index}"


async def _queue_telegram(
    session: AsyncSession, inbound: InboundMessage, replies: list[Reply]
) -> None:
    for index, reply in enumerate(replies):
        text, buttons = _render.telegram(reply)
        await messaging.send(
            session,
            key=outbox_key(inbound, index),
            chat_id=int(inbound.external_id),
            text=text,
            buttons=buttons,
        )
