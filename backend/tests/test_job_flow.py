"""The whole job flow against Postgres, with the LLM stubbed and Telegram faked."""

from collections.abc import AsyncIterator
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.db import get_engine
from app.modules import businesses, jobs, messaging
from app.modules.businesses import _ai as business_ai
from app.modules.jobs import _ai as jobs_ai
from app.modules.messaging._models import OutboxMessage

pytestmark = pytest.mark.db

WEEKDAYS: Any = ["mon", "tue", "wed", "thu", "fri"]
REQUEST = jobs.JobRequestIn(
    trade="electrician",
    when="any weekday after 4pm",
    street_address="Agias Fylaxeos 45",
    unit="Flat 3, 2nd floor",
    city="Limassol",
    access_notes="Gate code 1234, bell 'Alex'",
    description="Kitchen sockets dead",
    customer_name="Alex",
    customer_phone="+357 99 123456",
)


def _read(address_ok: bool = True) -> jobs_ai.RequestOut:
    return jobs_ai.RequestOut(
        trade="electrician",
        when_text="Any weekday after 16:00",
        when=jobs.When(
            asap=False, days_of_week=WEEKDAYS, dates=[], start_time="16:00", end_time="24:00"
        ),
        address_specific=address_ok,
        address_problem=None if address_ok else "Ask for the street name and house number.",
        maps_query="Agias Fylaxeos 45, Limassol, Cyprus",
    )


class FakeTelegram:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str, Any]] = []
        self.edits: list[tuple[int, int, str, Any]] = []

    async def send(self, chat_id: int, text: str, buttons: list[Any] | None) -> int:
        if chat_id < 0:
            raise messaging.PermanentError("chat not found")
        self.sent.append((chat_id, text, buttons))
        return 1000 + len(self.sent)

    async def edit(
        self, chat_id: int, message_id: int, text: str, buttons: list[Any] | None
    ) -> None:
        self.edits.append((chat_id, message_id, text, buttons))


@pytest.fixture
async def maker(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Sessions on one connection whose work is rolled back after the test."""

    async def fake_read(request: jobs.JobRequestIn) -> jobs_ai.RequestOut:
        return _read(address_ok=any(c.isdigit() for c in request.street_address))

    async def fake_prices(when_text: str, when: jobs.When, found: list[Any]) -> dict[int, str]:
        return {b.id: f"€{b.id} callout" for b in found}

    monkeypatch.setattr(jobs_ai, "read_request", fake_read)
    monkeypatch.setattr(jobs_ai, "price_notes", fake_prices)
    async with get_engine().connect() as connection:
        transaction = await connection.begin()
        yield async_sessionmaker(
            bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
        )
        await transaction.rollback()


async def _seed(session: AsyncSession) -> tuple[int, int, int]:
    def profile(slots: list[businesses.TimeSlot] | None) -> businesses.Profile:
        return businesses.Profile(
            name="Biz",
            trade=businesses.Trade.ELECTRICIAN,
            area="Limassol",
            availability=businesses.Availability(always_available=slots is None, slots=slots or []),
            pricing_text="€30",
        )

    a = await businesses.create_active(session, 501, "+357 1", profile(None))
    b = await businesses.create_active(
        session,
        502,
        "+357 2",
        profile([businesses.TimeSlot(days=WEEKDAYS, start="17:00", end="23:00")]),
    )
    mornings = [businesses.TimeSlot(days=WEEKDAYS, start="08:00", end="15:00")]
    c = await businesses.create_active(session, -503, "+357 3", profile(mornings))
    return a.id, b.id, c.id


async def _offers(session: AsyncSession, job_id: int) -> dict[int, jobs.OfferAdminView]:
    return {o.business_id: o for o in await jobs.list_recent_offers(session) if o.job_id == job_id}


async def test_vague_address_is_refused_before_anything_is_created(maker: Any) -> None:
    async with maker() as session, session.begin():
        await _seed(session)
        result = await jobs.draft_request(
            session, REQUEST.model_copy(update={"street_address": "Mouttagiaka"}), "assistant"
        )
    assert result.outcome == jobs.Outcome.INVALID
    assert "house number" in result.why
    assert result.job is None


async def test_full_flow_from_draft_to_done(maker: Any) -> None:
    async with maker() as session, session.begin():
        a, b, _ = await _seed(session)
        draft = await jobs.draft_request(session, REQUEST, "assistant")
    assert draft.outcome == jobs.Outcome.DONE and draft.job
    job_id = draft.job.job_id
    assert draft.job.status == jobs.JobStatus.DRAFT
    assert len(draft.job.quotes) == 2  # the mornings-only business is not free after 16:00

    async with maker() as session, session.begin():
        offers = await _offers(session, job_id)
        assert set(offers) == {a, b}
        assert all(o.answer == jobs.OfferAnswer.PROPOSED for o in offers.values())
        assert offers[b].options[0].endswith("17:00")  # its hours start at 17:00
        assert (await session.execute(select(OutboxMessage))).first() is None  # nothing sent yet
        confirmed = await jobs.confirm_request(session, job_id)
    assert confirmed.outcome == jobs.Outcome.DONE

    async with maker() as session, session.begin():
        again = await jobs.confirm_request(session, job_id)
    assert again.outcome == jobs.Outcome.NO_CHANGE

    telegram = FakeTelegram()
    await messaging.deliver_due(maker, telegram)
    assert sorted(chat for chat, _, _ in telegram.sent) == [501, 502]

    async with maker() as session, session.begin():
        offers = await _offers(session, job_id)
        assert await jobs.accept_offer(session, offers[a].id, b, 0) == "This offer isn't yours."
        assert (await jobs.accept_offer(session, offers[b].id, b, 0)).startswith("The job is yours")
        assert (
            await jobs.accept_offer(session, offers[a].id, a, 0)
            == "Sorry, this job was already taken."
        )
        view = (await jobs.get_jobs(session, [job_id]))[0]
    assert view.status == jobs.JobStatus.BOOKED
    assert view.scheduled_for is not None and view.scheduled_for.hour == 17

    async with maker() as session, session.begin():
        assert (
            await jobs.advance(session, job_id, a, jobs.BusinessAction.ARRIVED)
            == "This job isn't yours."
        )
        await jobs.advance(session, job_id, b, jobs.BusinessAction.ON_THE_WAY, 20)
        assert (await jobs.get_jobs(session, [job_id]))[0].status == jobs.JobStatus.ON_THE_WAY
        await jobs.advance(session, job_id, b, jobs.BusinessAction.ARRIVED)
        token = (await jobs.get_jobs(session, [job_id]))[0].token
        assert await jobs.customer_coming(session, token)
        assert await jobs.customer_coming(session, token)  # idempotent: one ping only
        await jobs.advance(session, job_id, b, jobs.BusinessAction.DONE)
        assert (
            await jobs.advance(session, job_id, b, jobs.BusinessAction.DONE)
            == "That step no longer applies."
        )
        view = (await jobs.get_jobs(session, [job_id]))[0]
    assert view.status == jobs.JobStatus.DONE
    kinds = [e.kind for e in view.timeline]
    assert kinds.count(jobs.EventKind.CUSTOMER_COMING) == 1
    assert kinds[-1] == jobs.EventKind.DONE

    await messaging.deliver_due(maker, telegram, limit=100)
    pings = [text for chat, text, _ in telegram.sent if "coming to the door" in text]
    assert len(pings) == 1
    final_card = [text for chat, _, text, _ in telegram.edits if chat == 502][-1]
    assert "Job done" in final_card
    loser = [text for chat, _, text, _ in telegram.edits if chat == 501][-1]
    assert "taken by someone else" in loser


async def test_customer_cancel_tells_the_booked_business(maker: Any) -> None:
    async with maker() as session, session.begin():
        a, _, _ = await _seed(session)
        draft = await jobs.draft_request(session, REQUEST, "assistant")
        assert draft.job
        await jobs.confirm_request(session, draft.job.job_id)
        offer = (await _offers(session, draft.job.job_id))[a]
        await jobs.accept_offer(session, offer.id, a, 0)
        result = await jobs.cancel_request(session, draft.job.job_id, "fixed it myself")
        assert result.outcome == jobs.Outcome.DONE
        rows = (await session.execute(select(OutboxMessage.key))).scalars().all()
    assert f"job:{draft.job.job_id}:cancelled" in rows


async def test_nobody_free_is_refused(maker: Any) -> None:
    async with maker() as session, session.begin():
        result = await jobs.draft_request(session, REQUEST, "assistant")  # no businesses at all
    assert result.outcome == jobs.Outcome.REFUSED
    assert result.job and result.job.status == jobs.JobStatus.NO_MATCH


async def test_seeded_fake_chat_fails_without_blocking_others(maker: Any) -> None:
    async with maker() as session, session.begin():
        await messaging.send(session, key="t:1", chat_id=-1, text="to nowhere")
        await messaging.send(session, key="t:2", chat_id=7, text="hello")
        await messaging.edit(session, key="t:1:e", edit_of="t:1", text="edited")
    telegram = FakeTelegram()
    await messaging.deliver_due(maker, telegram)
    async with maker() as session:
        status = dict(
            (await session.execute(select(OutboxMessage.key, OutboxMessage.status))).all()
        )
    assert status == {"t:1": "failed", "t:2": "sent", "t:1:e": "failed"}
    assert telegram.sent == [(7, "hello", None)]


async def test_owner_confirms_after_sharing_phone(
    maker: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_extract(text: str) -> businesses.Profile:
        return businesses.Profile(name="Nikos", trade=businesses.Trade.ELECTRICIAN, area="Limassol")

    monkeypatch.setattr(business_ai, "extract", fake_extract)
    async with maker() as session, session.begin():
        proposal = await businesses.propose(session, 900, "I'm Nikos, electrician in Limassol")
        assert (
            await businesses.confirm(session, 900, proposal.proposal_id)
            == businesses.ConfirmOutcome.NEEDS_PHONE
        )
        assert (await businesses.get_by_chat(session, 900)).status == "draft"  # type: ignore[union-attr]
        assert await businesses.set_phone(session, 900, "+35799") == businesses.ConfirmOutcome.LIVE
        assert (
            await businesses.confirm(session, 900, proposal.proposal_id)
            == businesses.ConfirmOutcome.STALE
        )
        live = await businesses.get_by_chat(session, 900)
    assert live and live.status == "active" and live.name == "Nikos"
