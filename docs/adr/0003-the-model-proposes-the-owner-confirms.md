# 0003. The model proposes, the owner confirms

- **Status:** accepted
- **Date:** 2026-10-24

## Context

The catalog is built by an LLM reading what the owner says. Extraction will sometimes be
wrong: a misheard price, a merged item, a delivery zone invented from a vague phrase. The
catalog is then shown to AI assistants as fact, and orders are placed against it. A wrong
price published is worse than a missing one.

## Decision

LLM output never writes the catalog directly. Extraction produces a *proposal*: a structured
set of changes linked to the message it came from. The owner sees it in the same channel in
plain words ("Add: cappuccino 0.3 l, 250 ₽ — yes / fix"), and only a confirmed proposal is
applied, by ordinary service code that validates it like any other input.

## Consequences

**Good.** The owner stays responsible for what is published, and can trust it. Every catalog
fact traces to a message and a confirmation. Extraction can be improved, swapped or evaluated
against stored proposals without touching catalog code.

**Bad.** One more step for the owner; the confirmation UX must be fast or they stop using it.
Batching and "confirm all" are needed early.

## Alternatives

- **Write directly, let the owner undo.** Faster onboarding, but errors are live until noticed,
  and nobody re-reads a catalog they did not write.
- **Confidence threshold: auto-apply when sure.** Model confidence is not calibrated enough
  to bet published prices on it. Revisit with eval data.
