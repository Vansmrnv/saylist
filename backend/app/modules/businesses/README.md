# businesses

## Purpose

Keeps each tradesperson's confirmed profile: trade, hours, prices, contact.

## Contract

| Name | Kind | Promise |
|------|------|---------|
| `propose(session, chat_id, text)` | service | Runs the owner's message through the LLM and stores a **proposal**: a new profile, or an edit of the latest open proposal / live profile. Older open proposals are superseded. Returns `ProposalView`. |
| `confirm(session, chat_id, proposal_id)` | service | The owner tapped Correct. Applies the proposal if it is the latest one, name and area are known, and a phone is on file. Returns a `ConfirmOutcome`. |
| `set_phone(session, chat_id, phone)` | service | Saves the phone; applies a proposal that was waiting for it (returns its outcome, else `None`). |
| `get`, `get_by_chat`, `list_active_for_trade`, `list_all`, `pending_profile` | reads | `BusinessView` / `Profile`. `list_active_for_trade` is what jobs match against. |
| `create_active(session, chat_id, phone, profile)` | service | Seeding and tests only: a live business without a proposal. |
| `Profile`, `Availability`, `TimeSlot`, `PriceRule`, `Trade`, `trade_label`, `BusinessStatus`, `ConfirmOutcome`, `BusinessView`, `ProposalView` | schemas | Shapes of the above. |

## Tables

| Table | Holds |
|-------|-------|
| `business` | One per Telegram chat: phone, status (`draft`/`active`) and the confirmed profile. |
| `business_proposal` | Every profile the model proposed, the owner's message it came from, and whether it was confirmed. |

## Invariants

- Profile columns on `business` change only by confirming a proposal (ADR 0003), or by
  `create_active` for seed data. An unconfirmed edit never changes what customers are matched against.
- At most one open proposal (`pending` or `awaiting_phone`) per business: a new one supersedes the rest,
  and only the latest can be confirmed (an old card's Correct button returns `STALE`).
- A business is `active` only with a name, an area, a trade and a phone, because the customer and the
  job flow rely on them.
- Prices are integer minor units with a currency (ADR 0002); the LLM's decimal amounts are converted
  in `_ai.py` and nowhere else.

## Dependencies

- None. (`app.core.llm` for the model calls.)

## Do not

- Do not write `business` profile fields from LLM output directly; go through a proposal.
- Do not filter on availability here; matching a time is the jobs module's job.
