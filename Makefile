.PHONY: install lint format typecheck test check export-traces help
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

help: ## show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "%-15s %s\n", $$1, $$2}'
