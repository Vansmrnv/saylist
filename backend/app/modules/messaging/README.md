# messaging

## Purpose

Delivers outbound Telegram messages reliably through an outbox (ADR 0004).

## Contract

| Name | Kind | Promise |
|------|------|---------|
| `send(session, key=, chat_id=, text=, buttons=)` | service | Queues a message in the caller's transaction. A repeated `key` is a no-op. |
| `edit(session, key=, edit_of=, text=, buttons=)` | service | Queues a rewrite of the message sent under key `edit_of`. `buttons=None` removes the buttons. Unknown `edit_of`: no-op. |
| `list_recent(session, limit)` | service | Newest outbox rows as `OutboxView`, for the admin page. |
| `Button` | schema | Inline button: `text` plus `callback_data` or `url`. `request_contact=True` makes the message's buttons a reply keyboard with Telegram's share-contact button instead (sends only; an edit cannot carry one). |
| `run_worker(sessionmaker, bot)` | worker | Runs forever, delivering due rows. Started by `app.main`. |
| `deliver_due(sessionmaker, transport)` | worker | One delivery batch; used by the worker and tests. |
| `Transport`, `TelegramTransport`, `PermanentError`, `RetryLater` | adapter | The delivery interface and its Telegram implementation; tests plug in a fake. |

## Tables

| Table | Holds |
|-------|-------|
| `messaging_outbox` | One row per message to send or edit: text, buttons, delivery status, attempts, Telegram message id. |

## Invariants

- A row exists only if the change it describes committed: callers write it in their own
  transaction and never call Telegram themselves.
- `key` is unique. Callers derive it from what the message is about (`job_offer:12`, or
  `seller:telegram:<chat>:<message>:<n>` for assistant replies, see `channels`), so a retried
  operation cannot send twice.
- An edit is delivered only after the send it targets; if that send failed, the edit fails too.
- Rows are delivered in id order, so the last edit queued is the text the user ends up seeing.
- Permanent errors (unknown chat, e.g. seeded fake chat ids; bot blocked) fail at once, are logged and
  never crash the worker. Other errors retry with backoff, up to 6 attempts.

## Dependencies

- None.

## Do not

- Do not call `bot.send_message` from business logic; queue through `send`/`edit`.
- Do not use random keys for sends: the key is the idempotency guarantee.
