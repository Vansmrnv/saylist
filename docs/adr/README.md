# Architecture decisions

One file per decision: `NNNN-short-slug.md`, numbered in order. An ADR answers one question:
why it is done this way and not the obvious way.

**When to write one:** a change alters the module graph, the shape of the data model, or how
the system talks to the outside world; or the obvious approach was considered and rejected.
Not for things a linter or a test already pins down.

**Rules**

- Never rewrite an accepted ADR. Write a new one that supersedes it, set the old one's status
  to `superseded by NNNN`, and strike it through in the index.
- Aim for ~40 lines. If it needs more, it is probably two decisions.
- Cite it in code where the choice would otherwise look like an accident: `# ADR 0002`.
- Add the row to the index below in the same commit.

## Index

| # | Decision | Status |
|---|----------|--------|
| [0001](0001-modules-talk-through-contracts-and-own-their-tables.md) | Modules talk through contracts and own their tables | accepted |
| [0002](0002-money-is-integer-minor-units.md) | Money is integer minor units | accepted |
| [0003](0003-the-model-proposes-the-owner-confirms.md) | The model proposes, the owner confirms | accepted |
| [0004](0004-outbound-messages-go-through-an-outbox.md) | Outbound messages go through an outbox | accepted |
| [0005](0005-mcp-tool-conventions.md) | MCP tool conventions | accepted |

## Template

```markdown
# NNNN. Decision as a statement

- **Status:** proposed | accepted | superseded by NNNN
- **Date:** YYYY-MM-DD

## Context
What forces the decision. Facts, not opinions.

## Decision
What we do, stated so it can be checked.

## Consequences
**Good.** ... **Bad.** ... (there is always a bad)

## Alternatives
Each rejected option and why, especially the obvious one.
```
