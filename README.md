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

## Deploy

Railway (project `saylist`, services `saylist` and `Postgres`) deploys every push to `main`
with `backend/Dockerfile`. Its settings live on the service, not in the repo (this service does
not read `railway.toml`): Dockerfile path `backend/Dockerfile`, pre-deploy
`alembic upgrade head`, healthcheck `/health`, one replica (the Telegram bot long-polls, so a
second copy with the same token steals its updates). Secrets are service variables;
`DATABASE_URL` references `${{Postgres.DATABASE_URL}}`.

- App: https://saylist-production.up.railway.app (MCP at `/mcp`)
- Bot: https://t.me/saylistbusiness_bot. Run locally with a different bot token.

## Read next

- [AGENTS.md](AGENTS.md): how the code is organised and the rules for changing it.
- [docs/adr/](docs/adr/README.md): why things are the way they are.
