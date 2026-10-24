# jobs

## Purpose

Carries a customer's job from request to done, so neither side has to call the other (ADR 0006).

## Contract

| Name | Kind | Promise |
|------|------|---------|
| `draft_request(session, JobRequestIn, channel)` | service | Checks the request (trade, time, an **exact** address), finds who is free and their price. Sends nothing. `DONE` with the draft, `INVALID` with what to ask the customer, or `REFUSED` when nobody is free. |
| `confirm_request(session, job_id)` | service | Sends the draft's offers through the outbox. `NO_CHANGE` if already sent. |
| `cancel_request(session, job_id, reason)` | service | Customer cancels before the business is at the door; waiting offers are closed and an assigned business is told. |
| `get_jobs(session, ids)`, `get_by_token(session, token)` | reads | `JobView`: status, a one-line `status_text`, business, booked time, ETA, timeline. |
| `customer_coming(session, token)` | service | Tracking-page "I'm coming down" button. Pings the business once; only when they are at the door. |
| `accept_offer(session, offer_id, business_id, option)` | service | The business tapped a time. The first tap claims the job (atomic); the others are told it's taken. Returns a toast. |
| `decline_offer(session, offer_id, business_id)` | service | Returns a toast. If everyone declined, the job becomes `no_match`. |
| `advance(session, job_id, business_id, BusinessAction, minutes)` | service | One tap on the job card: on the way (with ETA), at the door, done, can't make it. |
| `expire_stale(session)` | service | Open jobs nobody took within `REQUEST_TIMEOUT_MINUTES`, and unconfirmed drafts, expire. |
| `list_recent`, `list_recent_offers` | reads | For the admin page. |
| `arrival_options(when, availability, now)` | function | The concrete times a business can be offered. |
| `JobRequestIn`, `JobView`, `WriteResult`, `Outcome`, `JobStatus`, `OfferAnswer`, `EventKind`, `EventView`, `BusinessAction`, `ArrivalOption`, `When`, `OfferAdminView` | schemas | Shapes of the above. |

## Tables

| Table | Holds |
|-------|-------|
| `job` | The request: trade, time window, exact address, access notes, customer, status, assigned business, booked time, ETA, tracking token. |
| `job_offer` | One per business the job was offered to: its price note, the arrival times on its buttons, its answer. |
| `job_event` | The timeline the customer sees, one row per step, with customer-facing text. |

## Invariants

- Status only moves along `draft → open → booked → on_the_way → arrived → done` (ASAP jobs go
  `open → on_the_way`), or to `no_match` / `expired` / `cancelled`. Every change is a conditional
  `UPDATE … WHERE status IN (…)` (`_repository.move`), so two taps can never both win.
- A job is never sent without a specific address (street + number, flat/floor) and access notes.
  The point is that the business never has to call to ask where or how to get in.
- The times on the offer buttons come from `_schedule.arrival_options`, not from the LLM. A business
  with no time in the customer's window gets no offer. The LLM only writes the price note.
- Every Telegram message goes through `messaging` with a key derived from the offer
  (`job_offer:<id>`). The offer message becomes the job card and is edited in place at each step.
- Each status change writes one `job_event` whose `note` is shown to the customer as is.
- Only the assigned business can advance a job, and only the business an offer was sent to can
  answer it (`business_id` is checked, not just the button's data).

## Dependencies

- `businesses`: the active businesses of a trade, with hours and prices; names and phones for views.
- `messaging`: offers and job-card updates are queued in the outbox (ADR 0004).

## Do not

- Do not let the LLM pick arrival times or decide availability; it is not reliable on time
  arithmetic, and the buttons are a commitment.
- Do not expose `customer_phone` before a business has taken the job.
- Do not edit `job.status` directly; use `_repository.move` so the transition stays atomic.
