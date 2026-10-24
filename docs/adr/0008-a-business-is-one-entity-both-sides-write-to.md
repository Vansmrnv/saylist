# 0008. A business is one entity both sides write to

- **Status:** proposed
- **Date:** 2026-10-24

## Context

The code on main models one vertical: a tradesperson `Profile` (trade, hours, prices) and a
`jobs` flow that broadcasts a request to several businesses, first tap wins. The product must
serve any supply: goods, services, rentals, anything a small business sells. Two sides touch
a business: the seller, through their assistant (ADR 0007), shapes what is offered; customers,
through their AI assistants (ADR 0009), look, ask, order and pay. The seller wants to ask their
assistant what customers did ("how many orders this week? what did people ask about?").

## Decision

A **business** is one entity, owned by one module, with four parts:

- **Profile:** name, description, service area, hours, contacts, currency, policies.
- **Offerings:** what is sold. Each has a kind (`product`, `service`, `rental`, `other`),
  title, description, category, free attributes (JSONB) and a small fixed set of shapes:
  *price* (`fixed`, `from`, `per_unit`, `callout_plus_rate`, `on_request`; ADR 0002),
  *availability* (`stock`, `schedule`, `on_request`), *fulfilment* (`pickup`, `delivery`,
  `on_site`, `remote`).
- **Capabilities:** what a customer can do with this business. Each is an instance of a fixed
  type — `order`, `booking`, `quote_request`, `question` — with a seller-edited input form
  (JSON Schema: what to ask the customer), the offerings it covers, and its terms (needs the
  seller's acceptance, needs payment). Variety lives in this data, not in code or tools.
- **Interaction log:** append-only, written by the customer side automatically: shown in
  search, viewed, capabilities read, invoked, confirmed, paid, cancelled, a question with a
  one-line summary, and searches that matched nothing (unmet demand). Each event carries the
  business, offering, customer channel (which assistant), an anonymous customer ref and a time.

Seller-side changes are a change set the seller confirms; confirming produces a new version
(ADR 0003, applied to the whole entity). Old versions are kept.

A customer action creates a **deal**: one business, one capability, the form's answers, a
total computed from the offering's prices. Lifecycle: `draft → submitted → accepted |
declined → (paid) → fulfilled | cancelled | expired`. **No bids**: there is no request to the
whole market; the customer's assistant searches, picks a business, and tries the next one if
declined. A bid flow can be added later as a separate tool over the same deals.

**Customers are anonymous** to sellers: stats and the log show a pseudonymous ref. Contact
details reach a seller only inside a deal, and only when fulfilment needs them. A customer
reaches their deal by an unguessable token, never by a sequential id.

Modules: `businesses` (profile, offerings, capabilities, versions), `deals`, `interactions`
(log and stats, depends on nothing), `payments` (ADR 0010). `jobs` is replaced by `deals`
with `booking` / `quote_request`; its atomic status moves, job card and tracking page carry
over, its broadcast-to-many is dropped.

The seller assistant gains read tools over this: `stats_get(period, metric, group_by)`,
`interactions_list(filters)`, and change tools that edit offerings and capability forms.

## Consequences

**Good.** One model for any business; a new kind of business is data, not a migration. The
log makes seller analytics and unmet demand nearly free. Anonymity plus tokens closes the
"read any job by its number" hole.

**Bad.** Generic shapes fit some businesses awkwardly; the `other` kind and free attributes
will collect what does not fit and need pruning. Replacing `jobs` is a real rewrite.
Matching quality now depends on the customer's assistant and on our search.

## Alternatives

- **One model per vertical** (keep `Profile` + `jobs`, add `shop`, `salon`…). Fastest per
  vertical; each new one is new code, and the long-term goal is any business.
- **Fully free-form entity** (a JSON document per business). Infinitely flexible; nothing to
  search, price or validate against, so the customer's assistant gets nothing reliable.
- **Bids now.** Keeps the current `jobs` behaviour; adds matching, competing offers and timeouts
  to every deal. Deferred, not rejected.
