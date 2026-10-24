# 0009. Customer assistants use fixed verbs over business capabilities

- **Status:** proposed
- **Date:** 2026-10-24

## Context

Businesses differ wildly: a cake needs an inscription and a date, an electrician an exact
address and a door code, a boat a crew size. Giving each business its own MCP tools looks like
the way to not constrain them. But one server serves every business, the customer's assistant
connects before it knows which business it wants, models choose worse among many tools, MCP
clients reload tool lists unreliably, and a tool description is read by the customer's model as
a high-trust instruction — a seller-written one is a prompt-injection channel.

## Decision

A small fixed set of tools (ADR 0005 conventions), with per-business variety in the data they
return:

```text
whoami              what this caller may use
offering_search     across all businesses: what, where, when
business_get        profile and a summary of offerings
capability_list     what a business can do: type, input form (JSON Schema), prices, terms
capability_invoke   do it: returns a draft deal with the total (or an answer, for `question`)
request_confirm     confirm a draft: this is what commits the customer
request_get         status by token; `payment_url` once payment is due (ADR 0010)
request_cancel      cancel by token
```

- `capability_invoke` validates the answers against the capability's form; a gap comes back
  `INVALID` with exactly what to ask the customer.
- Anything that commits the customer is two steps: invoke → draft, then `request_confirm`.
- Deals are addressed by token (ADR 0008), never by a sequential id.
- Seller-written text (descriptions, form hints) reaches the customer's model only inside tool
  results, as data, length-capped — never in tool names or descriptions.
- Every call writes an interaction event (ADR 0008).

## Consequences

**Good.** Search and comparison work across all businesses; the tool list stays short and
stable; one backend validates everything; variety is unlimited within the capability types.

**Bad.** `capability_invoke` takes a generic `input` object, so the tool schema helps the model
less; `capability_list` must return a clear form and an example, and evals must check that
assistants fill it well.

## Alternatives

- **Seller-defined tools per business.** Rejected for the reasons in Context. If evals later
  show assistants do better with specific tools, a per-business MCP endpoint can expose tools
  *generated* from the same capability forms, on top of this model.
- **One tool per capability type** (`order_create`, `booking_create`…). Plausible; it splits
  the same validation four ways and grows with every new type.
