from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.jobs._models import Job, JobEvent, JobOffer
from app.modules.jobs._schemas import EventKind, JobStatus, OfferAnswer


async def add(session: AsyncSession, row: Job | JobOffer | JobEvent) -> None:
    session.add(row)
    await session.flush()


async def get(session: AsyncSession, job_id: int) -> Job | None:
    return await session.get(Job, job_id, populate_existing=True)


async def get_by_token(session: AsyncSession, token: str) -> Job | None:
    result = await session.execute(select(Job).where(Job.token == token))
    return result.scalar_one_or_none()


async def by_ids(session: AsyncSession, ids: Sequence[int]) -> Sequence[Job]:
    return (await session.execute(select(Job).where(Job.id.in_(ids)))).scalars().all()


async def recent(session: AsyncSession, limit: int) -> Sequence[Job]:
    return (await session.execute(select(Job).order_by(Job.id.desc()).limit(limit))).scalars().all()


async def move(
    session: AsyncSession,
    job_id: int,
    from_statuses: Sequence[JobStatus],
    values: dict[str, Any],
    business_id: int | None = None,
) -> bool:
    """Atomic status change: applies only if the job is still in one of `from_statuses`
    (and assigned to `business_id`, if given). The claim on accept relies on this."""
    stmt = update(Job).where(Job.id == job_id, Job.status.in_(from_statuses))
    if business_id is not None:
        stmt = stmt.where(Job.business_id == business_id)
    result = await session.execute(
        stmt.values(**values).execution_options(synchronize_session=False)
    )
    return bool(result.rowcount)  # type: ignore[attr-defined]


async def stale(session: AsyncSession, status: JobStatus, before: datetime) -> Sequence[Job]:
    """Jobs in `status` since before `before`: drafts by creation, open jobs by sending."""
    since = Job.sent_at if status == JobStatus.OPEN else Job.created_at
    stmt = select(Job).where(Job.status == status, since < before).order_by(Job.id)
    return (await session.execute(stmt)).scalars().all()


async def get_offer(session: AsyncSession, offer_id: int) -> JobOffer | None:
    return await session.get(JobOffer, offer_id, populate_existing=True)


async def offers(session: AsyncSession, job_id: int) -> Sequence[JobOffer]:
    stmt = select(JobOffer).where(JobOffer.job_id == job_id).order_by(JobOffer.id)
    return (await session.execute(stmt)).scalars().all()


async def offers_for_jobs(session: AsyncSession, job_ids: Sequence[int]) -> Sequence[JobOffer]:
    stmt = select(JobOffer).where(JobOffer.job_id.in_(job_ids)).order_by(JobOffer.id)
    return (await session.execute(stmt)).scalars().all()


async def accepted_offer(session: AsyncSession, job_id: int) -> JobOffer | None:
    stmt = select(JobOffer).where(
        JobOffer.job_id == job_id, JobOffer.answer == OfferAnswer.ACCEPTED
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def events(session: AsyncSession, job_id: int) -> Sequence[JobEvent]:
    stmt = select(JobEvent).where(JobEvent.job_id == job_id).order_by(JobEvent.id)
    return (await session.execute(stmt)).scalars().all()


async def has_event(session: AsyncSession, job_id: int, kind: EventKind) -> bool:
    stmt = select(JobEvent.id).where(JobEvent.job_id == job_id, JobEvent.kind == kind).limit(1)
    return (await session.execute(stmt)).first() is not None
