# 0001. Modules talk through contracts and own their tables

- **Status:** accepted
- **Date:** 2026-10-24

## Context

Most code here will be written by agents working with a limited view of the repository. An
agent changing a module cannot see every caller, so anything a caller can touch is something
the agent may break without knowing. In a shared-everything codebase that is everything: any
file can import any model and query any table.

## Decision

- Each module exposes a contract: the names in its `__init__.py` `__all__`. Everything else is
  private (`_`-prefixed files) and may be changed freely.
- Modules depend on each other only along the graph in AGENTS.md. No cycles.
- Each table has one owning module and is named after it. Other modules keep the id with a
  database foreign key, but no ORM `relationship()` and no queries against that table.
- All of this is enforced by `backend/tests/architecture/`, not by review.

## Consequences

**Good.** The blast radius of a change is the module plus the callers of its contract, and the
contract is short enough to read. Splitting a module into a service later is possible because
nothing reaches its tables. Agents get a precise failure message instead of a review comment.

**Bad.** Cross-module reads cost a function call instead of a join; listing screens that need
data from three modules need a composed query owned by one module, or a read model. Some
boilerplate: exporting a name is a deliberate step.

## Alternatives

- **No boundaries, rely on review.** Cheapest today; reviews do not scale to agent output.
- **import-linter with generated contracts.** Also good; rejected to keep one source (the
  graph in AGENTS.md) read directly by a test, with no generated config to drift.
- **Separate services now.** Boundaries for free, at the price of deploys, network calls and
  distributed transactions we do not need yet. Contracts keep that door open.
