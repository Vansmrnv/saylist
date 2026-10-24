"""Business logic. Takes an AsyncSession, flushes, never commits."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.businesses import _ai
from app.modules.businesses import _repository as repo
from app.modules.businesses._models import Business, BusinessProposal, ProposalStatus
from app.modules.businesses._schemas import (
    BusinessStatus,
    BusinessView,
    ConfirmOutcome,
    Profile,
    ProposalView,
    Trade,
)


def _view(business: Business) -> BusinessView:
    return BusinessView.model_validate(business)


def _apply(business: Business, profile: Profile) -> None:
    data = profile.model_dump(mode="json")
    for field in Profile.model_fields:
        setattr(business, field, data[field])


async def _get_or_create(session: AsyncSession, chat_id: int) -> Business:
    business = await repo.get_by_chat(session, chat_id)
    if business is None:
        business = await repo.add(session, Business(telegram_chat_id=chat_id))
    return business


async def get(session: AsyncSession, business_id: int) -> BusinessView | None:
    business = await repo.get(session, business_id)
    return _view(business) if business else None


async def get_by_chat(session: AsyncSession, chat_id: int) -> BusinessView | None:
    business = await repo.get_by_chat(session, chat_id)
    return _view(business) if business else None


async def list_active_for_trade(session: AsyncSession, trade: Trade) -> list[BusinessView]:
    return [_view(b) for b in await repo.active_for_trade(session, trade)]


async def list_all(session: AsyncSession, limit: int = 100) -> list[BusinessView]:
    return [_view(b) for b in await repo.all_newest_first(session, limit)]


async def pending_profile(session: AsyncSession, business_id: int) -> Profile | None:
    proposal = await repo.latest_open_proposal(session, business_id)
    return Profile.model_validate(proposal.profile) if proposal else None


async def propose(session: AsyncSession, chat_id: int, text: str) -> ProposalView:
    """Turn the owner's message into a proposal: a new profile, or an edit of the latest one."""
    business = await _get_or_create(session, chat_id)
    open_proposal = await repo.latest_open_proposal(session, business.id)
    if open_proposal:
        profile = await _ai.update(Profile.model_validate(open_proposal.profile), text)
    elif business.trade is not None:
        profile = await _ai.update(_view(business).profile(), text)
    else:
        profile = await _ai.extract(text)
    await repo.supersede_open_proposals(session, business.id)
    proposal = await repo.add_proposal(
        session,
        BusinessProposal(
            business_id=business.id, profile=profile.model_dump(mode="json"), source_text=text
        ),
    )
    return ProposalView(
        proposal_id=proposal.id,
        business_id=business.id,
        profile=profile,
        phone=business.phone,
        business_status=business.status,
        missing_basics=profile.missing_basics(),
    )


async def _confirm(
    session: AsyncSession, business: Business, proposal: BusinessProposal
) -> ConfirmOutcome:
    profile = Profile.model_validate(proposal.profile)
    if profile.missing_basics():
        return ConfirmOutcome.NEEDS_BASICS
    if not business.phone:
        proposal.status = ProposalStatus.AWAITING_PHONE
        await session.flush()
        return ConfirmOutcome.NEEDS_PHONE
    was_active = business.status == BusinessStatus.ACTIVE
    _apply(business, profile)
    business.status = BusinessStatus.ACTIVE
    proposal.status = ProposalStatus.CONFIRMED
    await session.flush()
    return ConfirmOutcome.UPDATED if was_active else ConfirmOutcome.LIVE


async def confirm(session: AsyncSession, chat_id: int, proposal_id: int) -> ConfirmOutcome:
    """The owner tapped Correct on proposal `proposal_id`. Only the latest one counts."""
    business = await repo.get_by_chat(session, chat_id)
    if business is None:
        return ConfirmOutcome.STALE
    proposal = await repo.latest_open_proposal(session, business.id)
    if proposal is None or proposal.id != proposal_id:
        return ConfirmOutcome.STALE
    return await _confirm(session, business, proposal)


async def set_phone(session: AsyncSession, chat_id: int, phone: str) -> ConfirmOutcome | None:
    """Save the owner's phone; applies a proposal that was waiting for it."""
    business = await _get_or_create(session, chat_id)
    business.phone = phone
    await session.flush()
    proposal = await repo.latest_open_proposal(session, business.id)
    if proposal and proposal.status == ProposalStatus.AWAITING_PHONE:
        return await _confirm(session, business, proposal)
    return None


async def create_active(
    session: AsyncSession, chat_id: int, phone: str, profile: Profile
) -> BusinessView:
    """Seeding and tests: a live business without the proposal step."""
    business = Business(telegram_chat_id=chat_id, phone=phone, status=BusinessStatus.ACTIVE)
    _apply(business, profile)
    return _view(await repo.add(session, business))
