# SkeinMinder Research Notes

_Last updated: 2026-05-12_

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
    stash_list.json          # 10 representative items (trimmed from 1,379)
    stash_detail_sample.json # first 5 items from stash_list, same shape
    stash_list_full.json     # all 1,379 items — GITIGNORED, local only
```

**Raw Pydantic models** (`models.py`, all use `extra="ignore"`):

- `RawFiberCategory` — id, name
- `RawYarnWeight` — id, name
- `RawYarn` — id, name, yarn_company_name, yarn_weight, grams (float|None), yardage (float|None), fiber_categories
- `RawStashStatus` — id, name
- `RawStashItem` — id, permalink, colorway_name, stash_status, skeins (float|None), notes, yarn_name, yarn, color_family_name
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
    LACE / COBWEB / THREAD / LIGHT_FINGERING / FINGERING /
    SPORT / DK / WORSTED / ARAN / BULKY / SUPER_BULKY / UNKNOWN

class ProjectQuantity(str, Enum):
    SWEATER    # 800+ yards
    ACCESSORY  # 200–799 yards
    SCRAP      # < 200 yards

class MatchScore(str, Enum):
    EXACT / ADJACENT / INCOMPATIBLE / UNKNOWN

@dataclass
class StashItem:
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

**Key normalizer behaviors:**

- `normalize_stash_item(raw)`: raises `NormalizationError` if yarn is None or yarn.yardage is None. If `skeins` is None (common in the list endpoint response), defaults to 1.0.
- `normalize_stash(raw_items)`: calls normalize_stash_item for each item; silently skips items that raise NormalizationError (logs at DEBUG). Returns only items that could be fully normalized.
- `yardage_buffer(stash_yards, pattern_yards) -> float`: ratio of extra yardage. E.g., 0.15 means 15% buffer.
- `weight_match(stash_weight, pattern_weight) -> MatchScore`: EXACT, ADJACENT (one step away in weight order), or INCOMPATIBLE.
- `fiber_suitability(fiber_list, garment_type) -> MatchScore`: based on known fiber/garment rules.

### Phases 3–8 — NOT YET STARTED

Next up is Phase 3: first LangGraph MVP. See the implementation plan below.

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

**Real stash scale:**

The demo user has 1,379 stash items. This is much larger than average and useful for stress-testing the agent design. The committed fixture is trimmed to 10 items (one per weight category, varied statuses). The full 1,379-item file is at `tests/fixtures/stash_list_full.json` (gitignored, local only).

Fixture item breakdown:
- 9 items successfully normalize (have linked yarn with yardage)
- 1 item has no yarn link and is silently skipped by `normalize_stash`
- Sweater-quantity items (800+ yds): currently 1 (Lace/990 yds). More will be needed for a compelling agent demo — pull from `stash_list_full.json` when building Phase 3.

---

## LangGraph fit

LangGraph is a good fit because the project needs state, routing, persistence, and human-in-the-loop control. The LangGraph persistence docs say checkpointing enables human-in-the-loop workflows, memory, time travel, and fault-tolerant execution. This is directly relevant for pausing before writing to Ravelry, Notion, Google Calendar, or Google Drive.

---

## Product concept

### Core workflow

User asks:

```text
Help me choose a fall cardigan project using yarn from my Ravelry stash.
Prioritize stash yarn, medium difficulty, and something I can realistically finish in 6 weeks.
```

System flow:

```text
User goal
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

### Phase 3 — First LangGraph MVP (NEXT)

Goal: build the simplest useful graph.

Workflow:

```text
User goal -> Read stash -> Normalize stash -> Filter to available sweater-qty items
         -> Recommend project archetypes -> Return ranked options
```

Tasks:

- Define graph state (TypedDict with stash items, user goal, recommendations, requires_approval flag).
- Add Supervisor node.
- Add Stash node (calls `RavelryClient` or loads fixture).
- Add Recommendation node (LLM call with filtered stash context).
- Add final response formatter.
- Add LangSmith tracing if available.
- Wire `--fixture` flag to graph (demo mode without live API).

Notes for next session:

- LangGraph requires `langgraph`, `langchain-anthropic` (or equivalent) as dependencies. Add to `pyproject.toml`.
- Use `claude-sonnet-4-6` (model ID: `claude-sonnet-4-6`) or `claude-haiku-4-5-20251001` for cost. The most capable current model is `claude-opus-4-7`.
- Stash filtering before the LLM node is critical — see context window constraint above.
- The `--fixture` CLI flag pattern is already established in `cli.py`; extend it to the graph.

Exit criteria:

- User can ask "What can I make from my stash?"
- System returns 3 recommendations with structured rationale and risks.

### Phase 4 — Pattern search and candidate matching

Goal: use real pattern data when available.

Tasks:

- Verify Ravelry pattern search endpoint schema (needs logged-in API docs review).
- Add `PatternScoutAgent`.
- Match pattern requirements to stash yarn using scoring helpers.
- Add fallback mode for unavailable API fields.
- Rank candidates by stash fit, yardage risk, difficulty fit, and project type.

### Phase 5 — Human approval checkpoints

Goal: demonstrate safe agentic control.

Tasks:

- Add LangGraph interrupt/checkpoint before writes.
- Show draft payload before side effects.
- Require explicit approval to continue.
- Store graph thread state.
- Add rejection/edit path.

### Phase 6 — Ravelry project write-back

Goal: create or update a Ravelry project.

Tasks:

- Verify official project create/update endpoints and payloads (logged-in docs).
- Add `draft_ravelry_project` and `create_ravelry_project` tools.
- Add dry-run mode.
- Add verification read-back.

### Phase 7 — External productivity integration

Google Calendar first (value is easy to demo). Schedule swatching and milestones. Optional: Notion project dashboard, Google Drive project brief.

### Phase 8 — Demo polish

Deterministic demo data, fixture mode toggle, sample prompt scripts, screenshots/GIFs, architecture diagram, known-limitations section.

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
  .env.example         # RAVELRY_USERNAME and RAVELRY_PASSWORD stubs
  .env                 # GITIGNORED — personal credentials
  .pre-commit-config.yaml
  .github/workflows/ci.yml
  src/
    skeinminder/
      __init__.py
      config.py          # ConfigError, get_ravelry_credentials, RAVELRY_BASE_URL
      cli.py             # click group + stash command with --fixture flag
      ravelry/
        __init__.py
        exceptions.py    # RavelryError hierarchy + NormalizationError
        models.py        # raw Pydantic models (RawUser, RawYarn, RawStashItem, etc.)
        client.py        # RavelryClient (Basic Auth, retries, pagination)
        normalizer.py    # StashItem, enums, normalize_stash, scoring helpers
        sanitizer.py     # strip personal data before committing fixtures
        recorder.py      # one-shot: captures live API responses as fixtures
  tests/
    __init__.py
    conftest.py          # FixtureTransport + fixture_client / fixture_transport fixtures
    test_cli.py
    test_config.py
    test_models.py
    test_normalizer.py
    test_ravelry_client.py
    test_sanitizer.py
    test_scoring.py
    test_placeholder.py  # empty, keeps pytest happy before real tests exist
    fixtures/
      current_user.json        # sanitized: real id, username="[REDACTED]"
      stash_list.json          # 10 representative items (trimmed from full stash)
      stash_detail_sample.json # first 5 items from stash_list
      stash_list_full.json     # 1,379 items — GITIGNORED, local only
```

---

## Open questions

Answered:

- ~~What is the stash list endpoint?~~ `/people/{username}/stash/list.json`
- ~~Does the stash list return skeins and fiber?~~ No — skeins=null, fiber_categories=[] in list format.
- ~~Does project creation require write permissions?~~ Yes, "Personal Account Access" app required.
- ~~Does the paginator use `pages` or `page_count`?~~ `page_count` in the real API.

Still open (need logged-in Ravelry API docs):

1. What is the exact endpoint and payload for project creation?
2. Can the API link stash items to a project directly?
3. Can start date, end date, status, and notes be set at creation time?
4. Are project notes plain text, HTML, Markdown, or Ravelry markup?
5. Are there documented rate limits?
6. What fields does the stash detail endpoint add over the list format? (Likely: skeins, fiber_categories, notes, photos.)
7. What fields are available in pattern search vs. pattern detail?
8. Can project photos be uploaded via the API?

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

## Pending housekeeping

- **Regenerate Ravelry credentials.** The API access key was exposed in a chat session. Revoke the current Personal Account Access app key and generate a new one. Update `.env` with the new credentials.
- The `project-init` branch has not been merged to `main` yet. All work is on this branch.

---


---

## Background: Ravelry API sources

- https://www.ravelry.com/api (requires login for full docs)
- https://www.ravelry.com/about/goodies
- Old ravelry_playground repo: https://github.com/ReneeErnst/ravelry_playground
- `pyravelry` wrapper: https://www.coultontheuer.com/pyravelry/
- Rust client (reference only): https://github.com/strickvl/ravelry-rs
