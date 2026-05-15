# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

SkeinMinder is a Ravelry-powered multi-agent studio planner. It reads a user's real Ravelry yarn stash, uses specialized LangGraph agents to evaluate project feasibility, and only writes back to Ravelry or external tools (Google Calendar, Notion, etc.) after a human approval checkpoint.

See `RESEARCH.md` for the full product concept, agent architecture, phased implementation plan, and open questions about Ravelry API behavior.

## Commands

```bash
uv sync               # install dependencies
make lint             # ruff check
make format           # ruff format
make typecheck        # mypy (strict mode, Python 3.13)
make test             # pytest
make check            # pre-commit + pytest (what CI runs)

uv run pytest tests/test_foo.py        # run a single test file
uv run pytest tests/test_foo.py::name  # run a single test

skeinminder stash            # print normalized stash (requires .env credentials)
skeinminder stash --fixture  # same, using committed fixture files (no network)

uv run python -m skeinminder.ravelry.recorder        # record fresh fixtures from live API
uv run python -m skeinminder.ravelry.recorder --raw  # save pre-Pydantic JSON to tests/fixtures/raw/ (gitignored)
```

## Stack

- Python 3.13, managed with `uv`
- LangGraph for stateful multi-agent orchestration (not yet built)
- Pydantic v2 for models (`extra="ignore"` everywhere — Ravelry API fields evolve)
- httpx for Ravelry API client, with tenacity retry on 429/5xx
- pytest, ruff (E/F/I rules, line-length 88), mypy strict

## What's built (Phases 1–2b)

```
src/skeinminder/
  ravelry/
    client.py      # RavelryClient — Basic Auth, pagination, retry
    models.py      # Raw Pydantic models (prefix Raw*) — thin wrappers around API JSON
    normalizer.py  # normalize_stash() → StashItem; weight/fiber scoring utilities
    sanitizer.py   # redacts PII before fixture files are committed
    recorder.py    # one-shot script to capture live API responses as fixture JSON
    exceptions.py  # RavelryAPIError, RavelryAuthError, RavelryRateLimitError, NormalizationError
  config.py        # get_ravelry_credentials() from .env
  cli.py           # `skeinminder stash [--fixture]`
tests/
  conftest.py      # FixtureTransport (httpx transport) + fixture_client fixture
  fixtures/        # sanitized JSON snapshots used by all tests (no live API needed)
```

The `graph/`, `agents/`, and `tools/` packages are planned for later phases.

## Key design rules

- Raw models (`Raw*`) map directly to API JSON. `StashItem` in `normalizer.py` is the normalized domain model — always work with `StashItem` inside the app, not raw models.
- Tests use `FixtureTransport` (injected into `RavelryClient` via the `transport=` kwarg) — never hit the live Ravelry API in tests.
- No write to Ravelry or external services without an explicit human approval checkpoint (`requires_approval` flag in graph state, when that layer exists).
- Every future write tool needs a dry-run mode.

## CI

GitHub Actions (`.github/workflows/ci.yml`) runs on PRs and pushes to `main`: pre-commit (ruff + mypy) in one job, pytest in another. Both use Python 3.13 and `uv`.
