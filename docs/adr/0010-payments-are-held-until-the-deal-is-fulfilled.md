# 0010. Payments are held until the deal is fulfilled

- **Status:** proposed
- **Date:** 2026-10-24

## Context

Customers' assistants must be able to hand the customer a payment link. No money moves yet,
but the intended model is: the customer pays saylist, and the seller is paid only after the
deal is done. Holding other people's money is regulated; how it is done must not be an
afterthought baked into deal code.

## Decision

- A `payments` module behind a provider interface: create a link for a deal, receive the
  provider's events. The first provider is a **stub**: the link opens our own "pay (test)" page,
  and paying it drives the same events a real provider would.
- States: `link_issued → paid (held) → released` when the deal is fulfilled, or `→ refunded`
  when it is cancelled. Deals, the interaction log and seller notifications react to these
  events exactly as they will with real money.
- The amount always comes from the deal, which is computed from offering prices (ADR 0002,
  0008). A model never sets an amount.
- Real provider later: Stripe Connect with separate charges and transfers, so funds are held
  and paid out under Stripe's licence, not on a plain company account.

## Consequences

**Good.** The whole flow, links and webhooks included, is testable now without a provider
account. Switching to Stripe touches one adapter.

**Bad.** The stub can hide provider realities (failed payments, disputes, payout delays,
seller verification), which will need work when Stripe arrives.

## Alternatives

- **No payments until Stripe.** Leaves the deal lifecycle and the MCP tool incomplete.
- **Seller's own payment link** (seller pastes a link). Simplest; no hold, no platform fee,
  and the amount is not tied to the deal.
