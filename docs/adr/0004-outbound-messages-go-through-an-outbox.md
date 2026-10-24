# 0004. Outbound messages go through an outbox

- **Status:** accepted
- **Date:** 2026-10-24

## Context

The product talks to owners and customers through Telegram, WhatsApp and webhooks to other
systems. These calls are slow, rate-limited and fail. If a service sends a message inside its
database transaction, a rollback leaves a message about something that did not happen; if it
sends after commit, a crash loses the message.

## Decision

Code never calls a messaging or webhook API inside business logic. It writes an outbox row in
the same transaction as the change it describes. A worker delivers outbox rows with retries
and idempotency keys, and records the result. One module owns the outbox table and the
delivery adapters.

## Consequences

**Good.** A message is sent if and only if its change committed. Retries, rate limits and
provider outages live in one place. Delivery history is queryable for support.

**Bad.** Delivery is asynchronous: a reply can lag by the worker's poll interval. A worker
process to run and monitor.

## Alternatives

- **Send directly and hope.** Fine for a demo; produces phantom and lost messages in
  production.
- **A message broker (Redis, RabbitMQ).** Adds infrastructure and still needs the
  transactional write; Postgres is enough until volume says otherwise.
