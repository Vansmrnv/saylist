"""Business logic. Takes an AsyncSession, flushes, never commits."""

from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.messaging import _repository as repo
from app.modules.messaging._models import OutboxKind
from app.modules.messaging._schemas import Button, OutboxView

Buttons = Sequence[Sequence[Button]]


def _dump(buttons: Buttons | None) -> list[list[dict[str, str | None]]] | None:
    return [[b.model_dump() for b in row] for row in buttons] if buttons else None


async def send(
    session: AsyncSession, *, key: str, chat_id: int, text: str, buttons: Buttons | None = None
) -> None:
    """Queue a new message. Delivered after the surrounding transaction commits."""
    await repo.add(
        session, key=key, kind=OutboxKind.SEND, chat_id=chat_id, text=text, buttons=_dump(buttons)
    )
    await session.flush()


async def edit(
    session: AsyncSession, *, key: str, edit_of: str, text: str, buttons: Buttons | None = None
) -> None:
    """Queue a rewrite of the message sent under `edit_of`. No buttons = buttons removed."""
    target = await repo.get_by_key(session, edit_of)
    if target is None:
        return
    await repo.add(
        session,
        key=key,
        kind=OutboxKind.EDIT,
        chat_id=target.chat_id,
        text=text,
        buttons=_dump(buttons),
        edit_of=edit_of,
    )
    await session.flush()


async def list_recent(session: AsyncSession, limit: int = 30) -> list[OutboxView]:
    return [OutboxView.model_validate(m) for m in await repo.recent(session, limit)]
