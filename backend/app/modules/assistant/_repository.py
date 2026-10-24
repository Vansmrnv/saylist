from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.assistant._models import Conversation, Turn


async def lock_conversation(session: AsyncSession, channel: str, external_id: str) -> Conversation:
    """Get or create the conversation and lock it until the transaction ends, so one seller's
    messages (and redeliveries of the same message) are handled one at a time."""
    await session.execute(
        insert(Conversation)
        .values(channel=channel, external_id=external_id)
        .on_conflict_do_nothing(index_elements=["channel", "external_id"])
    )
    stmt = (
        select(Conversation)
        .where(Conversation.channel == channel, Conversation.external_id == external_id)
        .with_for_update()
    )
    return (await session.execute(stmt)).scalar_one()


async def get_turn(session: AsyncSession, conversation_id: int, message_id: str) -> Turn | None:
    stmt = select(Turn).where(
        Turn.conversation_id == conversation_id, Turn.inbound_message_id == message_id
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def recent_turns(session: AsyncSession, conversation_id: int, limit: int) -> list[Turn]:
    """The last `limit` turns, oldest first."""
    stmt = (
        select(Turn)
        .where(Turn.conversation_id == conversation_id)
        .order_by(Turn.id.desc())
        .limit(limit)
    )
    rows: Sequence[Turn] = (await session.execute(stmt)).scalars().all()
    return list(reversed(rows))


async def add_turn(session: AsyncSession, turn: Turn) -> None:
    session.add(turn)
    await session.flush()
