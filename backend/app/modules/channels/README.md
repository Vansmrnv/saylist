# channels

<!-- Goal: an agent can work on this module after reading only this file. Keep it current:
     update it in the same commit as the code it describes. -->

## Purpose

Connects the channels sellers write from to the seller assistant (ADR 0007).

## Contract

| Name | Kind | Promise |
|------|------|---------|
| `receive(session, inbound) -> list[Reply]` | service | The one door to `assistant.handle`. Voice without a transcript gets a "couldn't hear" reply without reaching the assistant; a transcript is echoed ("I heard: …"). For Telegram, every reply is also queued in the outbox in the caller's transaction under `outbox_key`. Other channels show the returned replies themselves. |
| `outbox_key(inbound, index)` | function | `seller:<channel>:<external_id>:<message_id>:<index>`: the idempotency key of the index-th reply to a message. |
| `telegram_message(message, bot)` | adapter | aiogram `Message` → `InboundMessage` (text, `/start` → `start`, contact, voice downloaded and transcribed with `app.core.stt`), or `None` for anything else. |
| `telegram_choice(callback)` | adapter | A tap on `ch:<value>` (or a pre-assistant card's `prop:ok|edit:<id>`) → `choice`; `None` for other callbacks. |
| `render_telegram(reply)` | renderer | Telegram HTML with every string escaped; choices → inline buttons `ch:<value>`; `ask_contact` → reply keyboard with the share-contact button. |
| `render_plain(reply)` | renderer | Plain text, choices numbered from 1 (the dev CLI). |
| `TELEGRAM` | constant | The channel name `"telegram"`. |

## Tables

None.

## Invariants

- The assistant never sees a channel type: only `InboundMessage` in, `Reply` out. Anything
  channel-specific (markup, escaping, voice transcription, legacy button formats) lives here.
- Telegram replies leave only through the outbox, keyed by the inbound message id, so a
  redelivered update or a retried handler cannot send twice (ADR 0004). `assistant.handle`
  returns the same replies for a repeat, so the keys match.
- Every seller- or model-written string is HTML-escaped by `render_telegram`.

## Dependencies

- `assistant`: the conversation this module feeds.
- `messaging`: Telegram replies are queued in the outbox.

## Do not

- Do not answer a seller message from a channel handler directly; go through `receive`.
- Do not route job buttons (`acc:`, `dec:`, `job:`) here; they are not conversation and call
  `jobs` directly from `app/telegram_bot.py`.
- Do not use random outbox keys; derive them from the inbound message.
