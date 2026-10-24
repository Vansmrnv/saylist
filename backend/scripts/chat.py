"""Talk to the seller assistant from a terminal, no Telegram: `make chat [AS=name]`.

A tiny channel adapter (ADR 0007): what you type becomes an InboundMessage on channel "cli",
replies come back from `channels.receive` and are printed with `channels.render_plain`.
Needs a migrated database and ANTHROPIC_API_KEY (every text goes to the model).

  /start          open the chat (welcome)
  /phone +357...  share a phone, like Telegram's contact button
  1, 2, ...       pick a numbered choice from the last replies
  /quit           leave
"""

import asyncio
import sys
import uuid

from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.modules import assistant, channels, load_all
from app.modules.assistant import InboundKind, InboundMessage

CHANNEL = "cli"


def _inbound(who: str, line: str, last: list[assistant.Reply]) -> InboundMessage | None:
    choices = [c for r in last for c in r.choices]
    base = {"channel": CHANNEL, "external_id": who, "message_id": uuid.uuid4().hex}
    if line == "/start":
        return InboundMessage(**base, kind=InboundKind.START)
    if line.startswith("/phone "):
        return InboundMessage(**base, kind=InboundKind.CONTACT, phone=line.removeprefix("/phone "))
    if line.isdigit() and 1 <= int(line) <= len(choices):
        return InboundMessage(
            **base, kind=InboundKind.CHOICE, choice_value=choices[int(line) - 1].value
        )
    if line.startswith("/") and line != "/profile":
        print("commands: /start, /phone +357..., /profile, /quit, or a choice number")
        return None
    return InboundMessage(**base, kind=InboundKind.TEXT, text=line)


async def main(who: str) -> None:
    load_all()
    if not get_settings().anthropic_api_key:
        print("ANTHROPIC_API_KEY is not set: /start, /phone and choices work, text will not.")
    print(f"Chatting as {CHANNEL}:{who}. /quit to leave.\n")
    last: list[assistant.Reply] = []
    while True:
        try:
            line = (await asyncio.to_thread(input, "you> ")).strip()
        except EOFError:
            break
        if line in ("/quit", "/exit"):
            break
        inbound = _inbound(who, line, last) if line else None
        if inbound is None:
            continue
        async with get_sessionmaker()() as session, session.begin():
            last = await channels.receive(session, inbound)
        for reply in last:
            print("\n" + channels.render_plain(reply) + "\n")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "dev"))
