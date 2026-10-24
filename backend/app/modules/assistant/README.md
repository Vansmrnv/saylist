# assistant

<!-- Goal: an agent can work on this module after reading only this file. Keep it current:
     update it in the same commit as the code it describes. -->

## Purpose

Holds one conversation with each seller, whatever channel they write from (ADR 0007).

## Contract

| Name | Kind | Promise |
|------|------|---------|
| `handle(session, inbound) -> list[Reply]` | service | Answers one seller message. Idempotent per `(channel, external_id, message_id)`: a repeat returns the replies stored the first time and runs nothing (no LLM call, no proposal). Flushes, never commits. Never raises for an LLM failure: the turn's effects are rolled back to a savepoint and the reply is an apology. |
| `InboundMessage`, `InboundKind` | schemas | What a channel hands in: `start`, `text`, `voice` (already transcribed: `text` is the transcript), `contact` (`phone`), `choice` (`choice_value` from an earlier reply). |
| `Reply`, `ReplyKind`, `Choice`, `CardField` | schemas | What comes out: `text`, `choices` (text + options), `card` (title + fields + footer + options), `ask_contact` (text; the channel adds its share-phone control). Plain text only, never markup. |

## Tables

| Table | Holds |
|-------|-------|
| `assistant_conversation` | One per `(channel, external_id)`. Locked (`FOR UPDATE`) while a message is handled, so one seller's messages run one at a time. |
| `assistant_turn` | One per inbound message (unique per conversation): the inbound, the Anthropic-format transcript of the turn (thinking blocks as returned), the replies, and whether it failed. |

## How a turn runs

- `start`, `contact` and `choice` are decided by code (`_service._fixed_turn`): welcome, save the
  phone (`businesses.set_phone`), confirm (`businesses.confirm`), "tell me what to change".
- `text` and `voice` go to the model (`_agent.run`): a tool-use loop of at most 6 steps over the
  last 20 turns. Tools (`_tools.py`) are thin wrappers over the `businesses` contract:
  `get_profile`, `propose_profile_change` (→ `businesses.propose`, shows the card),
  `show_profile`, `show_pending_proposal`, `offer_phone` (Yes/No choice), `request_phone`.
- Every turn, fixed or not, is stored with a transcript, so the model sees taps and contacts too.

## Invariants

- The model cannot confirm a profile or save a phone (ADR 0003). There is no such tool. Confirming
  happens only in `_fixed_turn`, on a `choice` the seller picked (`confirm:<proposal_id>`,
  `phone:<number>`); `businesses.confirm` still refuses anything but the latest proposal.
- Replies are channel-neutral: no HTML, no Telegram types, no `aiogram` import here. Channels
  render and escape.
- The system prompt and tool list are constant; per-turn facts (time, status) go into that turn's
  user message. Earlier turns are replayed without thinking blocks; the current turn exactly as
  returned. Editing an earlier turn's stored transcript would break this.
- Identity is `(channel, external_id)`. `_identity.business_chat_id` maps it to the `businesses`
  key: the Telegram chat id, or a synthetic negative id below -10^15 for other channels. This is
  the seam the business-entity redesign replaces.

## Dependencies

- `businesses`: the profile operations the tools and fixed turns call.
- `app.core.llm.tool_step` for the model; `app.core.config` via it.

## Do not

- Do not add a tool that confirms or writes the profile directly; propose and let the seller pick.
- Do not build channel markup here (buttons, HTML, "tap the button"); describe choices instead.
- Do not call the model for `choice`/`contact`: those are the seller's deliberate actions.
