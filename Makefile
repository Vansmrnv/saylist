# Single entry point for every check. CI calls these targets, never copies of the commands.
.DEFAULT_GOAL := help
UV := cd backend && uv run

.PHONY: help setup check lint format types test test-db db-up db-down migrate migration \
        migration-merge migrations-check new-module worktree ci run serve seed seed-reset try-llm try-mcp chat

help: ## List targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-18s %s\n", $$1, $$2}'

setup: ## Install dependencies (and git hooks, from the main checkout only)
	cd backend && uv sync
	@# Hooks live in the shared .git and point at one venv. Installing from a worktree would
	@# point every checkout at that worktree's venv and break all hooks once it is removed.
	@if [ "$$(git rev-parse --path-format=absolute --git-dir)" = \
	      "$$(git rev-parse --path-format=absolute --git-common-dir)" ]; then \
		$(UV) pre-commit install; \
	else \
		echo "Worktree: git hooks are shared and already run from the main checkout."; \
	fi

check: lint types test ## Lint, types, tests without a database. Run before every commit.

lint: ## Ruff lint and format check
	$(UV) ruff check .
	$(UV) ruff format --check .

format: ## Apply ruff fixes and formatting
	$(UV) ruff check --fix .
	$(UV) ruff format .

types: ## mypy strict
	$(UV) mypy

test: ## Tests that need no database (includes architecture tests)
	$(UV) pytest -m "not db" -q

test-db: ## Tests marked db (needs db-up + migrate)
	$(UV) pytest -m db -q

db-up: ## Start Postgres on localhost:5433
	docker compose up -d --wait postgres

db-down: ## Stop Postgres (keeps data)
	docker compose down

migrate: ## Apply migrations
	$(UV) alembic upgrade head

migration: ## Autogenerate a migration: make migration MSG="add catalog item"
	@test -n "$(MSG)" || (echo 'usage: make migration MSG="..."' && exit 1)
	$(UV) alembic revision --autogenerate -m "$(MSG)"

migration-merge: ## Merge two migration heads after parallel branches
	$(UV) alembic merge heads -m "merge heads"

migrations-check: ## Migrations apply and match the models
	$(UV) alembic upgrade head
	$(UV) alembic check

new-module: ## Scaffold a module: make new-module NAME=catalog
	@test -n "$(NAME)" || (echo 'usage: make new-module NAME=...' && exit 1)
	$(UV) python -m scripts.new_module $(NAME)

worktree: ## Separate checkout for a parallel agent: make worktree NAME=task-slug
	@test -n "$(NAME)" || (echo 'usage: make worktree NAME=...' && exit 1)
	git fetch origin
	git worktree add ../saylist-$(NAME) -b $(NAME) origin/main
	@echo "cd ../saylist-$(NAME) && make setup"

ci: check migrations-check test-db ## Everything CI runs (needs db-up)

run: ## Dev server on :8000
	$(UV) uvicorn app.main:app --reload

serve: ## Demo server on :8000: web, MCP, Telegram bot and workers, no reload
	$(UV) uvicorn app.main:app --host 0.0.0.0 --port 8000

seed: ## Add the 4 demo businesses
	$(UV) python -m scripts.seed

seed-reset: ## Wipe every table, then add the 4 demo businesses
	$(UV) python -m scripts.seed --reset

try-llm: ## Live check of the prompts on the fixtures (costs a few API calls)
	$(UV) python -m scripts.try_llm

chat: ## Talk to the seller assistant in the terminal, no Telegram: make chat [AS=name]
	$(UV) python -m scripts.chat $(AS)

try-mcp: ## Call the MCP tools like an assistant (server running): make try-mcp URL=http://...
	$(UV) python -m scripts.try_mcp $(URL)
