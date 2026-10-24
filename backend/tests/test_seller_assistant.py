"""The seller pipeline end to end, with the LLM stubbed: a fake channel (no Telegram) drives a
whole conversation through `channels.receive`, then the Telegram path is checked through the
outbox. (ADR 0007)"""

import json
from collections.abc import AsyncIterator
from itertools import count, pairwise
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core import llm
from app.core.db import get_engine
from app.modules import assistant, businesses, channels, messaging
from app.modules.assistant import InboundKind, InboundMessage, ReplyKind
from app.modules.assistant._models import Conversation
from app.modules.businesses import _ai as business_ai
from app.modules.businesses._models import BusinessProposal
from app.modules.messaging._models import OutboxMessage
from tests.test_job_flow import FakeTelegram

pytestmark = pytest.mark.db

NIKOS = businesses.Profile(
    name="Nikos <Electrics>",
    trade=businesses.Trade.ELECTRICIAN,
    area="Limassol",
    availability_text="Mon–Fri 08:00–17:00",
    pricing_text="€30 minimum callout",
    pricing=[
        businesses.PriceRule(applies_when="always", amount_minor=3000, kind="minimum callout")
    ],
)
_ids = count(1)


def _step(*, text: str | None = None, call: tuple[str, dict[str, Any]] | None = None) -> Any:
    content: list[dict[str, Any]] = [{"type": "thinking", "thinking": "", "signature": "sig"}]
    texts = []
    calls = []
    if text:
        content.append({"type": "text", "text": text})
        texts.append(text)
    if call:
        tool_id = f"toolu_{next(_ids)}"
        content.append({"type": "tool_use", "id": tool_id, "name": call[0], "input": call[1]})
        calls.append(llm.ToolCall(id=tool_id, name=call[0], input=call[1]))
    return llm.ToolStep(
        content=content, texts=texts, tool_calls=calls, stop_reason="tool_use" if call else "end"
    )


class FakeLLM:
    """Plays scripted model steps and checks every request is a valid conversation."""

    def __init__(self) -> None:
        self.script: list[Any] = []
        self.requests: list[list[dict[str, Any]]] = []

    async def tool_step(
        self, task: str, system: str, messages: list[dict[str, Any]], tools: list[Any]
    ) -> Any:
        assert messages[0]["role"] == "user"
        for a, b in pairwise(messages):
            assert a["role"] != b["role"], "roles must alternate"
        last_assistant = [m for m in messages if m["role"] == "assistant"]
        if messages[-1]["content"][0].get("type") == "tool_result":
            asked = {b["id"] for b in last_assistant[-1]["content"] if b["type"] == "tool_use"}
            assert {r["tool_use_id"] for r in messages[-1]["content"]} == asked
        self.requests.append(json.loads(json.dumps(messages)))
        if not self.script:
            raise AssertionError("the model was called more often than scripted")
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


@pytest.fixture
async def maker(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    async with get_engine().connect() as connection:
        transaction = await connection.begin()
        yield async_sessionmaker(
            bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
        )
        await transaction.rollback()


@pytest.fixture
def model(monkeypatch: pytest.MonkeyPatch) -> FakeLLM:
    fake = FakeLLM()
    monkeypatch.setattr(llm, "tool_step", fake.tool_step)

    async def extract(text: str) -> businesses.Profile:
        return NIKOS

    async def update(current: businesses.Profile, text: str) -> businesses.Profile:
        return current.model_copy(update={"area": "Paphos"}) if "Paphos" in text else current

    monkeypatch.setattr(business_ai, "extract", extract)
    monkeypatch.setattr(business_ai, "update", update)
    return fake


class FakeChannel:
    """A channel with no Telegram: builds InboundMessages, keeps the replies it got."""

    def __init__(self, maker: async_sessionmaker[AsyncSession], who: str = "seller-1") -> None:
        self.maker, self.who, self.n = maker, who, 0
        self.last: list[assistant.Reply] = []

    async def send(self, kind: InboundKind, message_id: str | None = None, **kw: Any) -> list[Any]:
        self.n += 1
        inbound = InboundMessage(
            channel="fake",
            external_id=self.who,
            message_id=message_id or str(self.n),
            kind=kind,
            **kw,
        )
        async with self.maker() as session, session.begin():
            self.last = await channels.receive(session, inbound)
        return self.last

    def choice(self, label_prefix: str) -> str:
        return next(
            c.value for r in self.last for c in r.choices if c.label.startswith(label_prefix)
        )


async def _fake_chat_id(maker: async_sessionmaker[AsyncSession], who: str) -> int:
    """The synthetic businesses key of a non-Telegram seller (assistant/_identity.py)."""
    async with maker() as session:
        stmt = select(Conversation.id).where(
            Conversation.channel == "fake", Conversation.external_id == who
        )
        return -(10**15 + (await session.execute(stmt)).scalar_one())


async def _business(maker: async_sessionmaker[AsyncSession], chat_id: int) -> Any:
    async with maker() as session:
        return await businesses.get_by_chat(session, chat_id)


async def _proposals(maker: async_sessionmaker[AsyncSession]) -> int:
    async with maker() as session:
        return (await session.execute(select(func.count(BusinessProposal.id)))).scalar_one()


async def test_a_whole_seller_conversation_through_a_fake_channel(
    maker: Any, model: FakeLLM
) -> None:
    chat = FakeChannel(maker)

    hello = await chat.send(InboundKind.START)
    assert [r.kind for r in hello] == [ReplyKind.CHOICES]  # the language, before anything else
    assert [c.label for c in hello[0].choices] == ["🇬🇧 English", "🇷🇺 Русский", "🇬🇷 Ελληνικά"]
    assert not model.requests  # no model call for /start

    # The model writes the welcome in the chosen language; it gets the share-phone control.
    model.script = [_step(text="👋 Здравствуйте!")]
    welcome = await chat.send(InboundKind.CHOICE, choice_value=chat.choice("🇷🇺"))
    assert [(r.kind, r.text) for r in welcome] == [(ReplyKind.ASK_CONTACT, "👋 Здравствуйте!")]
    assert "chose the language 🇷🇺 Русский" in json.dumps(model.requests[0], ensure_ascii=False)

    # Describe the business: the model proposes, the seller gets a card to confirm.
    model.script = [
        _step(call=("propose_profile_change", {"text": "I'm Nikos, electrician in Limassol"})),
        _step(text="Here's your profile. Tap Correct if it's right."),
    ]
    replies = await chat.send(InboundKind.TEXT, text="I'm Nikos, electrician in Limassol")
    card = replies[0]
    assert card.kind == ReplyKind.CARD and card.title == "📝 Your profile (not live yet)"
    assert [c.label for c in card.choices] == ["✅ Correct", "✏️ Change"]
    assert replies[1].text.startswith("Here's your profile")
    sent = json.dumps(model.requests[1], ensure_ascii=False)
    assert "seller opened the chat" in sent and "Русский" in sent  # history has both turns

    # Redelivery of the same message: same replies, no model call, no second proposal.
    calls, proposals = len(model.requests), await _proposals(maker)
    again = await chat.send(InboundKind.TEXT, message_id="3", text="I'm Nikos, ...")
    assert again == replies
    assert len(model.requests) == calls and await _proposals(maker) == proposals

    # The seller says "yes" in words: the model can only show the card again.
    model.script = [
        _step(call=("show_pending_proposal", {})),
        _step(text="Please tap Correct on the card."),
    ]
    replies = await chat.send(InboundKind.TEXT, text="yes that's right")
    assert replies[0].choices and replies[0].choices[0].value == card.choices[0].value

    # Tapping Correct without a phone: kept, phone requested. No model call.
    calls = len(model.requests)
    replies = await chat.send(InboundKind.CHOICE, choice_value=chat.choice("✅"))
    assert [r.kind for r in replies] == [ReplyKind.ASK_CONTACT]
    replies = await chat.send(InboundKind.CONTACT, phone="357 99 123456")
    assert [r.text for r in replies] == [
        "📞 Saved your phone: +35799123456",
        "🚀 You're live. Job requests will arrive here.",
    ]
    assert len(model.requests) == calls

    # A question: answered from get_profile, nothing proposed.
    proposals = await _proposals(maker)
    model.script = [_step(call=("get_profile", {})), _step(text="Your minimum callout is €30.")]
    replies = await chat.send(InboundKind.TEXT, text="what's my callout price?")
    assert [r.text for r in replies] == ["Your minimum callout is €30."]
    tool_result = model.requests[-1][-1]["content"][0]["content"]
    assert '"status": "active"' in tool_result and "3000" in tool_result
    assert await _proposals(maker) == proposals
    # Earlier turns are replayed without thinking blocks; the current one as returned.
    request = model.requests[-1]
    current = len(request) - 3  # user, assistant(tool_use), user(tool_result)
    earlier = json.dumps(request[:current])
    assert '"thinking"' not in earlier and '"thinking"' in json.dumps(request[current:])

    # A follow-up edit, by voice: a new card; the live profile is unchanged until Correct.
    model.script = [
        _step(call=("propose_profile_change", {"text": "I moved to Paphos"})),
        _step(text="Updated. Tap Correct to save."),
    ]
    replies = await chat.send(InboundKind.VOICE, text="I moved to Paphos")
    assert replies[0].text == "🎙 I heard: I moved to Paphos"
    assert replies[1].title == "✏️ Updated profile (not saved yet)"
    assert "[Voice note, transcribed] I moved to Paphos" in json.dumps(model.requests[-2][-1])
    chat_id = await _fake_chat_id(maker, chat.who)
    assert (await _business(maker, chat_id)).area == "Limassol"
    replies = await chat.send(InboundKind.CHOICE, choice_value=chat.choice("✅"))
    assert [r.text for r in replies] == ["✅ Profile updated."]
    live = await _business(maker, chat_id)
    assert live.area == "Paphos" and live.status == "active" and live.phone == "+35799123456"

    # The old card's Correct is stale now.
    replies = await chat.send(InboundKind.CHOICE, choice_value=card.choices[0].value)
    assert replies[0].text == "That card is out of date; use the latest one."
    assert not model.script


async def test_a_typed_phone_is_saved_only_after_the_seller_says_yes(
    maker: Any, model: FakeLLM
) -> None:
    chat = FakeChannel(maker)
    model.script = [
        _step(call=("offer_phone", {"phone": "+357 99 765432"})),
        _step(text="Shall I save it?"),
    ]
    replies = await chat.send(InboundKind.TEXT, text="my number is +357 99 765432")
    assert replies[0].kind == ReplyKind.CHOICES
    assert await _business(maker, await _fake_chat_id(maker, chat.who)) is None  # nothing written
    replies = await chat.send(InboundKind.CHOICE, choice_value=chat.choice("✅"))
    assert replies[0].text == "📞 Saved your phone: +35799765432"


async def test_a_failed_model_call_leaves_nothing_half_done(maker: Any, model: FakeLLM) -> None:
    chat = FakeChannel(maker)
    model.script = [
        _step(call=("propose_profile_change", {"text": "I'm Nikos"})),
        llm.LLMError("boom"),
    ]
    replies = await chat.send(InboundKind.TEXT, text="I'm Nikos")
    assert [r.text for r in replies] == ["Sorry, something went wrong. Please send that again."]
    assert await _proposals(maker) == 0  # the proposal made before the failure was rolled back
    # The conversation goes on: the failed turn is valid history.
    model.script = [_step(text="Tell me about your business.")]
    await chat.send(InboundKind.TEXT, text="hello?")
    assert "I'm Nikos" in json.dumps(model.requests[-1])


async def test_the_welcome_falls_back_to_english_if_the_model_fails(
    maker: Any, model: FakeLLM
) -> None:
    chat = FakeChannel(maker)
    await chat.send(InboundKind.START)
    model.script = [llm.LLMError("boom")]
    welcome = await chat.send(InboundKind.CHOICE, choice_value=chat.choice("🇬🇷"))
    assert [r.kind for r in welcome] == [ReplyKind.ASK_CONTACT]
    assert welcome[0].text.startswith("👋 Hi!")


async def test_unknown_or_forged_choices_are_refused(maker: Any, model: FakeLLM) -> None:
    chat = FakeChannel(maker)
    for value in ["confirm:999", "confirm:x", "delete:everything", "phone:not-a-number", "lang:xx"]:
        replies = await chat.send(InboundKind.CHOICE, choice_value=value)
        assert "Saved" not in replies[0].text and "live" not in replies[0].text
    assert not model.requests


async def test_telegram_replies_go_through_the_outbox_once(maker: Any, model: FakeLLM) -> None:
    inbound = InboundMessage(
        channel="telegram", external_id="777", message_id="42", kind=InboundKind.TEXT, text="hi"
    )
    model.script = [
        _step(call=("propose_profile_change", {"text": "hi"})),
        _step(text="Is <this> right?"),
    ]
    for _ in range(2):  # Telegram redelivers the update
        async with maker() as session, session.begin():
            await channels.receive(session, inbound)
    async with maker() as session:
        keys = (await session.execute(select(OutboxMessage.key))).scalars().all()
    assert sorted(keys) == ["seller:telegram:777:42:0", "seller:telegram:777:42:1"]

    telegram = FakeTelegram()
    await messaging.deliver_due(maker, telegram)
    (chat1, card, buttons), (_, text, _) = telegram.sent
    assert chat1 == 777
    assert "Nikos &lt;Electrics&gt;" in card and "<b>📝 Your profile" in card  # escaped
    assert [b["callback_data"].rsplit(":", 1)[0] for b in buttons[0]] == ["ch:confirm", "ch:change"]
    assert text == "Is &lt;this&gt; right?"
    assert (await _business(maker, 777)).telegram_chat_id == 777  # Telegram identity = chat id
