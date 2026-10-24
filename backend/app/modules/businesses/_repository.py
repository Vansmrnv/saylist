from collections.abc import Sequence

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.businesses._models import Business, BusinessProposal, ProposalStatus
from app.modules.businesses._schemas import BusinessStatus, Trade

OPEN_PROPOSAL = (ProposalStatus.PENDING, ProposalStatus.AWAITING_PHONE)


async def get(session: AsyncSession, business_id: int) -> Business | None:
    return await session.get(Business, business_id)


async def get_by_chat(session: AsyncSession, chat_id: int) -> Business | None:
    result = await session.execute(select(Business).where(Business.telegram_chat_id == chat_id))
    return result.scalar_one_or_none()


async def add(session: AsyncSession, business: Business) -> Business:
    session.add(business)
    await session.flush()
    return business


async def active_for_trade(session: AsyncSession, trade: Trade) -> Sequence[Business]:
    stmt = (
        select(Business)
        .where(Business.status == BusinessStatus.ACTIVE, Business.trade == trade)
        .order_by(Business.id)
    )
    return (await session.execute(stmt)).scalars().all()


async def all_newest_first(session: AsyncSession, limit: int) -> Sequence[Business]:
    stmt = select(Business).order_by(Business.id.desc()).limit(limit)
    return (await session.execute(stmt)).scalars().all()


async def latest_open_proposal(session: AsyncSession, business_id: int) -> BusinessProposal | None:
    stmt = (
        select(BusinessProposal)
        .where(
            BusinessProposal.business_id == business_id, BusinessProposal.status.in_(OPEN_PROPOSAL)
        )
        .order_by(BusinessProposal.id.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def supersede_open_proposals(session: AsyncSession, business_id: int) -> None:
    await session.execute(
        update(BusinessProposal)
        .where(
            BusinessProposal.business_id == business_id, BusinessProposal.status.in_(OPEN_PROPOSAL)
        )
        .values(status=ProposalStatus.SUPERSEDED)
    )


async def add_proposal(session: AsyncSession, proposal: BusinessProposal) -> BusinessProposal:
    session.add(proposal)
    await session.flush()
    return proposal
