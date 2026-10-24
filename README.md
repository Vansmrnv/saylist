# saylist

AI infrastructure for small businesses: an owner describes their business in a chat
(Telegram, WhatsApp, a call), and saylist turns it into a structured catalog that AI
assistants (ChatGPT, Claude, …) can search, order from and pay through, via API and MCP.

Status: foundation only. No product code yet.

## Start

Needs [uv](https://docs.astral.sh/uv/) and Docker.

```sh
make setup      # dependencies + git hooks
make check      # lint, types, tests
make db-up migrate test-db
make help       # everything else
```

## Read next

- [AGENTS.md](AGENTS.md): how the code is organised and the rules for changing it.
- [docs/adr/](docs/adr/README.md): why things are the way they are.
