.PHONY: install lint format typecheck test check export-traces services web up up-live _stop-web down down-clean help
.DEFAULT_GOAL := help

install: ## install dependencies
	uv sync

lint: ## run ruff check
	uv run ruff check .

format: ## run ruff format
	uv run ruff format .

typecheck: ## run mypy (strict)
	uv run mypy .

test: ## run pytest
	uv run pytest || { RC=$$?; [ $$RC -eq 5 ] || exit $$RC; }

check: ## run pre-commit + pytest (CI)
	uv run pre-commit run --all-files
	uv run pytest || { RC=$$?; [ $$RC -eq 5 ] || exit $$RC; }

stash: ## print normalized stash from fixture (no credentials needed)
	uv run skeinminder stash --fixture

recommend: ## run recommendation pipeline with fixture stash (pass GOAL="..." to set goal)
	uv run skeinminder recommend "$(or $(GOAL),I want to make a fall cardigan)" --fixture

recommend-live: ## run recommendation pipeline against live Ravelry stash (requires .env credentials)
	uv run skeinminder recommend "$(or $(GOAL),I want to make a fall cardigan)"

eval: ## run eval suite (requires ANTHROPIC_API_KEY and Langfuse running)
	uv run skeinminder eval

export-traces: ## export recent Langfuse traces to traces_export.json (requires Langfuse running)
	uv run python -m skeinminder.scripts.export_traces

services: ## start Langfuse + Postgres and run one-time dataset bootstrap (model pricing + eval dataset)
	docker compose up -d
	@echo "Waiting for Langfuse…"
	@until curl -sf http://localhost:3000/api/public/health > /dev/null 2>&1; do printf '.'; sleep 2; done
	@echo " ready."
	uv run python -m skeinminder.scripts.setup_langfuse_dataset

web: ## start web UI in foreground at http://localhost:8000 (pass PORT=N to change port)
	uv run skeinminder web --fixture $(if $(PORT),--port $(PORT),)

up: services ## start everything in background — terminal freed when ready; use 'make down' to stop
	uv run skeinminder web --fixture $(if $(PORT),--port $(PORT),) > web.log 2>&1 & echo $$! > .web.pid
	@echo "Web UI running at http://localhost:$(or $(PORT),8000)  (logs: web.log)"

up-live: services ## start everything against live Ravelry stash (requires .env credentials)
	uv run skeinminder web $(if $(PORT),--port $(PORT),) > web.log 2>&1 & echo $$! > .web.pid
	@echo "Web UI running at http://localhost:$(or $(PORT),8000)  (logs: web.log)"

_stop-web:
	@if [ -f .web.pid ]; then kill $$(cat .web.pid) 2>/dev/null || true; rm -f .web.pid; fi

down: _stop-web ## stop web UI + Langfuse containers (history preserved)
	docker compose down

down-clean: _stop-web ## stop web UI + Langfuse and wipe all data (next 'make up' re-initializes)
	docker compose down -v

help: ## show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "%-15s %s\n", $$1, $$2}'
