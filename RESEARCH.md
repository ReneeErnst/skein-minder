# SkeinMinder Research Notes

_Last updated: 2026-05-31 (expanded product concept to three entry modes; added Phases 8–10; renumbered former Phases 7b–12 to Phases 8–15; added Phase 16; reprioritized for interview — added Phase 9 demo polish, promoted human approval to Phase 10, added Phase 12 eval depth pass, deferred UX wizard to Phase 13, deferred allow-purchase to Phase 14, renumbered cleanup/production to Phases 15–18; Phase 8 complete — PR #12)_

## Working project name

**SkeinMinder** — a Ravelry-powered multi-agent studio planner that turns a real yarn stash into feasible, scheduled, human-approved fiber projects.

## Engineering goals

SkeinMinder is a production-shaped LangGraph application built on top of the Ravelry API. It reads a real Ravelry stash, uses multiple specialized agents to evaluate project feasibility, and only writes back to Ravelry or external tools after a human approval checkpoint.

Key engineering themes:

- API integration with a real third-party system.
- Typed service-layer design.
- Stateful multi-agent orchestration with LangGraph.
- Human-in-the-loop approvals before side effects.
- Deterministic tool execution separated from LLM reasoning.
- Observability, test fixtures, dry-run mode, retries, and validation.

## Repository strategy

The new repo `skein-minder` was created from scratch. The old repo
[`ReneeErnst/ravelry_playground`](https://github.com/ReneeErnst/ravelry_playground)
is preserved as provenance — it demonstrates prior Ravelry API exploration using
Cauldron notebooks, BigQuery, and GCS. The new project is the modernized
application version.

## Implementation status

### Phase 0 — Project setup ✅ COMPLETE

Repo exists at `skein-minder` on the `project-init` branch (not yet merged to
`main`). Stack: Python 3.13, uv, hatchling, ruff, mypy (strict), pytest,
pre-commit. CI runs on PRs and pushes to `main` via GitHub Actions.

Commands:

```bash
uv sync               # install dependencies
make lint             # ruff check
make format           # ruff format
make typecheck        # mypy strict
make test             # pytest
make check            # pre-commit + pytest (what CI runs)
```

### Phase 1 — Ravelry read-only client ✅ COMPLETE

All of the following is implemented, tested (58 tests passing), and passing CI.

**Files built:**

```
src/skeinminder/
  config.py                  # ConfigError, get_ravelry_credentials(), RAVELRY_BASE_URL
  ravelry/
    exceptions.py            # RavelryError, RavelryAuthError, RavelryRateLimitError,
                             #   RavelryAPIError(status_code, url, body), NormalizationError
    models.py                # 10 raw Pydantic models (see below)
    client.py                # RavelryClient with Basic Auth, retries, pagination
    sanitizer.py             # strips personal fields before committing fixtures
    recorder.py              # one-shot live fixture capture script
  cli.py                     # `skeinminder stash [--fixture]` click command
tests/
  conftest.py                # FixtureTransport, fixture_client, fixture_transport fixtures
  fixtures/
    current_user.json        # sanitized: id=7036752, username="[REDACTED]"
    stash_list.json          # 1,379 items (full sanitized stash — refreshed 2026-05-14)
    stash_detail_sample.json # sample of detail-format items (refreshed 2026-05-14)
    stash_list_full.json     # 1,379 items — GITIGNORED, legacy local copy
```

**Raw Pydantic models** (`models.py`, all use `extra="ignore"`):

- `RawFiberCategory` — id, name
- `RawYarnWeight` — id, name
- `RawYarn` — id, name, yarn_company_name, yarn_weight, grams (float|None), yardage (float|None), fiber_categories
- `RawStashStatus` — id, name
- `RawPack` — id, primary_pack_id (int|None), skeins (float|None), total_yards, total_grams, yards_per_skein, grams_per_skein
- `RawStashItem` — id, permalink, colorway_name, stash_status, skeins (float|None — always null from API), notes, yarn_name, yarn, color_family_name, packs (list[RawPack])
- `RawPaginator` — page, page_size (optional), results, pages (alias: page_count), last_page
- `RawStashListResponse` — stash (list), paginator
- `RawStashDetailResponse` — stash (single item)
- `RawUser` — id, username, small_photo_url, large_photo_url
- `RawCurrentUserResponse` — user

**RavelryClient** (`client.py`):

- Constructor: `RavelryClient(username, password)` or `RavelryClient(transport=...)` for testing. Raises `ConfigError` if no credentials and no transport.
- `get_current_user() -> RawUser`
- `get_stash_list(username: str) -> list[RawStashItem]` — paginates automatically
- `get_stash_detail(username: str, stash_id: int) -> RawStashItem`
- `_get(path, params)` — internal, wrapped with tenacity (3 retries, exponential backoff). Retries on 429, 5xx, and network errors (status_code=0).
- Implements context manager (`with RavelryClient(...) as client`).

**FixtureTransport** (`tests/conftest.py`):

Custom `httpx.BaseTransport` that routes requests to local fixture files without hitting the network. Use `fixture_client` pytest fixture to get a `RavelryClient` backed by fixtures.

**CLI** (`cli.py`):

```bash
uv run skeinminder stash           # live mode, requires .env credentials
uv run skeinminder stash --fixture # fixture mode, no credentials needed
```

**Recorder** (run once to refresh fixtures from live API):

```bash
uv run python -m skeinminder.ravelry.recorder
```

Requires `.env` with `RAVELRY_USERNAME` and `RAVELRY_PASSWORD`. Writes sanitized
JSON to `tests/fixtures/`. Review before committing — ensure no personal data remains.

### Phase 2 — Stash normalization and scoring ✅ COMPLETE

**Files built:**

```
src/skeinminder/ravelry/
  normalizer.py   # enums, StashItem, normalize_stash_item, normalize_stash,
                  #   yardage_buffer, weight_match, fiber_suitability
tests/
  test_normalizer.py
  test_scoring.py
```

**Domain model** (`normalizer.py`):

```python
class WeightCategory(str, Enum):
    # lightest to heaviest
    THREAD / COBWEB / LACE / LIGHT_FINGERING / FINGERING /
    SPORT / DK / WORSTED / ARAN / BULKY / SUPER_BULKY / UNKNOWN

class ProjectQuantity(str, Enum):
    SWEATER    # weight-adjusted threshold (see _SWEATER_YARDS_BY_WEIGHT)
    ACCESSORY  # 200 yards up to SWEATER threshold
    SCRAP      # < 200 yards

class MatchScore(str, Enum):
    EXACT / ADJACENT / MISMATCH

class StashItem(BaseModel):  # Pydantic BaseModel, not dataclass
    stash_id: int
    brand: str
    yarn_name: str
    colorway: str | None
    weight_category: WeightCategory
    fiber: list[str]
    color_family: str | None
    skeins: float
    yards_per_skein: float
    yards_total: float
    grams_total: float | None
    notes: str | None
    project_quantity: ProjectQuantity
```

SWEATER thresholds by weight: Thread/Cobweb 2000 yds, Lace 1500, Light Fingering 1100, Fingering 1200, Sport 1000, DK 900, Worsted 800, Aran 650, Bulky 500, Super Bulky 300, Unknown 800.

**Key normalizer behaviors:**

- `normalize_stash_item(raw)`: raises `NormalizationError` if yarn is None or yarn.yardage is None. Skeins resolution order: primary pack skeins → raw.skeins → default 1.0.
- `normalize_stash(raw_items)`: calls normalize_stash_item for each item; silently skips items that raise NormalizationError (logs at DEBUG). Returns only items that could be fully normalized.
- `yardage_buffer(item, pattern_yards) -> float`: percent overage (positive) or deficit (negative).
- `weight_match(item, pattern_weight) -> MatchScore`: EXACT, ADJACENT (one step in `_WEIGHT_ORDER`), or MISMATCH.
- `fiber_suitability(item, garment_type) -> MatchScore`: based on known fiber/garment rules in `_FIBER_RULES`.

### Phase 2b — API investigation ✅ COMPLETE

All three blockers resolved. See "Critical Ravelry API discoveries" for full findings.

- **Skeins mystery solved.** Skein count lives in `packs[n].skeins` on the detail endpoint (primary pack only — `primary_pack_id: null`). Top-level `skeins` is always null. `RawPack` model added; `_primary_pack_skeins()` reads it.
- **Weight-adjusted thresholds implemented.** `ProjectQuantity` classification now uses `_SWEATER_YARDS_BY_WEIGHT` per-weight lookup. THREAD, COBWEB, and LIGHT_FINGERING weight categories added.
- **Stash detail schema documented.** Raw pre-Pydantic capture confirmed `fiber_categories` is absent from both list and detail formats; fiber requires a separate yarn detail request.
- **Playwright MCP configured** in `.mcp.json` for future API doc exploration. Not currently loading in Claude Code sessions.

73 tests passing, CI clean. Branch: `phase2b` (not yet merged to main).

### Phase 3 — First LangGraph MVP ✅ COMPLETE

Graph implemented on `phase3` branch (not yet merged to main). 109 tests passing, CI clean.

**Files built:**

```
src/skeinminder/
  graph/
    __init__.py
    state.py     # GraphState (TypedDict), StashFilter, Recommendation (Pydantic)
    nodes.py     # supervisor, project_first_filter, stash_first_filter, recommend, format_output
    graph.py     # build_graph() → CompiledStateGraph
  cli.py         # added `recommend` command with --fixture flag
tests/
  test_graph_state.py
  test_supervisor.py
  test_filters.py
  test_graph.py
```

**Known quality issues (fixed in Phase 3b):**
- LLM recommends weight mixing (sport + DK + worsted in one garment).
- Weaving yarn (e.g. Maurice Brassard 16/2 Bamboo) passes through filters.
- Accessory-quantity yarn passes through for sweater goals.
- LLM forces 3 recommendations even when stash cannot support them.

### Phases 3b–6b — COMPLETE (merged to main)

### Phase 7 — Web UI ✅ COMPLETE (PR #11)

Browser-based UI that wraps the existing LangGraph pipeline. The graph runs
server-side; the frontend streams progress via SSE and renders recommendation
cards when done.

**Files built:**

```
src/skeinminder/web/
  __init__.py
  events.py      # stream_graph_events() — astream_events → SSE bridge
                 #   _build_result_payload() enriches recommendations with photo_url
                 #   saves last_run.json after each run
  server.py      # create_app() FastAPI factory
                 #   POST /recommend → stream_id (non-blocking)
                 #   GET /stream/{id} → SSE
                 #   GET /replay → last_run.json fallback
                 #   POST /approve/{id}, POST /cancel/{id} → Phase 10 stubs
  static/
    index.html   # three-phase structure (phase-input / phase-running / phase-results)
    app.js       # SSE consumer, phase controller, card renderer, Load last run
    graph.js     # vis-network 8-node topology; setNodeState(name, state)
    style.css    # cream/burgundy/green palette, staggered card animation
src/skeinminder/ravelry/patterns.py
                 # + RawFirstPhoto model; PatternSummary gains photo_url field
src/skeinminder/cli.py
                 # + skeinminder web [--port PORT] [--fixture]
tests/
  test_web_events.py   # 9 tests: _sse, _build_result_payload, stream_graph_events
  test_web_server.py   # 6 endpoint tests via FastAPI TestClient
```

**Architecture decisions:**

- `create_app()` factory loads stash once at startup; each `/recommend` creates
  an `asyncio.Queue` and fires a background task via `asyncio.create_task`.
- `stream_graph_events()` is an async generator that wraps LangGraph's
  `astream_events(version="v2")` — filtering to known node names only.
- `_build_result_payload()` joins each `Recommendation` with its matching
  `PatternSummary` (by `pattern_id`) to attach `photo_url` for card images.
- The LangGraph mock in streaming tests uses actual `Recommendation` objects
  (not plain dicts), which is what LangGraph returns in Python `astream_events`.
- mypy `disable_error_code = ["untyped-decorator"]` applied to `web.server`
  module — FastAPI decorators are untyped in strict mode.

**194 tests passing, CI clean.**

---

### Phase 8 — Stash date filtering ✅ COMPLETE (PR #12)

Surfaces `created_at` from Ravelry stash items so temporal queries like "use my oldest fingering weight" sort by acquisition date rather than yardage. All changes are additive — existing behavior is unchanged when `oldest_first=False`.

Background: discovered during Phase 7 UI testing. The supervisor correctly identified "use up" as stash-first mode and filtered by weight, but sorted by yardage descending rather than age. The Ravelry API returns `created_at` on every stash item (confirmed via raw capture — format: `"YYYY/MM/DD HH:MM:SS ±HH:MM"`), which was previously dropped by `extra="ignore"`.

**What was built:**

- `RawStashItem` gains `created_at: str | None = None`.
- `StashItem` gains `added_date: datetime | None = None`. New `_parse_ravelry_date(s)` helper in `normalizer.py` parses the Ravelry date string (handles timezone offsets; returns `None` for None or malformed input). `normalize_stash_item` populates `added_date`.
- `StashFilter` gains `oldest_first: bool = False`.
- `supervisor` detects `_TEMPORAL_TRIGGERS` frozenset ("oldest", "longest", "been sitting", "first acquired") and sets `oldest_first=True` on the `StashFilter`.
- Both filter nodes: when `oldest_first=True`, sort by `added_date` ascending via `_date_sort_key` (items with no date sort last via `datetime.max` sentinel); otherwise sort by `yards_total` descending.
- `tests/fixtures/stash_list.json`: 10 of 39 items now carry `created_at` with a spread of 2016–2025 dates (3 old / 4 mid / 3 recent).
- Tests added: `_parse_ravelry_date` (4 cases), supervisor temporal keyword detection (5 parametrized cases), filter sort-by-age including `project_first_filter` path and naive-datetime guard.

Note: `stash_list_full.json` still lacks `created_at` (built via `model_dump()` before the field was added); re-running the recorder is the cleanest way to refresh it. The sanitizer does not currently strip `created_at` — timestamps are low-sensitivity, but add them to `_sanitize_stash_item` before the next fixture refresh if desired.

**211 tests passing, CI clean.**

---

**Demo completion order.** Phases 1–8 are merged. To reach a strong live demo for a technical audience, complete in this order:

1. **Phase 9** — demo polish (`click.confirm` in `low_confidence_output` currently hangs the web UI on the low-confidence path — a hard blocker before any live demo; Phase 9 also adds mode echo-back, compile-once graph optimization, and stream TTL eviction)
2. **Phase 10** — human approval (the product's core safety claim is today a stub: `/approve` and `/cancel` return 202 and do nothing; for a technically demanding audience this is the centerpiece feature, not a stretch goal)
3. **Phase 12** — eval depth (a failing golden example with a visible Langfuse trace is stronger demo material than three examples that all pass)

Phases 11 and 13–18 strengthen the product but are not required for a compelling technical demo.

---

### Phase 9 — Demo polish

Goal: two targeted improvements that unblock a clean live demo and lay groundwork for Phase 10. Both are self-contained.

**Stream the `recommend` LLM response**

The `recommend` node currently blocks 2–5 seconds before the user sees anything. The Anthropic API supports streaming; adding it gives visible progress immediately. The SSE infrastructure in `events.py` already carries the result payload — the change is in how `recommend` produces tokens, not how the frontend receives them. This is the highest-impact UX improvement relative to effort in the backlog.

**`click.confirm` → LangGraph `interrupt()` (in `low_confidence_output`)**

`low_confidence_output` uses `click.confirm()` — a blocking terminal call that is incompatible with the web UI and prevents clean testing of the low-confidence graph path. Migrating to LangGraph's `interrupt()` mechanism is required before Phase 10 anyway. This also requires wiring a `MemorySaver` checkpointer into `build_graph()` — the same checkpointer Phase 10 depends on.

Tasks:
- Replace `click.confirm()` in `low_confidence_output` with `interrupt()` — this is the hard blocker; the web UI hangs indefinitely on the low-confidence path today.
- Wire `MemorySaver` checkpointer into `build_graph()`; propagate `thread_id` through the CLI and web server.
- Update tests for the interrupt-based low-confidence path.
- Add streaming to `recommend` node; emit SSE token events so the frontend shows incremental output.
- Echo the detected mode in the web UI before the graph continues (e.g., "Running in stash-first mode…"). One sentence of feedback that makes silent supervisor misclassification visible without adding latency. This is the cheapest fix for supervisor robustness and should be done before any embedding-based classifier work.
- Compile the LangGraph graph once at server startup rather than per-request. `stream_graph_events()` currently calls `build_graph()` on every SSE request; move compilation into `create_app()` and pass the compiled graph through.
- Wire TTL-based eviction for `_streams` (moved up from Phase 15 — this is a memory leak, not cleanup). Store a creation timestamp alongside each queue; a lightweight `asyncio` background task sweeps entries older than ~5 minutes. Prevents unbounded memory growth when clients call `POST /recommend` but never connect to `GET /stream/{id}`.

---

### Phase 10 — Human approval checkpoints

_Promoted from Phase 12. Phase 9 lays the required checkpointer groundwork. Full planning notes in the Implementation plan section below._

Goal: demonstrate safe agentic control before any write operations — the centerpiece feature for a technically demanding audience. Surfaces LangGraph checkpointing, the interrupt/resume pattern, and human-in-the-loop design together.

---

### Phase 11 — Ravelry project write-back

_Promoted from Phase 13. Depends on Phase 10 (approval gate). Full planning notes in the Implementation plan section below._

_**Demo path: defer until after Phase 12.** Phase 11 completes the first end-to-end write loop but is not required for a compelling demo — Phase 10 (the approval gate itself) is the feature a technical audience wants to see. Implement Phase 12 (eval depth) before Phase 11._

Goal: create or update a Ravelry project from an approved recommendation, completing the first end-to-end write loop.

---

### Phase 12 — Eval depth pass

Goal: strengthen the eval suite for a technically demanding audience. Walking through a failing example — and showing how the Langfuse trace illuminates the failure — is a stronger demo than three examples that all score well.

Tasks:
- Add one failing or edge-case golden example: an input that fails a deterministic assertion (e.g., hallucinated stash ID) or scores below threshold on the LLM-as-judge. Document why it fails and what the graph state shows.
- Add a third judge dimension: **pattern relevance**. Now that Phase 6 ships real pattern links, the judge can score whether the recommended pattern is a plausible fit for the stash yarn, not just whether the reasoning is coherent.
- Verify the Langfuse dashboard is demo-ready: a recent run logged with visible token counts, cost per run, and judge scores on all three dimensions. Run `skeinminder eval` against live fixtures before the interview.
- Confirm prompt caching is working: a second identical run should show `cache_read_input_tokens` in the `recommend` node's Langfuse span.

---

### Phase 13 — Guided UX Wizard (Modes 2 & 3)

_Deferred from Phase 9. Product UX improvement — deprioritized in favor of Phase 10 (human approval) before the interview. Resume after Phase 12._

Goal: Replace the single free-text input with a guided two-step wizard. Step 1 presents the three intent modes (Mode 1 rendered but disabled pending Phase 14). Modes 2 and 3 are fully implemented here. This removes the need for users to know supervisor trigger phrases and enables pre-graph stash disambiguation for Mode 3.

**Dependency:** Phase 8 (stash date filtering) should complete first so that `added_date` is available on `StashItem` and can be included in the `GET /stash` response. If Phase 13 ships before Phase 8, the `/stash` endpoint omits `added_date` and the Mode 3 search UI cannot display yarn age; the field can be added in Phase 8 without breaking Phase 13's other work.

**Step 1 — Mode selector:**

The `phase-input` screen is preceded by a new `phase-mode` screen with three option cards. Mode 1 is visible but disabled with a "Coming soon" label. Selecting Mode 2 or 3 transitions to a mode-appropriate `phase-input` form.

**Mode 2 — "Make something with my stash":**

Step 2 is the existing text box with a smarter label and placeholder: "Describe what you'd like to make — garment type, weight, skill level, any preferences." No backend changes. The supervisor runs as today (project_first path).

**Mode 3 — "Use a specific yarn":**

Step 2 shows a yarn search field. As the user types, results filter against `/stash` data in real time. The user confirms a match and proceeds, or falls through to a free-text input if they want to describe by type rather than pick a specific item.

Pre-graph disambiguation:
- Specific yarn confirmed: graph runs with `stash_filter=StashFilter(specific_stash_id=<id>)` pre-set and `mode="stash_first"` injected into initial `GraphState`. Supervisor respects a pre-set mode rather than reclassifying.
- Yarn not found before submission: return an error immediately — no graph run, no LLM call.
- Browse/type fallback: supervisor runs as today's stash_first path.

`stash_first_filter` already handles `specific_stash_id` correctly (filters to exactly that item).

**Backend changes:**
- `GET /stash` endpoint: returns normalized stash as a lightweight list — `{stash_id, brand, yarn_name, colorway, weight_category, yards_total}` per item — for client-side search.
- `POST /recommend` body gains `mode: Literal["project_first", "stash_first"] | None` and `stash_id: int | None`. When provided, these are injected into the initial `GraphState` before the graph runs.
- `supervisor` node: if `state["mode"]` is already set (non-empty), skip mode classification but still run temporal keyword extraction (Phase 8's `oldest_first` detection). Only the routing decision is bypassed — filter enrichment still applies.
- `GET /stash` response: include `added_date` when populated (requires Phase 8); omit the field gracefully if Phase 8 has not shipped.

**Frontend changes:**
- `index.html`: new `phase-mode` section with three option cards.
- `app.js`: initial phase is `phase-mode`; mode selection advances to `phase-input` with the appropriate form. Mode 3 fetches `/stash` on first load, filters client-side as the user types, and shows a confirmation step before calling `/recommend`.
- `style.css`: mode card styles.

**Speed and cost benefits:**
- Mode 3 with a confirmed yarn: supervisor skips classification, `recommend` node receives a 1-item filtered stash rather than up to 20 candidates — smaller, cheaper LLM call. Failed yarn lookup aborts before any graph work.
- Mode 2: no backend speed change; clarity improvement only.

---

### Phase 14 — Allow Purchase Mode (Mode 1)

_Deferred from Phase 10. Depends on Phase 13 (Guided UX Wizard)._

Goal: Implement the "open to buying yarn" mode, completing the three-mode wizard from Phase 13. The LLM can recommend projects that require purchasing yarn, while still prioritizing stash matches when available.

**UX changes:**
- Enable Mode 1 card in the wizard (remove "Coming soon" state).
- Mode 1 `phase-input`: same text box as Mode 2 with a different placeholder: "What would you like to make? We'll use your stash where possible and suggest yarn to buy if needed."
- Result cards: when `purchase_suggestion` is present, render a "You may need to buy yarn" section below the rationale.

**Backend changes:**
- `allow_purchase: bool` added to `GraphState` (default `False`).
- `POST /recommend` body gains `allow_purchase: bool`; set to `True` for Mode 1.
- `recommend` prompt: when `allow_purchase=True`, the stash-only constraint is lifted. The prompt adds: "If no stash yarn is a good fit, you may suggest that the user purchase yarn for this project. Populate `purchase_suggestion` with a brief description of what to look for (weight, fiber, yardage)."
- `Recommendation` model: add `purchase_suggestion: str | None = None`.
- `format_output`: render `Purchase suggestion: ...` line when set.
- `_build_result_payload` in `events.py`: include `purchase_suggestion` in the SSE result payload.
- Tests: unit tests for the modified `recommend` prompt path; update eval golden examples to cover Mode 1 behavior.

**Key distinction from Mode 2:** Mode 2 recommendations always reference a stash yarn. Mode 1 recommendations may include a `purchase_suggestion` instead of or alongside `yarn_candidate_ids` when no stash yarn is a good fit.

---

## Critical Ravelry API discoveries

These were found through live testing and should save time in future sessions.

**Authentication:**

- Use "Personal Account Access" app type (not "Read Only"). The stash endpoint requires write-level auth even for reads. A read-only app returns: `403 Forbidden. This is not a read only API method.`
- Basic Auth: `RAVELRY_USERNAME` = access key (alphanumeric API key), `RAVELRY_PASSWORD` = personal key. These are NOT the Ravelry login credentials.
- Credentials do not auto-expire but should be regenerated periodically. Store in `.env` (gitignored).

**Endpoint corrections (verified against official docs):**

| Endpoint | Correct path |
|---|---|
| Current user | `GET /current_user.json` |
| Stash list | `GET /people/{username}/stash/list.json` |
| Stash detail | `GET /people/{username}/stash/{id}.json` |

Note: the username in these URLs is the Ravelry display username (e.g., "KnittingBunnyMom"), NOT the API access key. Always call `get_current_user()` first to get the correct username from `user.username`.

**Paginator field name:**

The real API returns `page_count` (not `pages`). `RawPaginator.pages` uses `AliasChoices("pages", "page_count")` to accept both the real API and our fixture files.

**Stash list endpoint (Stash "small" format):**

- Returns `skeins=null` for all items — skein count is not populated in the list response.
- Returns `yarn.yardage` and `yarn.yarn_weight` reliably for items with linked yarn.
- Returns empty `fiber_categories=[]` for all items — fiber data is not in the list format.
- `yarn_name` is null for all items; use `yarn.name` as fallback.
- Items without a linked yarn (`yarn=null`) cannot be normalized for yardage.

**Stash detail endpoint (raw capture, 2026-05-14):**

The raw capture (pre-Pydantic) revealed the following about the detail format vs. list format:

- **Skein count lives in `packs`, not in the stash item directly.** The detail endpoint returns a `packs` array (dropped by `RawStashItem` because it was not in the model). Each pack has a `skeins` field (float|null). The primary pack (`primary_pack_id: null`) is the authoritative record. To get skein count, sum `skeins` across primary packs, or use the primary pack's `skeins` value directly.
- **The packs structure always has two entries per stash item**: a "primary" pack (`primary_pack_id: null`) and a secondary pack whose `primary_pack_id` points to the first. The secondary appears to be a UI-layer duplicate — only the primary pack should be used for quantity calculations.
- **`quantity_description` on the primary pack** gives a human-readable summary (e.g., `"1 skeins = 438.0 yards (400.5m)"`), confirming the `skeins` field is the right source of truth.
- **`skeins` can still be null in the detail format** — confirmed for stash items where the user has not entered a skein count on Ravelry (pack 126820577 in the sample returned `skeins: null`).
- **`fiber_categories` is NOT present in the detail format** — the field simply does not appear in the raw stash detail response. Fiber data must be fetched separately from the yarn endpoint.
- **`long_yarn_weight_name`, `personal_yarn_weight`, `yarn_weight_name`** are present in the detail format but not the list format. These are currently dropped by `RawStashItem`.
- **`photos`** (full array) is present in detail format vs. `first_photo` (single object) in list format. Both currently dropped.
- **`user` and `user_id`** are present in detail format. Currently dropped. Not needed for normalization.
- **`notes` and `notes_html`** are present in detail format. `notes` is already in `RawStashItem`; `notes_html` is dropped.

**Fields dropped by `RawStashItem` that are relevant for normalization:**

- `packs` (detail only) — **critical**: carries `skeins`, `total_yards`, `total_grams`, `yards_per_skein`, `grams_per_skein`, `total_meters`, `meters_per_skein`
- `yarn_weight_name` (detail only) — useful fallback if `yarn.yarn_weight` is absent
- `long_yarn_weight_name` (detail only) — human-readable weight label
- `created_at` (both list and detail) — date the item was added to the stash; format `"YYYY/MM/DD HH:MM:SS ±HH:MM"`. Confirmed via raw capture (`stash_list_raw.json`). Needed for age-based sorting ("use up my oldest yarn"). Dropped today by `extra="ignore"` — see Phase 8.
- `updated_at` (both list and detail) — date the item was last edited; same format. Lower priority than `created_at`.

## API discrepancies (to report to Ravelry)

_Discrepancies between official API documentation and observed behavior. Candidate items for a Ravelry API bug report._

- **`skeins` field on stash item**: The Ravelry API documentation describes `skeins` as a top-level field on a stash item. In observed behavior, `skeins` is null on all stash items in both the list and detail endpoints. The actual skein count is nested inside the `packs` array on the detail endpoint (`packs[n].skeins`), not at the stash-item level. The list endpoint does not return `packs` at all.
  Observed on: `/people/{username}/stash/list.json` and `/people/{username}/stash/{id}.json`. Reproducible: yes.

- **`fiber_categories` field on stash item**: The list endpoint returns `fiber_categories: []` (empty array) for all items even when yarn has known fiber content. The detail endpoint does not return `fiber_categories` at all (field absent). Fiber data must be fetched via a separate yarn detail request.
  Observed on: `/people/{username}/stash/list.json` and `/people/{username}/stash/{id}.json`. Reproducible: yes.

---

**Real stash scale:**

The demo user has 1,379 stash items. This is much larger than average and useful for stress-testing the agent design. The full stash is now committed in `stash_list.json` (sanitized). Of the 1,379 items, 1,313 normalize successfully; 66 have no linked yarn and are silently skipped. The weight-adjusted thresholds apply across all 1,313 normalized items.

---

## LangGraph fit

LangGraph is a good fit because the project needs state, routing, persistence, and human-in-the-loop control. The LangGraph persistence docs say checkpointing enables human-in-the-loop workflows, memory, time travel, and fault-tolerant execution. This is directly relevant for pausing before writing to Ravelry, Notion, Google Calendar, or Google Drive.

---

## Product concept

### Three entry modes

The system supports three directions of use, presented to the user as a mode selector in the web UI. All three share the same downstream filtering and recommendation logic — only the starting point and purchasing constraint differ.

**Mode 1 — Open ("I want to make something new"):** User describes a project goal; recommendations use stash yarn where available but may suggest purchasing yarn if no stash item fits well. This is the least constrained mode.

```text
"I want to knit a colorwork yoke sweater."
  -> filter stash by weight, yardage, fiber suitability
  -> recommend projects; if stash yarn is insufficient, include a purchase suggestion
```

**Mode 2 — Stash-constrained ("I want to make something with my stash"):** User describes a project goal; recommendations are constrained to stash yarn only. Equivalent to the original project-first behavior.

```text
"I want a fall cardigan, medium difficulty, something I can finish in 6 weeks."
  -> filter stash by weight, yardage, fiber suitability
  -> rank candidates
  -> return recommendations (stash yarn only)
```

**Mode 3 — Yarn-specific ("I want to use a specific yarn"):** User identifies a yarn from their stash (by name search or free text); the agent finds fitting project archetypes for that yarn. Pre-graph disambiguation means the graph gets a single confirmed stash item rather than a filtered list — smaller LLM context, faster response.

```text
"I want to use my Cascade 220 Superwash in the teal colorway."
  -> user searches stash, confirms the match
  -> graph runs with specific_stash_id pre-set
  -> recommend project archetypes that fit that yarn
```

Modes 2 and 3 are implemented in Phase 13. Mode 1 is implemented in Phase 14.

The graph state must accommodate all three entry points. `user_goal` (free-text goal) and `stash_filter` (weight, color, specific item, or yardage range) are both optional; at least one must be present. `allow_purchase` (Phase 14) controls whether Mode 1's looser constraint is active.

### Core workflow

User asks:

```text
Help me choose a fall cardigan project using yarn from my Ravelry stash.
Prioritize stash yarn, medium difficulty, and something I can realistically finish in 6 weeks.
```

System flow:

```text
User goal / stash filter
  -> Supervisor Agent
  -> Ravelry Stash Agent
  -> Yarn Normalizer
  -> Pattern Scout Agent
  -> Feasibility Agent
  -> Project Planner Agent
  -> Human Approval Gate
  -> Ravelry Project Creator and/or Calendar/Notion writer
  -> Verification Agent
```

### Ideal output

```text
Top recommendation: cropped textured cardigan

Why it works:
- Uses yarn already in stash.
- Yardage buffer appears acceptable.
- Fiber and yarn weight fit the garment type.
- Medium challenge level.
- Good seasonal wardrobe fit.

Risks:
- Swatch required before committing.
- Yardage may be tight for longer length or heavy cables.
- If gauge changes significantly, buy one extra skein or choose cropped length.

Next actions:
- Create Ravelry project draft.
- Link selected stash yarn if supported.
- Add generated notes to the project page.
- Schedule swatching in Google Calendar.
```

### Future interface vision

The CLI is the right demo vehicle for a technical portfolio project. The natural end state for a fiber arts audience is a web chat UI: a simple input box where the user types a goal or describes their yarn, and recommendation cards come back with rationale and risks. Most knitters already think in chat terms from Ravelry's community features.

The path from CLI to web is a thin layer once the graph exists: a FastAPI endpoint wraps the graph with SSE streaming, and a vanilla JS front end handles the three-phase UI (input → live graph animation → recommendation cards). No JS framework or build step required. The LangGraph backend doesn't change.

**Observability note for FastAPI:** When the graph moves to a web service, Langfuse trace IDs must be correlated to HTTP request IDs. Set the trace ID to the request ID (e.g., from a `X-Request-ID` header) via `langfuse_context.update_current_trace(id=request_id)` inside the `@observe`-decorated endpoint handler. This makes traces directly linkable from logs. The CLI implementation in Phase 4 does not require this — it is a FastAPI-specific concern.

Longer-term possibilities worth noting: a Discord or Slack bot that lives in knitting community servers (there are large active knitting Discords where a stash-aware bot would fit naturally), and a Ravelry-embedded panel if Ravelry ever opens extension support. Neither is a current requirement.

### LLM context window design constraint

With 1,379 stash items, even a compact normalized representation would overflow
the LLM context window. The agent architecture must filter the stash before
passing it to any LLM node. Filtering strategies to consider:

- By weight (match to pattern requirements first)
- By project_quantity (only sweater-quantity items for sweater requests)
- By status (only "In stash" items — skip "All used up" and "Traded/sold/gifted")
- By yardage floor (set a minimum based on the project type)

This is a real design constraint that makes the architecture story stronger, not weaker.

---

## Agent architecture

### 1. Supervisor Agent

Owns graph routing and decides which agents/tools run next.

Responsibilities:

- Interpret user goal.
- Decide whether project is knitting, crochet, sewing, weaving, or mixed.
- Route to stash, pattern, fit, or planner agents.
- Decide when to ask for human approval.
- Prevent destructive/write actions unless approved.

### 2. Ravelry Stash Agent

Reads stash data from Ravelry.

Responsibilities:

- Authenticate using approved credentials.
- Pull current user and stash (via `RavelryClient`).
- Normalize stash fields (via `normalize_stash`).
- Filter to actionable items (status "In stash", has yardage).
- Identify sweater quantities, accessory quantities, and scraps.
- Cache responses for demo stability.

### 3. Yarn Normalizer Agent

Already implemented as `normalizer.py`. Turns `RawStashItem` into `StashItem`.
Example normalized shape:

```json
{
  "stash_id": 98765,
  "brand": "Example Yarn Co.",
  "yarn_name": "Example Worsted",
  "colorway": "Moss",
  "weight_category": "worsted",
  "fiber": ["wool"],
  "skeins": 5.0,
  "yards_total": 1100.0,
  "grams_total": 500.0,
  "color_family": "green",
  "notes": null,
  "project_quantity": "sweater"
}
```

### 4. Pattern Scout Agent

Finds or ranks project candidates.

Responsibilities:

- Search Ravelry patterns if endpoint access is available.
- Filter by craft, category, yarn weight, yardage, difficulty, and popularity.
- Return candidate patterns and project archetypes.
- Include a fallback mode that recommends project archetypes without live pattern search.

### 5. Yarn Feasibility Agent

Evaluates whether a stash yarn is plausible for a candidate project.

Signals:

- Yardage buffer (use `yardage_buffer()` helper).
- Yarn weight match (use `weight_match()` helper).
- Fiber and drape match (use `fiber_suitability()` helper).
- Gauge risk, garment type, color suitability, washability.

### 6. Project Fit Agent

Evaluates human/project fit.

Signals:

- Desired season, time available, difficulty mood, wardrobe usefulness, novelty, likelihood of completion.

### 7. Project Planner Agent

Creates a realistic plan: swatch step, pattern review, cast-on milestones, blocking, notes for Ravelry project page, calendar-ready tasks.

### 8. Ravelry Project Creator Agent

Prepares a project payload and asks for approval.

Design rule: LLM drafts the payload; a deterministic tool validates and executes the API write; no write happens without explicit approval.

### 9. Verification Agent

Reads back created/updated records and confirms the side effect succeeded.

---

## Implementation plan

### Phase 2b — API Investigation ✅ COMPLETE (2026-05-14)

All exit criteria met. Branch: `phase2b`.

- **Skeins field:** `packs[n].skeins` on primary pack (detail endpoint only). `RawPack` model added; `_primary_pack_skeins()` helper implemented. `normalize_stash_item` reads packs first, falls back to `raw.skeins`, then defaults to 1.0.
- **Weight-adjusted thresholds:** `_SWEATER_YARDS_BY_WEIGHT` lookup implemented. THREAD, COBWEB, LIGHT_FINGERING weight categories added. `project_quantity_from_yards(yards, weight)` now takes weight as second argument.
- **Stash detail schema:** Documented via raw capture. Fiber requires separate yarn detail request (not implemented — out of scope).
- **Raw capture mode:** `recorder.py --raw` saves pre-Pydantic JSON to `tests/fixtures/raw/` (gitignored).
- **Playwright MCP:** Configured in `.mcp.json`; API docs exploration deferred (not blocking Phase 3).
- **Fixtures refreshed** with full 1,379-item stash. 73 tests passing.

**Potential future improvement (not implemented):** Weight-adjusted thresholds are currently hand-tuned constants. A more accurate approach would sample real Ravelry patterns by weight category and size to derive empirical thresholds. This would also allow `project_quantity_from_yards` to accept size as a parameter (e.g., XS vs. XXL sweaters have meaningfully different yardage requirements). See open question 6 in the Open Questions section.

---

### Phase 3b — Recommendation quality improvements ✅ COMPLETE

Goal: fix known domain-correctness problems in the phase 3 graph before moving to pattern integration.

Spec: `docs/superpowers/specs/2026-05-16-phase3b-recommendation-quality.md`

Key changes:
- **Weaving yarn exclusion.** Add `is_weaving_yarn()` heuristic (count/ply naming regex) to `normalizer.py`; add `is_weaving_yarn: bool` to `StashItem`. Both filter nodes exclude weaving yarn. The Ravelry yarn API has no `craft` field — naming is the only reliable signal.
- **Sweater quantity gate.** `project_first_filter` now requires `project_quantity == SWEATER` for sweater goals (not just "not scrap"). Accessory-quantity yarn cannot satisfy a sweater request.
- **Fiber suitability filtering.** `project_first_filter` calls the existing `fiber_suitability()` helper and excludes MISMATCH results for the detected garment type.
- **Prompt domain constraints.** System prompt updated: no weight mixing, yardage adequacy by weight, honest fiber guidance (silk/bamboo not warm), return fewer than 3 if fewer are viable.
- **Low-confidence path.** New nodes `assess_filter_quality` and `low_confidence_output`. When filtered stash is empty or yardage is clearly insufficient, the graph summarises what was found and asks the user interactively whether to proceed with available yarn or exit. A placeholder message notes that a future version will offer yarn-to-purchase suggestions.

New graph state fields: `filter_confidence: Literal["high", "low", ""]`, `force_recommend: bool`.

Updated graph routing:
```
supervisor → filter → assess_filter_quality →
  high → recommend → format_output → END
  low  → low_confidence_output →
           (user confirms) → recommend → format_output → END
           (user declines) → END
```

### Phase 3c — Code quality review ✅ COMPLETE

Goal: audit the full codebase for Python best practices before moving to pattern integration.

Scope:
- Move all deferred imports (inside functions) to module top level.
- Audit docstrings: all public functions, classes, and modules in both `ravelry/` and `graph/` packages.
- Remove dead code, commented-out blocks, and unreachable branches.
- Name any magic values that should be constants.
- Review test coverage: confirm all meaningful behaviour has deliberate test coverage.
- Fix anything ruff and mypy do not catch but a human reviewer would flag.

No new features. No spec needed — implement as a single PR with a checklist commit message.

### Phase 4 — Observability (Langfuse) ✅ COMPLETE

Goal: wire in self-hosted Langfuse tracing so every graph run is visible as a structured trace — nodes, LLM calls, filter counts, token usage, and latency — without relying on a third-party SaaS. Also lay the eval infrastructure scaffold that Phase 5 needs.

Key decisions:
- Self-hosted Langfuse via Docker Compose (local and demo-friendly); `docker-compose.yml` committed to the repo.
- Full SDK integration with `@observe` decorators on each node, not just the LangChain callback. This makes filter decisions and state transitions visible as spans, not just the LLM call.
- Langfuse replaces LangSmith vars in `.env.example`.
- Langfuse dataset configured (named, schema defined) so Phase 5 can log to it immediately.
- `tests/fixtures/eval/` directory created with one documented example file showing the input/output schema Phase 5 will populate.

Phase 4 does NOT include eval logic (assertions, scoring, CLI). That belongs in Phase 5.

Spec: `docs/superpowers/specs/YYYY-MM-DD-phase4-observability.md` (to be written)

### Phase 5 — Evaluation ✅ COMPLETE

Goal: build a two-layer eval suite using the Langfuse infrastructure from Phase 4. Deterministic assertions catch hallucinated stash IDs and filter violations; LLM-as-judge scores recommendation quality (yarn-goal fit and reasoning coherence).

Key decisions:
- Golden dataset: 3–5 JSON examples in `tests/fixtures/eval/` (schema established in Phase 4). Each example uses the sanitized fixture stash — no live Ravelry calls needed.
- Two test layers: unit tests (CI-safe, mock LLM/Ravelry) and integration tests (`@pytest.mark.eval`, excluded from CI, make real LLM calls). Unit tests cover `load_examples()`, `assert_example()`, `format_table()`, `run_example()` with mocked recommend node, and `judge_example()` with mocked Claude client.
- Deterministic assertions (`assert_example()`) check: recommendation count in range, all stash IDs are a subset of input IDs, no weight mixing across recommendations, filter confidence matches expected.
- LLM-as-judge runs via `skeinminder eval` CLI command only (too expensive for pytest). Judge scores two dimensions on a 1–5 rubric: yarn-goal fit and reasoning coherence. Scores are logged to Langfuse as named scores on judge traces.
- Golden examples are upserted as Langfuse dataset items (keyed by `example_id`) so eval coverage is visible in the UI.
- `skeinminder eval` exits non-zero if any example fails assertions or scores below 3 on either dimension.
- **Automated Langfuse evaluators are deferred to a later phase.** Phase 5 uses explicit CLI-driven scoring only. Automated evaluators require enough trace history to set meaningful thresholds — revisit after Phase 6 or 7.
- All eval logic lives in `src/skeinminder/eval.py` (single module, not a package).

Spec: `docs/superpowers/specs/YYYY-MM-DD-phase5-evaluation.md` (to be written)

### Phase 6 — Pattern integration ✅ COMPLETE

Goal: connect recommendations to real Ravelry patterns. Output is yarn+pattern pairs, not abstract project ideas.

Background: the current graph recommends abstract project archetypes. A knitter cannot act on "a modern structured cardigan" — they need a real pattern. Pattern requirements (weight, yardage, gauge) and stash yarn availability are co-constraints; the recommendation is only useful when both are resolved together.

The yarn-first approach from Phase 3 is preserved: filter stash first, then find patterns that suit the filtered yarn.

Pattern priority order:
1. Patterns already in the user's Ravelry library (`pdf_in_library: true` / `library/search` endpoint).
2. Free patterns (`free: true` in `Pattern (list)`).
3. Popular patterns (sort by `projects` or `rating` in `patterns/search`).

Key API endpoints (documented in `docs/ravelry-api/api-reference-skeinminder.md`):
- `GET /patterns/search.json` — full-text + filter search; accepts `craft`, `weight`, `availability`, `sort`.
- `GET /people/{username}/library/search.json` — search user's owned patterns.
- `GET /patterns.json?ids=ID1+ID2+...` — batch pattern detail including `yardage`, `yardage_max`, `yarn_weight`.

**Phase 6a — Pattern data layer ✅ COMPLETE (merged to main)**

- `patterns.py` — `RawPattern` (search list shape), `RawPatternFull` (batch detail shape), `RawLibraryVolume`, `RawLibrarySearchResponse`, `PatternSummary` (normalized domain model), `normalize_pattern()`. Tier assignment: library > free > popular.
- `FixtureTransport` moved from `tests/conftest.py` to `src/skeinminder/ravelry/fixture_transport.py` and extended with routes for all four pattern API endpoints.
- Pattern fixture files committed: `pattern_search_free.json`, `pattern_search_popular.json`, `pattern_detail.json`, `library_search_patterns.json`.
- `RavelryClient.get_library_pattern_ids(username)` — paginates library search; returns empty set on any failure (graceful degradation).
- `RavelryClient.search_patterns(weight, query, availability, sort, page_size)` — always passes `craft=knitting`; returns empty list on failure.
- `RavelryClient.get_pattern_details(pattern_ids)` — batch call to `/patterns.json`; returns partial map on parse failures.

**Phase 6b — Pattern graph integration ✅ COMPLETE (merged to main)**

- `Recommendation` model gains nullable `pattern_id`, `pattern_name`, `pattern_url`.
- `GraphState` gains `ravelry_username`, `use_fixture`, `pattern_candidates`.
- New `pattern_search` node (deterministic, `@observe`-decorated): runs four Ravelry API calls (library IDs, free search, popular search, batch detail), each independently graceful. Writes `pattern_candidates` sorted library→free→popular, capped at 10. Falls back to `[]` on full failure.
- `recommend` node: conditionally includes formatted pattern list and pairing rule in the LLM prompt.
- `format_output`: renders `Pattern: <name> — <url>` line when pattern fields are set.
- CLI wires `ravelry_username` and `use_fixture` through `_load_stash` into graph state.
- Eval adds `pattern_ids_from_candidates` assertion; `run_example` uses fixture transport.
- 176 tests passing. Graph routing: `assess_filter_quality` high → `pattern_search` → `recommend`; `low_confidence_output` confirm → `pattern_search` → `recommend`.

Future hook (not yet in scope): when `low_confidence_output` fires, offer to search for yarn to purchase that would satisfy the goal.

### Phase 7 — Web UI (demo + daily use)

Goal: replace the plain CLI output with a browser-based UI that is compelling for live demos to mixed technical/craft audiences and enjoyable for daily use. The graph, business logic, and all existing tests remain unchanged.

Stack: FastAPI + SSE (backend), vanilla JS + CSS (no build step), vis-network (graph animation). Visual design is Ravelry-inspired: warm cream background, deep burgundy accents, sage green for success states.

Broken into three subphases:

**Phase UI-a — Backend + CLI command:** FastAPI app, SSE streaming endpoint, LangGraph → SSE event bridge, `skeinminder web [--port 8000] [--fixture]` CLI command, `/replay` endpoint + `last_run.json` auto-save.

**Phase UI-b — Frontend structure + graph animation:** Three-phase page (input → running → results), vis-network node animation driven by SSE events, status text per node in plain English. UI-a and UI-b can run as parallel subagents — the SSE event schema is the shared contract.

**Phase UI-c — Visual polish + result cards:** Ravelry-inspired styling, recommendation cards with pattern photos and yarn tags, Phase 10 approval modal (rendered when `node_awaiting_approval` SSE event arrives; wired to real graph interrupt in Phase 10).

**SSE event schema (the UI-a/UI-b contract):**
```
node_start / node_complete — drives graph animation
node_awaiting_approval     — Phase 10 seam (defined now, emitted in Phase 10)
result                     — full recommendation payload, auto-saved
error                      — renders error state
```

**Fallback layers:** `--fixture` flag disables live API calls; "Load last run" link serves `last_run.json` from the previous successful run; `/replay` endpoint accessible from any HTTP client.

Spec: `docs/superpowers/specs/2026-05-31-web-ui-design.md`

### Phase 5b — Observability improvements ✅ COMPLETE (merged in PR #9)

Focused pass on tracing quality before Phase 6 adds more nodes.

**Issues resolved:**

1. **Token cost always $0.00 → fixed.** Root causes: (a) `@observe` creates a SPAN by default; usage/cost fields are silently ignored on SPANs — only GENERATION observations track them. Fixed by adding `as_type="generation"` to the `recommend` decorator. (b) Token counts from the LangChain call were not being reported to Langfuse. Fixed by using `with_structured_output(..., include_raw=True)` to get the raw `AIMessage` back, reading `usage_metadata` from it, and reporting via `langfuse_context.update_current_observation(usage=ModelUsage(...))`. Also passes `model=model_name` so Langfuse can look up pricing.

2. **Full stash in every span → fixed.** Added `langfuse_context.update_current_observation(input=...)` at the top of every node to replace the auto-captured `GraphState` with a compact summary (user input + stash/candidate counts). The `normalized_stash` list (1,300+ items in live mode) no longer appears in any span.

3. **Test traces polluting Langfuse → fixed.** `autouse` `disable_langfuse` fixture in `tests/conftest.py` unsets Langfuse env vars for all tests. `@pytest.mark.eval` tests are also suppressed — they use a mock LLM in CI and the full eval is run via `skeinminder eval`, not pytest.

4. **Model pricing not configured in self-hosted Langfuse.** Langfuse self-hosted has no pre-populated model pricing table; cost shows as `None` until models are registered. **Decision: add model registration to `setup_langfuse_dataset.py`.** This is the right pattern for both local dev and self-hosted production — run the script once after each fresh deployment. `langfuse Cloud` would handle this automatically, but we're targeting self-hosted. Haiku 4.5, Sonnet 4.6, and Opus 4.7 pricing is registered by the script. Update prices there when Anthropic changes rates.

5. **Export script date filtering** — `--since` flag not yet added. Low priority; deferred.

### Phase 15 — Cleanup backlog

_Revised 2026-05-31. Streaming, interrupt migration, stream TTL eviction (a memory leak, not cleanup), and mode echo-back were all pulled forward to Phase 9. Parallelism, async pagination, and caching remain deferred to Phase 18 where they fit naturally._

**1. Richer filter quality signals**

`assess_filter_quality` checks only two conditions: empty filtered stash, or sweater goal with <500 yards. Additional signals worth adding:

- All candidates are the same fiber (a mono-fiber result is suspicious for a 1,300-item stash)
- No candidates match the fiber suitability score for the goal garment type (all MISMATCH)
- Pattern candidates found but no stash yarn within one weight step of any pattern's required weight

**2. Supervisor robustness**

The `supervisor` node classifies input using hardcoded phrase-matching ("use my", "i have", etc.). Natural-language inputs outside this vocabulary are silently misclassified.

Recommended path, in order of complexity:

1. Expand the keyword set with common paraphrases ("i've got some", "there's yarn in my stash", "i want to use"). Handles the majority of real inputs at zero latency cost — do this first regardless.
2. Add a sentence-transformer embedding classifier (e.g., `all-MiniLM-L6-v2`, ~80MB) as a fallback when no keyword matches. Computes cosine similarity against a few prototype sentences per class. Runs in ~10–30ms on CPU with no network call or GPU requirement.

Option 3 (echo the detected mode and let the user correct it before the graph runs) was pulled forward to Phase 9 — it's the cheapest fix and should ship before anything else in this list.

A full generative LLM call for this classification (~200–400ms API round-trip) is disproportionate for a binary intent detection task. A self-hosted small LLM on CPU is typically no faster than the API call and adds infrastructure overhead. The sentence-transformer approach is the right ceiling for this problem.

Defer option 2 until the keyword expansion (option 1) is in place and still producing visible misclassifications.

**3. `pattern_search` weight selection**

The node derives the Ravelry query weight as `max(filtered_stash, key=lambda i: i.yards_total).weight_category`. When `project_first_filter` runs without a weight constraint, `filtered_stash` may span multiple weight categories; the search covers only the heaviest-yardage item's weight and misses patterns suited to lighter items. Better priority order: extract weight from the user's goal first; fall back to the modal weight across filtered items; then fall back to the heaviest-yardage item.

**4. Hallucinated stash IDs fail silently**

`format_output` calls `stash_by_id.get(sid)` and silently drops any ID the LLM invented. The eval suite's `assert_example()` catches this in tests, but production runs have no signal. Add `_logger.warning("LLM returned stash ID %d not in filtered_stash", sid)` — one line, materially improves debuggability.

**5. `LAST_RUN_PATH` is a process-relative path**

`LAST_RUN_PATH = Path("last_run.json")` resolves against whatever directory `uvicorn` starts in. Pin it relative to `__file__` or make it configurable via env var. Low priority until Phase 18 replaces it with a proper result store, but trivial to harden now.

---

### Phase 10 — Human approval checkpoints

Goal: demonstrate safe agentic control before any write operations. Phase 9 lays the required groundwork — the `MemorySaver` checkpointer is wired and `low_confidence_output` is migrated to `interrupt()` there; Phase 10 extends the same pattern to the write-operation approval gate.

Tasks:
- Add interrupt/checkpoint before any write operations.
- Show draft payload before side effects.
- Require explicit approval to continue.
- Store graph thread state.
- Add rejection/edit path.

**LangGraph checkpointing:** `interrupt()` requires a checkpointer — LangGraph must be able to serialize and store the graph state at the pause point so it can resume after the user approves. For local/demo use, `MemorySaver` (in-process) is sufficient. For multi-user deployment, a `PostgresSaver` (or equivalent persistent checkpointer) is required, since the graph may pause across requests and the server may restart in between. The checkpointer also enables multi-turn conversation within a session ("show me simpler options" or "try worsted instead"), since prior state can be loaded and branched from. Wire the checkpointer when implementing `interrupt()` — retrofitting it later requires thread-ID management that's easier to add once at the start.

**Web UI integration:** Phase 7 (UI-c) builds the approval modal in the browser (triggered by `node_awaiting_approval` SSE event) and the `/approve` + `/cancel` endpoints in the backend. Phase 10 wires the real `interrupt()` call — no frontend changes needed beyond what Phase 7 already delivers.

Note: the low-confidence interactive prompt migrated in Phase 9 is a lightweight precursor to this — same interrupt/resume concept applied earlier in the graph.

### Phase 11 — Ravelry project write-back

Goal: create or update a Ravelry project from an approved recommendation.

With Phase 6 complete, write-back now has a real pattern reference to include alongside the yarn link.

Tasks:
- Add `draft_ravelry_project` and `create_ravelry_project` tools.
- Link stash yarn and pattern ID to the created project.
- Add dry-run mode.
- Add verification read-back.

API reference: `docs/ravelry-api/api-reference-skeinminder.md` covers project endpoints.

### Phase 12 — Eval depth pass

Goal: strengthen the eval suite for a technically demanding audience. Walking through a failing example — and showing how the Langfuse trace illuminates the failure — is a stronger demo than three examples that all score well.

Tasks:
- Add one failing or edge-case golden example: an input that fails a deterministic assertion (e.g., hallucinated stash ID) or scores below threshold on the LLM-as-judge. Document why it fails and what the graph state reveals in the Langfuse trace.
- Add a third judge dimension: **pattern relevance**. Now that Phase 6 ships real pattern links, the judge can score whether the recommended pattern is a plausible fit for the stash yarn — not just whether the reasoning is coherent.
- Verify the Langfuse dashboard is demo-ready: a recent run logged with visible token counts, cost per run, and judge scores on all three dimensions. Run `skeinminder eval` against live fixtures before the interview.
- Confirm prompt caching is working: a second identical run should show `cache_read_input_tokens` in the `recommend` node's Langfuse span.

### Phase 16 — External productivity integration (tentative)

Google Calendar first (value is easy to demo). Schedule swatching and milestones.

Note: Ravelry projects support start dates natively, which may make calendar integration unnecessary. Revisit after Phase 11 (Ravelry write-back) before committing to Phase 16.

### Phase 17 — Documentation polish

The demo UI itself (fixture mode, fallback, animated graph, result cards) is delivered by Phase UI. This phase covers remaining documentation artifacts: screenshots/GIFs for the README, an architecture diagram, sample prompt scripts, and a known-limitations section.

---

### Phase 18 — Production deployment readiness

Goal: make SkeinMinder safe to deploy for more than one user. The changes here are not about new features — they are about isolating users from each other, managing resources correctly, and handling credentials at production scale. Also incorporates the parallelism and caching work deferred from Phase 15.

**Dependency:** Phase 10 (human approval checkpoints) should complete first — specifically the LangGraph checkpointer work — since that decision directly shapes the persistence layer choices here.

**1. Multi-user session layer**

Currently the app is hard-wired for one user: credentials come from env vars, one stash is loaded at startup, and `ravelry_username` is a single string in `GraphState`. To serve multiple users:

- Each request must carry its own Ravelry credentials. The most straightforward path for a web deployment is an OAuth flow using Ravelry's OAuth 2 support; Basic Auth with per-user credential storage is an alternative if OAuth is not available.
- `create_app()` can no longer take a single `stash` argument. Stash loading moves from startup into the request handler, guarded by the per-user TTL cache (item 5 below).
- `ravelry_username` in `GraphState` must reflect the requesting user, not a process-level constant.

**2. Per-user stash isolation**

Once the session layer exists, the stash cache (item 5 below) becomes the primary data store for user state between requests. Key requirements:

- Cache entries must be keyed by authenticated user identity, not just the username string.
- Strip `notes` from cached stash items — this field can contain personal context (gift notes, purchase history, prices paid) and should not persist beyond the lifetime needed for a single recommendation run.
- Normalized stash size at scale: ~1–2MB per user. At 1,000 concurrent users that is 1–2GB in Redis — manageable. The normalized form is already compact since `StashItem` discards most `RawStashItem` fields.

**3. Run result persistence**

`last_run.json` is a single file written to the working directory. It is not user-scoped, not safe for concurrent writes, and disappears on redeploy. Replace it with a proper result store:

- A `runs` table in Postgres (or similar) keyed by `(user_id, run_id)` with a TTL or explicit cleanup policy.
- The `/replay` endpoint queries the store by authenticated user rather than reading a hardcoded file path.
- Consider whether run history (more than just the last run) is useful — users may want to compare recommendations across sessions.

**4. Cost and rate limit considerations**

At scale, per-request Ravelry API calls are the primary cost risk, not LLM calls. A single recommendation run makes up to four Ravelry API calls (items 5 and 6 below address caching). Beyond caching:

- Monitor Ravelry API rate limits (open question 5 — limits are not documented, test empirically). Add per-user rate limiting at the application layer before Ravelry enforces it.
- LLM cost per run is low using Haiku (~$0.01 or less). If Sonnet is ever used for better recommendation quality, cost rises to ~$0.05–0.10 per run — still acceptable for a consumer app but worth tracking via Langfuse cost reporting.
- Prompt caching (`cache_control: ephemeral`) is already in place on the system prompt. Make sure the system prompt is stable across requests for the same user — any per-user content injected into the system prompt breaks cache hits.

**5. Normalized stash caching**

The stash is currently fetched from Ravelry and normalized on every process start. For a web service, this means every cold start hits the API. A simple TTL cache (15–30 minutes, keyed by Ravelry username) eliminates repeated fetches within a session and is negligible in storage: a normalized stash of 1,300 items serializes to roughly 1–2MB of JSON — the normalized form is smaller than the raw API response because `StashItem` discards most `RawStashItem` fields.

Implementation notes:
- In-memory dict cache is sufficient for a single-process server; Redis if multi-process.
- Cache the normalized `list[StashItem]`, not the raw API response. Normalization is cheap but the raw response is larger.
- Strip the `notes` field before caching — it can contain PII (purchase history, gift notes, personal context) and is not used by any graph node. The same principle that governs `sanitizer.py` for fixtures applies here.
- Add a "Refresh stash" button in the web UI as a manual invalidation escape hatch. Ravelry has no push events (no webhooks), so TTL expiry is the only automatic mechanism.

**6. Pattern search caching**

`pattern_search` makes four Ravelry API calls per run (library IDs, free search, popular search, batch detail). The free and popular searches are keyed by weight and goal keyword — stable across users and requests within a short window. A shared cache (Redis, short TTL of 5–15 minutes) keyed by `(weight, query, availability, sort)` would substantially reduce Ravelry API call volume when multiple users make similar requests.

Library pattern IDs are user-specific and should not be shared across users; cache them per username alongside the stash cache.

**7. Parallel pattern search and stash filtering (LangGraph fan-out)**

The highest-leverage parallelism opportunity in the graph. Pattern search and stash filtering are independent operations — pattern search needs the goal/weight from `supervisor`, stash filtering needs the stash — and can run in parallel via LangGraph's fan-out support. After `supervisor` resolves, two branches can execute concurrently:

- `project_first_filter` or `stash_first_filter` (~10ms)
- `pattern_search` node (~500ms–1s: Ravelry pattern search + detail fetch)

Both results join before `assess_filter_quality`. This eliminates pattern lookup latency from the user's perspective without affecting the LLM call.

**8. Async Ravelry pagination**

`get_stash_list()` and `get_library_pattern_ids()` paginate sequentially. For a 1,300-item stash (13 pages), switching from `httpx.Client` to `httpx.AsyncClient` with `asyncio.gather()` could reduce stash load time by 70–80% on live runs. Requires converting `RavelryClient` to async or adding an async variant. The pattern search path (`search_patterns` + `get_library_pattern_ids`) would also benefit, since those two calls are independent and currently run serially.

**9. Infrastructure summary**

Minimum additions for a multi-user deployment:
- Redis (stash cache + pattern search cache + stream TTL eviction)
- Postgres (run results, LangGraph `PostgresSaver` checkpointer)
- Session/auth layer (OAuth or equivalent)
- Per-user rate limiting middleware

The existing Docker Compose setup (currently Langfuse + Postgres) can be extended to include Redis. The Postgres instance already present for Langfuse can host the `runs` table and the LangGraph checkpointer tables in a separate schema.

---

## Current repo structure

```text
skein-minder/
  README.md
  RESEARCH.md
  CLAUDE.md
  pyproject.toml
  uv.lock
  Makefile
  docker-compose.yml   # Langfuse v2 + Postgres; pre-seeded API keys
  .env.example         # RAVELRY_USERNAME / RAVELRY_PASSWORD / ANTHROPIC_API_KEY stubs
  .env                 # GITIGNORED — personal credentials
  .pre-commit-config.yaml
  .github/workflows/ci.yml
  src/
    skeinminder/
      __init__.py
      config.py          # ConfigError, get_ravelry_credentials, RAVELRY_BASE_URL
      cli.py             # skeinminder stash / recommend / eval click commands
      observability.py   # get_langfuse_client() — no-op when credentials absent
      eval.py            # load_examples, run_example, assert_example, judge_example, format_table
      ravelry/
        __init__.py
        exceptions.py         # RavelryError hierarchy + NormalizationError
        models.py             # raw Pydantic models (RawUser, RawYarn, RawPack, RawStashItem, etc.)
        client.py             # RavelryClient (Basic Auth, retries, pagination, pattern search)
        normalizer.py         # StashItem, enums, normalize_stash, scoring helpers
        patterns.py           # RawPattern, RawPatternFull, PatternSummary, normalize_pattern
        fixture_transport.py  # FixtureTransport — routes test HTTP to JSON fixture files
        sanitizer.py          # strip personal data before committing fixtures
        recorder.py           # one-shot: captures live API responses as fixtures
      graph/
        __init__.py
        state.py    # GraphState (TypedDict), StashFilter, Recommendation
        graph.py    # build_graph() — compiles the LangGraph StateGraph
        nodes.py    # all graph nodes: supervisor, filters, assess_filter_quality,
                    #   low_confidence_output, recommend, format_output
      scripts/
        setup_langfuse_dataset.py  # idempotent: create dataset + upsert golden examples
  tests/
    __init__.py
    conftest.py          # fixture_client / fixture_transport fixtures (use FixtureTransport from src/)
    test_cli.py
    test_config.py
    test_models.py
    test_normalizer.py
    test_ravelry_client.py
    test_sanitizer.py
    test_scoring.py
    test_patterns.py     # Phase 6: RawPattern models, normalize_pattern, PatternSummary
    test_graph_state.py
    test_supervisor.py
    test_filters.py
    test_graph.py
    test_eval.py         # CI-safe unit tests + @pytest.mark.eval integration tests
    fixtures/
      current_user.json              # sanitized: real id, username="[REDACTED]"
      stash_list.json                # 10 representative items
      stash_detail_sample.json       # first 5 items from stash_list
      stash_list_full.json           # 1,379 items — GITIGNORED, local only
      pattern_search_free.json       # Phase 6: free-pattern search results
      pattern_search_popular.json    # Phase 6: popular-pattern search results
      pattern_detail.json            # Phase 6: batch pattern detail response
      library_search_patterns.json   # Phase 6: user library search response
      eval/                          # three golden examples + example-schema.json
```

---

## Open questions

Answered:

- ~~What is the stash list endpoint?~~ `/people/{username}/stash/list.json`
- ~~Does the stash list return skeins and fiber?~~ No — skeins=null, fiber_categories=[] in list format.
- ~~Does project creation require write permissions?~~ Yes, "Personal Account Access" app required.
- ~~Does the paginator use `pages` or `page_count`?~~ `page_count` in the real API.
- ~~What fields does the stash detail endpoint add over the list format?~~ Answered by raw capture (2026-05-14): detail adds `packs` (carries actual skein and yardage data), `photos`, `notes_html`, `yarn_weight_name`, `long_yarn_weight_name`, `personal_yarn_weight`, `user`, `user_id`. `fiber_categories` is absent in both formats. See "Critical Ravelry API discoveries" above for full breakdown. (Was question 6.)
- ~~Does the stash detail endpoint return `skeins` as a non-null value?~~ Yes, but not as a top-level field. Skein count is in `packs[n].skeins` on the primary pack (the one with `primary_pack_id: null`). It can still be null if the user has not entered a count on Ravelry. (Was question 9.)

Still open:

1. What is the exact endpoint and payload for project creation?
2. Can the API link stash items to a project directly?
3. Can start date, end date, status, and notes be set at creation time?
4. Are project notes plain text, HTML, Markdown, or Ravelry markup?
5. Are there documented rate limits?
7. Can project photos be uploaded via the API?

Answered (2026-05-16 — full API docs captured in `docs/ravelry-api/`):

6. **Pattern search vs. pattern detail fields:** `patterns/search` returns `Pattern (list)` — includes `id`, `name`, `permalink`, `free`, `designer`, `first_photo`, `personal_attributes` (queued/favorited). `patterns/show` returns `Pattern (full)` — adds `craft`, `yardage`, `yardage_max`, `yarn_weight`, `gauge`, `pdf_in_library`, `volumes_in_library`, `packs` (suggested yarns), `pattern_categories`, `download_location`. Pattern search also accepts undocumented on-site filter params: `craft`, `weight`, `availability`, `sort` (best/rating/projects).

---

## Demo guardrails

- Do not let the LLM call write tools directly.
- Use explicit tool schemas and validation.
- Add dry-run mode for every write.
- Add a `requires_approval` flag in graph state.
- Never log API keys, OAuth tokens, or personal Ravelry data.
- Use sanitized fixtures for tests and public demos.
- Do not rely on live Ravelry during demos unless you have a fallback.
- Read back any created/updated resource to verify success.

---

---

## Background: Ravelry API sources

- https://www.ravelry.com/api (requires login for full docs)
- https://www.ravelry.com/about/goodies
- Old ravelry_playground repo: https://github.com/ReneeErnst/ravelry_playground
- `pyravelry` wrapper: https://www.coultontheuer.com/pyravelry/
- Rust client (reference only): https://github.com/strickvl/ravelry-rs
