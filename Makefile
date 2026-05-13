.PHONY: install lint format typecheck test check

install:
	uv sync

lint:
	uv run ruff check .

format:
	uv run ruff format .

typecheck:
	uv run mypy .

test:
	uv run pytest || { RC=$$?; [ $$RC -eq 5 ] || exit $$RC; }

check:
	uv run pre-commit run --all-files
	uv run pytest || { RC=$$?; [ $$RC -eq 5 ] || exit $$RC; }
