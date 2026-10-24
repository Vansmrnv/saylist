"""Business logic. Takes an AsyncSession, flushes, never commits.

A job moves draft -> open -> booked -> on_the_way -> arrived -> done; every step is one tap by
the business or one call by the customer's assistant, and the other side sees it without a call.
"""

import logging
import secrets
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from urllib.parse import quote_plus

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings, now_local
from app.modules import businesses, messaging
from app.modules.jobs import _ai, _schedule
from app.modules.jobs import _messages as msg
from app.modules.jobs import _repository as repo
from app.modules.jobs._models import Job, JobEvent, JobOffer
from app.modules.jobs._schemas import (
    ACTIVE_STATUSES,
    ArrivalOption,
    BusinessAction,
    EventKind,
    EventView,
    JobRequestIn,
    JobStatus,
    JobView,
    OfferAdminView,
    OfferAnswer,
    Outcome,
    WriteResult,
)

log = logging.getLogger("jobs")

CLOSED_REPLIES = {
    OfferAnswer.ACCEPTED: "You already took this job.",
    OfferAnswer.DECLINED: "You declined this job.",
    OfferAnswer.TOO_LATE: "Sorry, this job was already taken.",
    OfferAnswer.EXPIRED: "This request has expired.",
    OfferAnswer.WITHDRAWN: "The customer cancelled this request.",
    OfferAnswer.PROPOSED: "This request was not sent.",
}


def _now() -> datetime:
    return datetime.now(UTC)


def _local(at: datetime | None) -> datetime | None:
    return at.astimezone(get_settings().tz) if at else None


def _maps_url(query: str) -> str:
    return "https://www.google.com/maps/search/?api=1&query=" + quote_plus(query)


async def _event(session: AsyncSession, job: Job, kind: EventKind, text: str) -> None:
    await repo.add(session, JobEvent(job_id=job.id, kind=kind, note=text))


async def _business_name(session: AsyncSession, business_id: int | None) -> str:
    business = await businesses.get(session, business_id) if business_id else None
    return (business.name if business else None) or "The business"


# --- views ---------------------------------------------------------------------------------


def _status_text(job: Job, name: str, sent_to: int, events: Sequence[JobEvent]) -> str:
    trade = businesses.trade_label(job.trade).lower()
    match job.status:
        case JobStatus.DRAFT:
            return "Draft: nothing has been sent yet."
        case JobStatus.OPEN:
            return f"Sent to {sent_to} {trade}(s). Waiting for the first to accept."
        case JobStatus.BOOKED:
            at = _local(job.scheduled_for)
            return f"{name} is booked for {at:%a %d %b at %H:%M}." if at else f"{name} is booked."
        case JobStatus.ON_THE_WAY:
            eta = _local(job.eta_at)
            return (
                f"{name} is on the way, arriving around {eta:%H:%M}."
                if eta
                else f"{name} is on the way."
            )
        case JobStatus.ARRIVED:
            return f"{name} is at the door."
        case JobStatus.DONE:
            return "Job done."
        case JobStatus.NO_MATCH:
            return f"No {trade} is available. Try another time."
        case JobStatus.EXPIRED:
            return "Nobody accepted in time. Send it again or try another time."
        case JobStatus.CANCELLED:
            last = next((e for e in reversed(events) if e.kind.value.startswith("cancelled")), None)
            return last.note if last else "Cancelled."
    return job.status.value


async def _view(session: AsyncSession, job: Job) -> JobView:
    offers = await repo.offers(session, job.id)
    events = await repo.events(session, job.id)
    business = await businesses.get(session, job.business_id) if job.business_id else None
    name = (business.name if business else None) or "The business"
    sent_to = len(offers) if job.sent_at else 0
    accepted = next((o for o in offers if o.answer == OfferAnswer.ACCEPTED), None)
    return JobView(
        job_id=job.id,
        token=job.token,
        status=job.status,
        status_text=_status_text(job, name, sent_to, events),
        trade=job.trade,
        when=job.when_text,
        address=f"{job.street_address}, {job.unit}, {job.city}",
        access_notes=job.access_notes,
        description=job.description,
        customer_name=job.customer_name,
        maps_url=job.maps_url,
        business_name=business.name if business else None,
        business_phone=business.phone if business else None,
        price_note=accepted.price_note if accepted else None,
        quotes=[
            o.price_note or ""
            for o in offers
            if o.answer in (OfferAnswer.PROPOSED, OfferAnswer.WAITING)
        ],
        scheduled_for=_local(job.scheduled_for),
        eta_at=_local(job.eta_at),
        sent_to=sent_to,
        timeline=[
            EventView(at=_local(e.created_at) or e.created_at, kind=e.kind, text=e.note)
            for e in events
        ],
        created_at=_local(job.created_at) or job.created_at,
    )


async def get_jobs(session: AsyncSession, job_ids: Sequence[int]) -> list[JobView]:
    return [await _view(session, job) for job in await repo.by_ids(session, job_ids)]


async def get_by_token(session: AsyncSession, token: str) -> JobView | None:
    job = await repo.get_by_token(session, token)
    return await _view(session, job) if job else None


async def list_recent(session: AsyncSession, limit: int = 50) -> list[JobView]:
    return [await _view(session, job) for job in await repo.recent(session, limit)]


async def list_recent_offers(session: AsyncSession, limit: int = 50) -> list[OfferAdminView]:
    jobs = await repo.recent(session, limit)
    offers = await repo.offers_for_jobs(session, [j.id for j in jobs])
    return [
        OfferAdminView(
            id=o.id,
            job_id=o.job_id,
            business_id=o.business_id,
            answer=o.answer,
            price_note=o.price_note,
            options=[ArrivalOption.model_validate(x).label for x in o.options],
            answered_at=o.answered_at,
        )
        for o in sorted(offers, key=lambda o: o.id, reverse=True)
    ]


# --- customer side (through the assistant) ---------------------------------------------------


def _invalid(why: str) -> WriteResult:
    return WriteResult(outcome=Outcome.INVALID, why=why)


async def draft_request(session: AsyncSession, request: JobRequestIn, channel: str) -> WriteResult:
    """Check the request and find who is free. Sends nothing: confirming is a second step
    (ADR 0005)."""
    blank = [name for name, value in request.model_dump().items() if not str(value).strip()]
    if blank:
        return _invalid(f"Missing {', '.join(blank)}. Ask the customer, then call again.")
    if sum(c.isdigit() for c in request.customer_phone) < 6:
        return _invalid(
            "customer_phone does not look like a phone number. Ask the customer for it."
        )

    read = await _ai.read_request(request)
    if read.trade is None:
        return _invalid("Unclear which tradesperson is needed. Ask the customer what the job is.")
    if read.when is None:
        return _invalid("No time given. Ask the customer when they need it.")
    if not read.address_specific:
        return _invalid(
            (read.address_problem or "Ask for the street name and house number.")
            + " The business must find the door without calling."
        )

    job = Job(
        token=secrets.token_urlsafe(9),
        channel=channel,
        status=JobStatus.DRAFT,
        trade=read.trade,
        when_text=read.when_text or request.when,
        when=read.when.model_dump(),
        street_address=request.street_address.strip(),
        unit=request.unit.strip(),
        city=request.city.strip(),
        access_notes=request.access_notes.strip(),
        maps_url=_maps_url(read.maps_query or f"{request.street_address}, {request.city}"),
        description=request.description.strip(),
        customer_name=request.customer_name.strip(),
        customer_phone=request.customer_phone.strip(),
    )
    await repo.add(session, job)
    await _event(session, job, EventKind.REQUESTED, "Request created")

    now = now_local()
    candidates = await businesses.list_active_for_trade(session, businesses.Trade(read.trade))
    options = {
        b.id: _schedule.arrival_options(
            read.when, b.availability or businesses.Availability(always_available=False), now
        )
        for b in candidates
    }
    free = [b for b in candidates if options[b.id]]
    log.info(
        "job %s: %d %s(s), %d free %s",
        job.id,
        len(candidates),
        read.trade,
        len(free),
        job.when_text,
    )
    if not free:
        await repo.move(session, job.id, [JobStatus.DRAFT], {"status": JobStatus.NO_MATCH})
        await repo.get(session, job.id)
        await _event(session, job, EventKind.NO_MATCH, "Nobody is free at that time")
        return WriteResult(
            outcome=Outcome.REFUSED,
            why=f"No {read.trade} is free for: {job.when_text}. Suggest another time, call again.",
            job=await _view(session, job),
        )

    notes = await _ai.price_notes(job.when_text, read.when, free)
    for b in free:
        await repo.add(
            session,
            JobOffer(
                job_id=job.id,
                business_id=b.id,
                price_note=notes.get(b.id) or b.pricing_text,
                options=[o.model_dump(mode="json") for o in options[b.id]],
                answer=OfferAnswer.PROPOSED,
            ),
        )
    return WriteResult(
        outcome=Outcome.DONE,
        why=(
            f"Draft ready, nothing sent yet. {len(free)} {read.trade}(s) are free; prices are "
            "in job.quotes. Read the address, time and prices back to the customer, then call "
            "job_request_confirm with this job_id."
        ),
        job=await _view(session, job),
    )


async def confirm_request(session: AsyncSession, job_id: int) -> WriteResult:
    job = await repo.get(session, job_id)
    if job is None:
        return WriteResult(outcome=Outcome.NOT_FOUND, why=f"No job {job_id}.")
    if job.status != JobStatus.DRAFT:
        if job.status in (JobStatus.OPEN, *ACTIVE_STATUSES, JobStatus.DONE):
            return WriteResult(
                outcome=Outcome.NO_CHANGE, why="Already sent.", job=await _view(session, job)
            )
        return WriteResult(
            outcome=Outcome.REFUSED,
            why=f"This job is {job.status.value}; create a new request.",
            job=await _view(session, job),
        )
    if not await repo.move(
        session, job.id, [JobStatus.DRAFT], {"status": JobStatus.OPEN, "sent_at": _now()}
    ):
        return WriteResult(outcome=Outcome.NO_CHANGE, why="Already sent.")
    job = await repo.get(session, job_id)
    assert job is not None
    offers = [o for o in await repo.offers(session, job.id) if o.answer == OfferAnswer.PROPOSED]
    for offer in offers:
        business = await businesses.get(session, offer.business_id)
        if business is None:
            continue
        offer.answer = OfferAnswer.WAITING
        await messaging.send(
            session,
            key=msg.offer_key(offer.id),
            chat_id=business.telegram_chat_id,
            text=msg.offer_text(job, offer),
            buttons=msg.offer_buttons(offer),
        )
    trade = businesses.trade_label(job.trade).lower()
    await _event(session, job, EventKind.SENT, f"Sent to {len(offers)} {trade}(s)")
    timeout = get_settings().request_timeout_minutes
    return WriteResult(
        outcome=Outcome.DONE,
        why=(
            f"Sent to {len(offers)} {trade}(s). The first to accept picks a concrete arrival time. "
            f"Expires in {timeout:g} min if nobody accepts. Give the customer the tracking link: "
            "it shows live when the business is booked, on the way and at the door."
        ),
        job=await _view(session, job),
    )


async def cancel_request(session: AsyncSession, job_id: int, reason: str) -> WriteResult:
    job = await repo.get(session, job_id)
    if job is None:
        return WriteResult(outcome=Outcome.NOT_FOUND, why=f"No job {job_id}.")
    if job.status in (JobStatus.CANCELLED, JobStatus.NO_MATCH, JobStatus.EXPIRED):
        return WriteResult(outcome=Outcome.NO_CHANGE, why=f"The job is already {job.status.value}.")
    if job.status in (JobStatus.ARRIVED, JobStatus.DONE):
        return WriteResult(
            outcome=Outcome.REFUSED,
            why="The business is already at the door or finished; sort it out with them directly.",
            job=await _view(session, job),
        )
    cancellable = [JobStatus.DRAFT, JobStatus.OPEN, JobStatus.BOOKED, JobStatus.ON_THE_WAY]
    if not await repo.move(session, job.id, cancellable, {"status": JobStatus.CANCELLED}):
        return WriteResult(outcome=Outcome.NO_CHANGE, why="The job changed; check it again.")
    job = await repo.get(session, job_id)
    assert job is not None
    note = "Cancelled by the customer" + (f": {reason}" if reason.strip() else "")
    await _event(session, job, EventKind.CANCELLED_BY_CUSTOMER, note)
    for offer in await repo.offers(session, job.id):
        if offer.answer == OfferAnswer.PROPOSED:
            offer.answer = OfferAnswer.WITHDRAWN
        elif offer.answer == OfferAnswer.WAITING:
            offer.answer = OfferAnswer.WITHDRAWN
            await _close_offer(session, job, offer, "❌ The customer cancelled this request.")
        elif offer.answer == OfferAnswer.ACCEPTED:
            await _refresh_card(session, job, offer)
            business = await businesses.get(session, offer.business_id)
            if business:
                await messaging.send(
                    session,
                    key=f"job:{job.id}:cancelled",
                    chat_id=business.telegram_chat_id,
                    text=f"❌ The customer cancelled job #{job.id}. {reason}".strip(),
                )
    await session.flush()
    return WriteResult(outcome=Outcome.DONE, why="Cancelled.", job=await _view(session, job))


async def customer_coming(session: AsyncSession, token: str) -> bool:
    """The customer tapped "I'm coming down" on the tracking page. Pings the business once."""
    job = await repo.get_by_token(session, token)
    if job is None or job.status != JobStatus.ARRIVED:
        return False
    if await repo.has_event(session, job.id, EventKind.CUSTOMER_COMING):
        return True
    await _event(session, job, EventKind.CUSTOMER_COMING, "You're coming to the door")
    offer = await repo.accepted_offer(session, job.id)
    business = await businesses.get(session, job.business_id) if job.business_id else None
    if offer and business:
        await messaging.send(
            session,
            key=f"job:{job.id}:coming",
            chat_id=business.telegram_chat_id,
            text=f"👋 <b>{job.customer_name}</b> is coming to the door.",
        )
        await _refresh_card(session, job, offer, "👋 The customer is coming to the door.")
    return True


# --- business side (Telegram buttons) ------------------------------------------------------


async def _close_offer(session: AsyncSession, job: Job, offer: JobOffer, status_line: str) -> None:
    await messaging.edit(
        session,
        key=f"{msg.offer_key(offer.id)}:{uuid.uuid4().hex[:12]}",
        edit_of=msg.offer_key(offer.id),
        text=msg.offer_text(job, offer, footer=status_line),
    )


async def _refresh_card(
    session: AsyncSession, job: Job, offer: JobOffer, extra: str | None = None
) -> None:
    await messaging.edit(
        session,
        key=f"{msg.offer_key(offer.id)}:{uuid.uuid4().hex[:12]}",
        edit_of=msg.offer_key(offer.id),
        text=msg.job_card_text(job, offer, extra),
        buttons=msg.job_card_buttons(job),
    )


async def accept_offer(session: AsyncSession, offer_id: int, business_id: int, option: int) -> str:
    """The business tapped one of the times. The first tap claims the job. Returns a toast."""
    offer = await repo.get_offer(session, offer_id)
    if offer is None or offer.business_id != business_id:
        return "This offer isn't yours."
    if offer.answer != OfferAnswer.WAITING:
        return CLOSED_REPLIES[offer.answer]
    options = [ArrivalOption.model_validate(o) for o in offer.options]
    if not 0 <= option < len(options):
        return "Please pick one of the times."
    chosen, now = options[option], _now()
    if chosen.minutes is not None:  # ASAP: they leave now
        at = now + timedelta(minutes=chosen.minutes)
        values = {"status": JobStatus.ON_THE_WAY, "scheduled_for": at, "eta_at": at}
    else:
        values = {"status": JobStatus.BOOKED, "scheduled_for": chosen.at}
    claimed = await repo.move(
        session, offer.job_id, [JobStatus.OPEN], {**values, "business_id": business_id}
    )
    job = await repo.get(session, offer.job_id)
    assert job is not None
    offer.answered_at = now
    if not claimed:
        offer.answer = OfferAnswer.TOO_LATE
        await _close_offer(session, job, offer, "😔 Sorry, this job was already taken.")
        return "Sorry, this job was already taken."

    offer.answer = OfferAnswer.ACCEPTED
    name = await _business_name(session, business_id)
    if chosen.minutes is not None:
        eta = _local(job.eta_at)
        await _event(session, job, EventKind.ON_THE_WAY, f"{name} is on the way, ETA {eta:%H:%M}")
    else:
        await _event(session, job, EventKind.BOOKED, f"{name} booked for {chosen.label}")
    log.info("job %s taken by business %s for %s", job.id, business_id, chosen.label)
    await _refresh_card(session, job, offer)
    for other in await repo.offers(session, job.id):
        if other.id != offer.id and other.answer == OfferAnswer.WAITING:
            other.answer, other.answered_at = OfferAnswer.TOO_LATE, now
            await _close_offer(session, job, other, "🔒 This job was taken by someone else.")
    await session.flush()
    return "The job is yours! The customer can see it."


async def decline_offer(session: AsyncSession, offer_id: int, business_id: int) -> str:
    offer = await repo.get_offer(session, offer_id)
    if offer is None or offer.business_id != business_id:
        return "This offer isn't yours."
    if offer.answer != OfferAnswer.WAITING:
        return CLOSED_REPLIES[offer.answer]
    job = await repo.get(session, offer.job_id)
    assert job is not None
    offer.answer, offer.answered_at = OfferAnswer.DECLINED, _now()
    await _close_offer(session, job, offer, "❌ Declined.")
    answers = {o.answer for o in await repo.offers(session, job.id)}
    if answers == {OfferAnswer.DECLINED} and await repo.move(
        session, job.id, [JobStatus.OPEN], {"status": JobStatus.NO_MATCH}
    ):
        await _event(session, job, EventKind.NO_MATCH, "Every business declined")
    await session.flush()
    return "Declined."


_TRANSITIONS: dict[BusinessAction, tuple[list[JobStatus], JobStatus, EventKind]] = {
    BusinessAction.ON_THE_WAY: ([JobStatus.BOOKED], JobStatus.ON_THE_WAY, EventKind.ON_THE_WAY),
    BusinessAction.ARRIVED: (
        [JobStatus.BOOKED, JobStatus.ON_THE_WAY],
        JobStatus.ARRIVED,
        EventKind.ARRIVED,
    ),
    BusinessAction.DONE: ([JobStatus.ARRIVED], JobStatus.DONE, EventKind.DONE),
    BusinessAction.CANCEL: (
        [JobStatus.BOOKED, JobStatus.ON_THE_WAY],
        JobStatus.CANCELLED,
        EventKind.CANCELLED_BY_BUSINESS,
    ),
}


async def advance(
    session: AsyncSession,
    job_id: int,
    business_id: int,
    action: BusinessAction,
    minutes: int | None = None,
) -> str:
    """One tap on the job card. Returns a toast."""
    job = await repo.get(session, job_id)
    if job is None or job.business_id != business_id:
        return "This job isn't yours."
    from_statuses, to_status, kind = _TRANSITIONS[action]
    values: dict[str, object] = {"status": to_status}
    if action == BusinessAction.ON_THE_WAY:
        values["eta_at"] = _now() + timedelta(minutes=minutes or 20)
    moved = await repo.move(session, job_id, from_statuses, values, business_id=business_id)
    job = await repo.get(session, job_id)
    offer = await repo.accepted_offer(session, job_id)
    assert job is not None
    if not moved:
        if offer:
            await _refresh_card(session, job, offer)
        return "That step no longer applies."
    name = await _business_name(session, business_id)
    eta = _local(job.eta_at)
    texts = {
        BusinessAction.ON_THE_WAY: (
            f"{name} is on the way, ETA {eta:%H:%M}" if eta else "On the way"
        ),
        BusinessAction.ARRIVED: f"{name} is at the door",
        BusinessAction.DONE: "Job done",
        BusinessAction.CANCEL: f"{name} can't make it. Ask your assistant to send it again.",
    }
    await _event(session, job, kind, texts[action])
    if offer:
        await _refresh_card(session, job, offer)
    await session.flush()
    return {
        BusinessAction.ON_THE_WAY: "The customer sees you're on the way.",
        BusinessAction.ARRIVED: "The customer is told you're at the door.",
        BusinessAction.DONE: "Marked as done. Thanks!",
        BusinessAction.CANCEL: "Cancelled. The customer is told.",
    }[action]


# --- expiry --------------------------------------------------------------------------------


async def expire_stale(session: AsyncSession) -> int:
    """Open jobs nobody took, and drafts never confirmed, expire. Returns how many."""
    settings, now = get_settings(), _now()
    count = 0
    for job in await repo.stale(
        session, JobStatus.OPEN, now - timedelta(minutes=settings.request_timeout_minutes)
    ):
        if not await repo.move(session, job.id, [JobStatus.OPEN], {"status": JobStatus.EXPIRED}):
            continue
        count += 1
        log.info("job %s expired", job.id)
        await _event(session, job, EventKind.EXPIRED, "Nobody accepted in time")
        for offer in await repo.offers(session, job.id):
            if offer.answer == OfferAnswer.WAITING:
                offer.answer, offer.answered_at = OfferAnswer.EXPIRED, now
                await _close_offer(session, job, offer, "⌛ This request expired.")
    for job in await repo.stale(
        session, JobStatus.DRAFT, now - timedelta(minutes=settings.draft_timeout_minutes)
    ):
        if not await repo.move(session, job.id, [JobStatus.DRAFT], {"status": JobStatus.EXPIRED}):
            continue
        count += 1
        await _event(session, job, EventKind.EXPIRED, "The draft was never confirmed")
        for offer in await repo.offers(session, job.id):
            offer.answer = OfferAnswer.WITHDRAWN
    await session.flush()
    return count
