.PHONY: install lint format typecheck test check help
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

help: ## show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "%-15s %s\n", $$1, $$2}'
