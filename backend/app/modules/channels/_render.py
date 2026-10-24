"""Reply -> what a channel shows. The assistant's replies are plain text; escaping happens here."""

from html import escape

from app.modules import messaging
from app.modules.assistant import Reply, ReplyKind

CHOICE_PREFIX = "ch:"  # Telegram callback_data of an assistant choice: "ch:<value>"
SHARE_PHONE = "📱 Share phone number"


def telegram(reply: Reply) -> tuple[str, list[list[messaging.Button]] | None]:
    """Telegram HTML (parse_mode=HTML) and buttons: choices become inline buttons, a contact
    request a reply keyboard with Telegram's share-contact button."""
    lines: list[str] = []
    if reply.title:
        lines.append(f"<b>{escape(reply.title)}</b>")
    lines += [f"{escape(f.label)}: {escape(f.value)}" for f in reply.fields]
    if reply.text:
        if lines:
            lines.append("")
        lines.append(escape(reply.text))
    html = "\n".join(lines)
    if reply.kind == ReplyKind.ASK_CONTACT:
        return html, [[messaging.Button(text=SHARE_PHONE, request_contact=True)]]
    if reply.choices:
        row = [
            messaging.Button(text=c.label, callback_data=f"{CHOICE_PREFIX}{c.value}")
            for c in reply.choices
        ]
        return html, [row]
    return html, None


def plain(reply: Reply) -> str:
    """Plain text for terminals and logs; choices are numbered from 1."""
    lines: list[str] = []
    if reply.title:
        lines.append(reply.title)
    lines += [f"  {f.label}: {f.value}" for f in reply.fields]
    if reply.text:
        lines.append(reply.text)
    lines += [f"  [{i}] {c.label}" for i, c in enumerate(reply.choices, 1)]
    if reply.kind == ReplyKind.ASK_CONTACT:
        lines.append("  (share a phone with: /phone +357...)")
    return "\n".join(lines)
