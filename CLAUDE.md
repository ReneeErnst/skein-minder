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

skeinminder stash                      # print normalized stash (requires .env credentials)
skeinminder stash --fixture            # same, using committed fixture files (no network)
skeinminder recommend "<goal>"         # run the full graph and print recommendations (requires ANTHROPIC_API_KEY)
skeinminder recommend "<goal>" --fixture  # same, using fixture stash instead of live Ravelry

uv run python -m skeinminder.ravelry.recorder        # record fresh fixtures from live API
uv run python -m skeinminder.ravelry.recorder --raw  # save pre-Pydantic JSON to tests/fixtures/raw/ (gitignored)
```

## Stack

- Python 3.13, managed with `uv`
- LangGraph for stateful multi-agent orchestration
- langchain-anthropic for LLM calls (structured output via `with_structured_output`)
- Pydantic v2 for models (`extra="ignore"` everywhere — Ravelry API fields evolve)
- httpx for Ravelry API client, with tenacity retry on 429/5xx
- pytest, ruff (E/F/I rules, line-length 88), mypy strict

## Environment variables

Copy `.env.example` to `.env`. Required for live API usage:

```
RAVELRY_USERNAME=       # Ravelry Basic Auth credentials
RAVELRY_PASSWORD=
ANTHROPIC_API_KEY=      # required for skeinminder recommend (live LLM calls)
SKEINMINDER_MODEL=      # optional; defaults to claude-haiku-4-5-20251001
```

LangSmith tracing vars (`LANGSMITH_API_KEY`, `LANGCHAIN_TRACING_V2`, `LANGCHAIN_PROJECT`) are optional and documented in `.env.example`.

## What's built (Phases 1–3)

```
src/skeinminder/
  ravelry/
    client.py      # RavelryClient — Basic Auth, pagination, retry
    models.py      # Raw Pydantic models (prefix Raw*) — thin wrappers around API JSON
    normalizer.py  # normalize_stash() → StashItem; weight/fiber scoring utilities
    sanitizer.py   # redacts PII before fixture files are committed
    recorder.py    # one-shot script to capture live API responses as fixture JSON
    exceptions.py  # RavelryAPIError, RavelryAuthError, RavelryRateLimitError, NormalizationError
  graph/
    state.py       # GraphState (TypedDict), StashFilter, Recommendation
    graph.py       # build_graph() — compiles the LangGraph StateGraph
    nodes.py       # supervisor, project_first_filter, stash_first_filter, recommend, format_output
  config.py        # get_ravelry_credentials() from .env
  cli.py           # `skeinminder stash` and `skeinminder recommend`
tests/
  conftest.py      # FixtureTransport (httpx transport) + fixture_client fixture
  fixtures/        # sanitized JSON snapshots used by all tests (no live API needed)
```

## Graph architecture

The LangGraph pipeline: `supervisor → [project_first_filter | stash_first_filter] → recommend → format_output`

- **supervisor**: classifies user input into `project_first` (goal-driven) or `stash_first` (yarn-driven) mode; extracts weight/yardage into `StashFilter` for stash-first inputs.
- **project_first_filter / stash_first_filter**: filter `normalized_stash` down to ≤20 candidates using `StashFilter` criteria or goal keywords; both sort descending by yards.
- **recommend**: calls the LLM (model from `SKEINMINDER_MODEL` env var) with a system-prompt-cached prompt and returns exactly 3 `Recommendation` objects via structured output.
- **format_output**: renders recommendations as a plain-text CLI report, resolving stash IDs back to yarn names.

In tests, `recommend` is patched at `skeinminder.graph.nodes.recommend` — the node function itself, not the LLM client — so the full graph routing logic is exercised without live API calls.

## Testing conventions

- Use `@pytest.mark.parametrize` whenever multiple tests call the same function with different inputs and assert the same shape of result. Collapse them into one parametrized test rather than writing individual named functions.
- Keep tests as named functions when the setup or assertion structure differs meaningfully between cases — parametrize is for input variation, not behavioral variation.
- Fixture files in `tests/fixtures/` should be small and representative (one or a few items per category), not exhaustive dumps. Full exports belong in gitignored files.

## Key design rules

- Raw models (`Raw*`) map directly to API JSON. `StashItem` in `normalizer.py` is the normalized domain model — always work with `StashItem` inside the app, not raw models.
- Tests use `FixtureTransport` (injected into `RavelryClient` via the `transport=` kwarg) — never hit the live Ravelry API in tests.
- No write to Ravelry or external services without an explicit human approval checkpoint (`requires_approval` flag in `GraphState`; currently always `False` — the approval gate is a Phase 5 stub).
- Every future write tool needs a dry-run mode.

## Git workflow

- Never commit directly to `main`. All work goes on a feature branch (e.g., `phase3`) and merges via PR.
- Do not commit `docs/superpowers/` — it is gitignored intentionally. Specs and plans in that directory are local working documents, not part of the project history.

## CI

GitHub Actions (`.github/workflows/ci.yml`) runs on PRs and pushes to `main`: pre-commit (ruff + mypy) in one job, pytest in another. Both use Python 3.13 and `uv`.
