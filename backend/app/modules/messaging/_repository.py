from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.messaging._models import OutboxKind, OutboxMessage, OutboxStatus


async def add(
    session: AsyncSession,
    *,
    key: str,
    kind: OutboxKind,
    chat_id: int,
    text: str,
    buttons: list[Any] | None,
    edit_of: str | None = None,
) -> None:
    """Insert once per key; a repeated key is a no-op (idempotency)."""
    stmt = (
        insert(OutboxMessage)
        .values(key=key, kind=kind, chat_id=chat_id, text=text, buttons=buttons, edit_of=edit_of)
        .on_conflict_do_nothing(index_elements=["key"])
    )
    await session.execute(stmt)


async def get_by_key(session: AsyncSession, key: str) -> OutboxMessage | None:
    result = await session.execute(select(OutboxMessage).where(OutboxMessage.key == key))
    return result.scalar_one_or_none()


async def lock_due(session: AsyncSession, now: datetime, limit: int) -> Sequence[OutboxMessage]:
    stmt = (
        select(OutboxMessage)
        .where(OutboxMessage.status == OutboxStatus.PENDING, OutboxMessage.next_attempt_at <= now)
        .order_by(OutboxMessage.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    return (await session.execute(stmt)).scalars().all()


async def recent(session: AsyncSession, limit: int) -> Sequence[OutboxMessage]:
    stmt = select(OutboxMessage).order_by(OutboxMessage.id.desc()).limit(limit)
    return (await session.execute(stmt)).scalars().all()
