"""Which business a conversation acts for. The one place to change for cross-channel identity.

Today `businesses` is keyed by a Telegram chat id. A Telegram seller is that chat; a seller on
any other channel (the dev CLI, tests, later WhatsApp) gets a synthetic key derived from the
conversation id, far outside the range of real Telegram ids, so nothing sent to it reaches a
real chat (the outbox fails such sends permanently). The entity redesign replaces this with a
seller identity that several channel addresses point to.
"""

from app.modules.assistant._models import Conversation

TELEGRAM = "telegram"
_SYNTHETIC_BASE = 10**15


def business_chat_id(conversation: Conversation) -> int:
    if conversation.channel == TELEGRAM:
        return int(conversation.external_id)
    return -(_SYNTHETIC_BASE + conversation.id)
