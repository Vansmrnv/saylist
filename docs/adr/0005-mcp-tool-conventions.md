# 0005. MCP tool conventions

- **Status:** accepted
- **Date:** 2026-10-24

## Context

The MCP server is the product's main surface: AI assistants find businesses, read catalogs and
place orders through it. The caller is a model that reads tool names, descriptions and results
literally, cannot ask a clarifying question mid-call, and pays per round trip.

## Decision

- **Names:** `<entity>_<verb>`, singular entity (`catalog_item_list`, `order_create`). Reads end
  in `_list` or `_get`.
- **The description the model reads is the handler's docstring.** One source, kept with the
  code.
- **Writes take a list** of items and return one result per item:
  `{results: [{outcome, why, ...}]}`. Reads return `{rows, returned, truncated, next_offset}`.
- **Outcomes are a fixed set:** `DONE`, `NO_CHANGE`, `NOT_FOUND`, `REFUSED`, `INVALID`,
  `NEEDS_A_DECISION`. The last carries `options`; the caller answers by calling again with its
  choice. A choice nobody offered is refused. Never guess on the caller's behalf.
- **Anything that commits a customer is two steps:** create a draft (order, booking), then
  confirm it. The draft response states exactly what will happen, including the total.
- **`whoami`** lists every tool and whether this caller may use it, computed by the same check
  the real call makes.
- Once the server exists, one test reads every tool and fails on a convention breach.

## Consequences

**Good.** A model learns the surface once and applies it everywhere; failures are explicit
and actionable instead of silent; batch calls keep round trips low.

**Bad.** Envelopes are verbose for single-item calls. The convention test must be written
before the second tool, or exceptions pile up.

## Alternatives

- **Free-form per tool.** Faster to write the first few; each new tool is then a new dialect.
- **REST/OpenAPI only, no MCP.** We still serve REST; MCP is where assistants discover tools.
