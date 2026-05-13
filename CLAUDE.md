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
```

## Stack

- Python 3.13, managed with `uv`
- LangGraph for stateful multi-agent orchestration
- Pydantic for models
- httpx or requests for Ravelry API client
- pytest, ruff (E/F/I rules, line-length 88), mypy strict

## Architecture intent

The planned layout (not yet built) is:

```
src/skeinminder/
  ravelry/        # RavelryClient, Pydantic models, normalizer, fixture recordings
  graph/          # LangGraph state, nodes, workflow
  agents/         # supervisor, stash, pattern_scout, feasibility, planner, project_creator, verifier
  tools/          # deterministic tool wrappers: ravelry_project, calendar, notion
  config.py
  cli.py
```

Key design rules (from RESEARCH.md):

- LLM agents handle ambiguous judgment; deterministic tool wrappers execute all side effects.
- No write to Ravelry or external services without an explicit human approval checkpoint (`requires_approval` flag in graph state).
- Every write tool needs a dry-run mode.
- Fixture recordings (sanitized) enable tests and demo mode without live API access.
- Secrets via environment variables only — never logged, never committed.

## CI

GitHub Actions (`.github/workflows/ci.yml`) runs on PRs and pushes to `main`: pre-commit (ruff + mypy) in one job, pytest in another. Both use Python 3.13 and `uv`.
