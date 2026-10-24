# 0002. Money is integer minor units

- **Status:** accepted
- **Date:** 2026-10-24

## Context

Prices come from free-form dialog ("250 rubles", "12.50") and leave through APIs, MCP tools
and payment providers. Floats cannot represent most decimal amounts exactly. Payment
providers (Stripe, YooKassa and others) take integers in minor units.

## Decision

Every money field is an integer in the currency's minor units, named with a `_minor` suffix
(`price_minor`), with an ISO 4217 `currency` column next to it. Parsing and formatting happen
only at the edges (dialog extraction, API/MCP output).

## Consequences

**Good.** Exact arithmetic; no conversion at the payment boundary; the suffix makes the unit
impossible to misread, for people and for models reading a schema.

**Bad.** Conversion at every input and output. Currencies with three decimals (KWD) or none
(JPY) need the exponent from the currency code, never a hard-coded 100.

## Alternatives

- **`Decimal` / `NUMERIC`.** Exact in Python and Postgres, but turns into a float in JSON on
  many clients, and an LLM tool schema has no decimal type.
- **float.** The one choice that cannot be fixed later by changing code alone: the stored
  values are already wrong.
