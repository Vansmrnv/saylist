"""Channel rendering and the assistant's channel-neutrality, without a database. (ADR 0007)"""

import ast
from pathlib import Path

from aiogram.types import CallbackQuery, User

from app.modules import channels
from app.modules.assistant import CardField, Choice, InboundKind, Reply, ReplyKind

ASSISTANT = Path(__file__).resolve().parents[1] / "app" / "modules" / "assistant"
CHANNEL_LIBRARIES = ("aiogram", "html", "app.modules.channels", "app.modules.messaging")


def test_the_assistant_knows_no_channel() -> None:
    problems = []
    for path in sorted(ASSISTANT.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            else:
                continue
            problems += [
                f"{path.name}:{node.lineno} imports {n}"
                for n in names
                if n.startswith(CHANNEL_LIBRARIES)
            ]
    assert not problems, "the assistant must stay channel-neutral (ADR 0007): " + str(problems)


CARD = Reply(
    kind=ReplyKind.CARD,
    title="Your <profile>",
    fields=[CardField(label="Name", value="A & B <script>")],
    text="Check it.",
    choices=[Choice(value="confirm:7", label="✅ Correct"), Choice(value="change:7", label="✏️")],
)


def test_telegram_escapes_everything_and_turns_choices_into_buttons() -> None:
    html, buttons = channels.render_telegram(CARD)
    assert html == "<b>Your &lt;profile&gt;</b>\nName: A &amp; B &lt;script&gt;\n\nCheck it."
    assert buttons is not None
    assert [(b.text, b.callback_data) for b in buttons[0]] == [
        ("✅ Correct", "ch:confirm:7"),
        ("✏️", "ch:change:7"),
    ]


def test_telegram_asks_for_the_contact_with_its_own_button() -> None:
    html, buttons = channels.render_telegram(Reply(kind=ReplyKind.ASK_CONTACT, text="Phone?"))
    assert html == "Phone?"
    assert buttons and buttons[0][0].request_contact


def test_plain_numbers_the_choices() -> None:
    text = channels.render_plain(CARD)
    assert "  [1] ✅ Correct" in text and "  [2] ✏️" in text and "<b>" not in text


def _tap(data: str) -> CallbackQuery:
    user = User(id=555, is_bot=False, first_name="Nikos")
    return CallbackQuery(id="cb1", from_user=user, chat_instance="c", data=data)


def test_telegram_taps_become_choices_and_old_cards_still_work() -> None:
    new = channels.telegram_choice(_tap("ch:confirm:3"))
    old = channels.telegram_choice(_tap("prop:ok:3"))
    assert new and old and new == old
    assert (new.kind, new.choice_value, new.external_id, new.message_id) == (
        InboundKind.CHOICE,
        "confirm:3",
        "555",
        "cb:cb1",
    )
    assert channels.telegram_choice(_tap("acc:1:0")) is None  # job buttons are not conversation
