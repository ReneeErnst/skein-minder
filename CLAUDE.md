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
skeinminder web                        # start browser UI at http://localhost:8000 (requires ANTHROPIC_API_KEY)
skeinminder web --fixture              # same, using fixture stash + pattern data (no network)

uv run python -m skeinminder.ravelry.recorder        # record fresh fixtures from live API
uv run python -m skeinminder.ravelry.recorder --raw  # save pre-Pydantic JSON to tests/fixtures/raw/ (gitignored)

uv run python -m skeinminder.scripts.setup_langfuse_dataset  # register model pricing + create eval dataset (idempotent; re-run after docker compose down -v)

skeinminder eval                       # run two-layer eval suite (all examples)
skeinminder eval --example-id <id>     # run a single example by id
uv run pytest -m eval                  # run @pytest.mark.eval integration tests (real LLM, not CI)

docker compose up -d   # start local Langfuse + Postgres (http://localhost:3000)
docker compose down    # stop containers
docker compose down -v # stop and delete volumes (reset all Langfuse data)
```

## Stack

- Python 3.13, managed with `uv`
- LangGraph for stateful multi-agent orchestration
- langchain-anthropic for LLM calls (structured output via `with_structured_output`)
- Pydantic v2 for models (`extra="ignore"` everywhere — Ravelry API fields evolve)
- httpx for Ravelry API client, with tenacity retry on 429/5xx
- FastAPI + uvicorn[standard] for the web UI; SSE via `asyncio.Queue`
- langfuse for graph tracing (`@observe` decorators, self-hosted via Docker Compose)
- pytest, ruff (E/F/I rules, line-length 88), mypy strict

## Environment variables

Copy `.env.example` to `.env`. Required for live API usage:

```
RAVELRY_USERNAME=       # Ravelry Basic Auth credentials
RAVELRY_PASSWORD=
ANTHROPIC_API_KEY=      # required for skeinminder recommend (live LLM calls)
SKEINMINDER_MODEL=      # optional; defaults to claude-haiku-4-5-20251001
```

Langfuse tracing vars are optional — set them to enable graph traces in the Langfuse UI:

```
LANGFUSE_PUBLIC_KEY=    # from docker-compose.yml LANGFUSE_INIT_PROJECT_PUBLIC_KEY
LANGFUSE_SECRET_KEY=    # from docker-compose.yml LANGFUSE_INIT_PROJECT_SECRET_KEY
LANGFUSE_HOST=          # defaults to http://localhost:3000
```

Run `docker compose up -d` first. The pre-seeded keys (`lf-pk-skeinminder-local` / `lf-sk-skeinminder-local`) match the values already in `.env.example`.

## What's built (Phases 1–8)

```
src/skeinminder/
  ravelry/
    client.py           # RavelryClient — Basic Auth, pagination, retry
                        #   Phase 6a: + get_library_pattern_ids, search_patterns, get_pattern_details
    models.py           # Raw Pydantic models (prefix Raw*) — thin wrappers around API JSON
                        #   Phase 8: RawStashItem gains created_at: str | None = None
    normalizer.py       # normalize_stash() → StashItem; weight/fiber scoring utilities
                        #   Phase 8: StashItem gains added_date: datetime | None; _parse_ravelry_date helper
    patterns.py         # Phase 6a: RawPattern, RawPatternFull, RawLibrarySearchResponse,
                        #   PatternSummary, normalize_pattern()
                        #   Phase 7: + RawFirstPhoto; PatternSummary gains photo_url
    sanitizer.py        # redacts PII before fixture files are committed
    recorder.py         # one-shot script to capture live API responses as fixture JSON
    exceptions.py       # RavelryAPIError, RavelryAuthError, RavelryRateLimitError, NormalizationError
    fixture_transport.py  # Phase 6a: FixtureTransport moved here from tests/conftest.py;
                          #   routes pattern API URLs to fixture files
  graph/
    state.py       # GraphState (TypedDict), StashFilter, Recommendation
                   #   Phase 6b: Recommendation gains pattern_id/name/url (nullable);
                   #   GraphState gains ravelry_username, use_fixture, pattern_candidates
                   #   Phase 8: StashFilter gains oldest_first: bool = False
    graph.py       # build_graph() — compiles the LangGraph StateGraph
                   #   Phase 6b: pattern_search wired in on both routing paths
    nodes.py       # supervisor, project_first_filter, stash_first_filter, assess_filter_quality,
                   #   low_confidence_output, pattern_search, recommend, format_output
                   #   Phase 6b: + pattern_search node; recommend + format_output updated
                   #   Phase 8: + _TEMPORAL_TRIGGERS, _date_sort_key; supervisor sets oldest_first;
                   #            filter nodes sort by added_date when oldest_first=True
  web/             # Phase 7: browser UI
    __init__.py
    events.py      # stream_graph_events() async generator; _build_result_payload(); _sse()
                   #   bridges LangGraph astream_events → SSE; saves last_run.json for /replay
    server.py      # create_app(stash, ravelry_username, use_fixture) FastAPI factory
                   #   endpoints: POST /recommend, GET /stream/{id}, GET /replay,
                   #   POST /approve/{id}, POST /cancel/{id}, GET / (static)
    static/
      index.html   # three-phase page (phase-input / phase-running / phase-results)
      app.js       # SSE consumer, phase controller, card renderer
      graph.js     # vis-network topology + setNodeState(name, state)
      style.css    # Ravelry-inspired palette (cream/burgundy/green)
  scripts/
    setup_langfuse_dataset.py  # idempotent bootstrap: registers Anthropic model pricing in Langfuse, then creates skeinminder-eval-v1 dataset and upserts golden examples
  config.py        # get_ravelry_credentials() from .env
  cli.py           # `skeinminder stash`, `skeinminder recommend`, `skeinminder eval`
                   #   Phase 6b: _load_stash returns (stash, username); _run_recommend takes ravelry_username + use_fixture
                   #   Phase 7: + `skeinminder web [--port] [--fixture]`
  eval.py          # load_examples(), run_example(), assert_example(), judge_example(), format_table()
                   #   Phase 6b: EvalExpected gains pattern_ids_from_candidates; run_example uses fixture transport
  observability.py # get_langfuse_client() — returns None when credentials are absent (no-op in tests)
tests/
  conftest.py      # fixture_client and fixture_transport fixtures (FixtureTransport now lives in src/)
  test_eval.py     # unit tests (CI) + @pytest.mark.eval integration tests (real LLM)
  test_web_events.py  # Phase 7: 9 tests for _sse, _build_result_payload, stream_graph_events
  test_web_server.py  # Phase 7: 6 endpoint tests via FastAPI TestClient
  fixtures/        # sanitized JSON snapshots used by all tests (no live API needed)
  fixtures/eval/   # three golden examples (project-first, stash-first, low-confidence); example-schema.json documents the shape
  fixtures/pattern_search_free.json      # Phase 6a: free-pattern search fixture
  fixtures/pattern_search_popular.json   # Phase 6a: popular-pattern search fixture
  fixtures/pattern_detail.json           # Phase 6a: batch pattern detail (Phase 7: pattern 1001 gets first_photo)
  fixtures/library_search_patterns.json  # Phase 6a: user library search fixture
docker-compose.yml # Langfuse v2 self-hosted + Postgres; pre-seeded org/project/API keys
```

## Graph architecture

The LangGraph pipeline:

```
supervisor → [project_first_filter | stash_first_filter]
           → assess_filter_quality
           → high: pattern_search → recommend → format_output
             low:  low_confidence_output → (force_recommend?) pattern_search → recommend | END
```

- **supervisor**: classifies user input into `project_first` (goal-driven) or `stash_first` (yarn-driven) mode; extracts weight/yardage into `StashFilter` for stash-first inputs; detects temporal phrases ("oldest", "longest", "been sitting", "first acquired") and sets `oldest_first=True`. Phase 14a will allow the web UI to pre-set `mode` in `GraphState`; when mode is already set, supervisor skips classification but still runs filter extraction.
- **project_first_filter / stash_first_filter**: filter `normalized_stash` down to ≤20 candidates using `StashFilter` criteria or goal keywords. Sort order: `added_date` ascending (oldest first) when `oldest_first=True`, otherwise `yards_total` descending.
- **assess_filter_quality**: sets `filter_confidence` to `"high"` or `"low"` based on candidate count; routes to `pattern_search` or `low_confidence_output` accordingly.
- **low_confidence_output**: warns the user about low-quality filter results and prompts via `click.confirm`; sets `force_recommend` to continue or exits to `END`.
- **pattern_search**: deterministic node that runs four Ravelry API calls (library IDs, free search, popular search, batch detail), each independently graceful. Writes `pattern_candidates` sorted library→free→popular, capped at 10. Uses `FixtureTransport` when `use_fixture=True`; falls back to live credentials otherwise. Full failure writes `[]`, which causes `recommend` to produce abstract archetypes.
- **recommend**: calls the LLM (model from `SKEINMINDER_MODEL` env var) with a system-prompt-cached prompt; conditionally includes a formatted pattern list and pairing rule when `pattern_candidates` is non-empty. Returns up to 3 `Recommendation` objects via structured output.
- **format_output**: renders recommendations as a plain-text CLI report, resolving stash IDs back to yarn names. Renders a `Pattern: <name> — <url>` line when pattern fields are set.

Every node is decorated with `@observe(name=...)` from `langfuse.decorators`. The decorator is a no-op when `LANGFUSE_PUBLIC_KEY` is absent, so all tests pass without credentials. The CLI's `_run_recommend()` function carries the root `@observe(name="skeinminder-recommend")` trace.

In tests, `recommend` is patched at `skeinminder.graph.nodes.recommend` — the node function itself, not the LLM client — so the full graph routing logic is exercised without live API calls. `pattern_search` runs as a real node via `FixtureTransport` in all integration tests.

## Testing conventions

- Use `@pytest.mark.parametrize` whenever multiple tests call the same function with different inputs and assert the same shape of result. Collapse them into one parametrized test rather than writing individual named functions.
- Keep tests as named functions when the setup or assertion structure differs meaningfully between cases — parametrize is for input variation, not behavioral variation.
- When parametrized test data is complex or multi-field, extract it into a named list above the test — `SCENARIOS = [{"state": ..., "expected": ...}, ...]` — and pass each dict as a single `scenario` parameter. When each scenario is a single value, use `pytest.param(value, id="name")` directly; a one-field dict adds no value.
- Use `pytest.param({...}, id="name")` when preserving a descriptive test node name matters for diagnosing failures. Plain dicts auto-generate `scenario0`, `scenario1`, etc., which is acceptable when the scenario content is self-evident from the dict.
- Fixture files in `tests/fixtures/` should be small and representative (one or a few items per category), not exhaustive dumps. Full exports belong in gitignored files.

## Key design rules

- Raw models (`Raw*`) map directly to API JSON. `StashItem` in `normalizer.py` is the normalized domain model — always work with `StashItem` inside the app, not raw models.
- Tests use `FixtureTransport` (injected into `RavelryClient` via the `transport=` kwarg) — never hit the live Ravelry API in tests.
- No write to Ravelry or external services without an explicit human approval checkpoint (`requires_approval` flag in `GraphState`; currently always `False` — the approval gate is a Phase 10 stub).
- The web server's `POST /approve/{id}` and `POST /cancel/{id}` endpoints are Phase 10 stubs — they accept requests but are not yet wired to the graph interrupt mechanism.
- Every future write tool needs a dry-run mode.
- The web UI is being extended to a three-mode wizard (Phases 13–14): Mode 1 open/allow-purchase, Mode 2 stash-constrained project-first, Mode 3 yarn-specific stash-first. New `GraphState` fields `allow_purchase: bool` (Phase 14) will be added; avoid hardcoding assumptions that recommendations must always draw from stash yarn.

## Git workflow

- Never commit directly to `main`. All work goes on a feature branch (e.g., `phase3`) and merges via PR.
- Do not commit `docs/superpowers/` — it is gitignored intentionally. Specs and plans in that directory are local working documents, not part of the project history.

## CI

GitHub Actions (`.github/workflows/ci.yml`) runs on PRs and pushes to `main`: pre-commit (ruff + mypy) in one job, pytest in another. Both use Python 3.13 and `uv`.
