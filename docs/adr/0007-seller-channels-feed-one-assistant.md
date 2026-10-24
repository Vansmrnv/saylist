# 0007. Seller channels feed one assistant

- **Status:** accepted
- **Date:** 2026-10-24

## Context

A seller does not "use a Telegram bot": they talk to saylist, and Telegram is one door among
WhatsApp, a phone call and a web chat. The Telegram handlers decided everything themselves:
each message type mapped to one `businesses` call and a hand-built reply with Telegram markup.
A second channel would have copied that logic, and the one-shot extraction could not answer a
question about the profile or take a follow-up edit in context.

## Decision

- **Channel adapters only translate** (module `channels`): an update becomes an
  `InboundMessage` (`start`, `text`, `voice` already transcribed, `contact`, `choice`), and each
  `Reply` (`text`, `choices`, `card`, `ask_contact`, plain text) is rendered and escaped the
  channel's way. `channels.receive(session, inbound)` is the one door.
- **One seller assistant** (module `assistant`): `handle(session, inbound) -> list[Reply]`,
  with history per `(channel, external_id)` in `assistant_*` tables and an LLM tool-use loop
  whose tools are thin wrappers over the `businesses` contract.
- **Taps, contacts and the welcome are decided by code, not the model.** Confirming a proposal
  or saving a phone happens only when the seller picks a choice the assistant offered (ADR 0003).
- **`handle` is idempotent per inbound message**, and Telegram replies are queued in the outbox
  under keys derived from it (ADR 0004). The outbox stays Telegram-addressed: a channel gets an
  address column when it gets a push transport.
- Graph: `channels -> assistant, messaging`; `assistant -> businesses`.

## Consequences

**Good.** A new channel is an adapter plus a renderer; a test drives a whole conversation
through a fake channel. The seller can ask and correct in context. Redelivered updates neither
re-run the model nor send twice.

**Bad.** Each seller text is a model loop (cost, latency) instead of one extraction, and runs
inside the DB transaction holding the conversation lock. Replies wait for the outbox poll.
Non-Telegram sellers need a synthetic `businesses` key until the entity redesign gives sellers
an identity of their own (`assistant/_identity.py` is that seam).

## Alternatives

- **Keep per-channel handlers.** Cheapest now; every channel repeats the flow and drifts.
- **Let the model call `confirm`.** Fewer taps; breaks ADR 0003 on the model's say-so.
- **Generalize the outbox to `(channel, address)` now.** No second push channel exists to
  shape it; WhatsApp's templates and 24-hour window will.
