# SkeinMinder Research Notes

_Last updated: 2026-05-16_

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

### Phases 3b–8 — IN PROGRESS

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

### Two entry modes

The system supports two directions of use. Both share the same downstream filtering and recommendation logic — only the starting point differs.

**Project-first (goal-directed):** User specifies a project goal and the agent finds matching stash yarn.

```text
"I want a fall cardigan, medium difficulty, something I can finish in 6 weeks."
  -> filter stash by weight, yardage, fiber suitability
  -> rank candidates
  -> return recommendations
```

**Stash-first:** User specifies a stash item or yarn type and the agent finds fitting project archetypes.

```text
"What can I make with my 900 yards of sport weight silk?"
"Help me use up this merino worsted."
  -> locate matching stash items
  -> recommend project archetypes that fit
```

The graph state must accommodate both entry points from Phase 3 onward. The input fields `user_goal` (free-text goal) and `stash_filter` (weight, color, specific item, or yardage range) are both optional; at least one must be present.

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

The path from CLI to web is a thin layer once the graph exists: a FastAPI endpoint wraps the graph, a simple React front end handles input and card rendering. The LangGraph backend doesn't change.

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

### Phase 3b — Recommendation quality improvements

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

### Phase 3c — Code quality review

Goal: audit the full codebase for Python best practices before moving to pattern integration.

Scope:
- Move all deferred imports (inside functions) to module top level.
- Audit docstrings: all public functions, classes, and modules in both `ravelry/` and `graph/` packages.
- Remove dead code, commented-out blocks, and unreachable branches.
- Name any magic values that should be constants.
- Review test coverage: confirm all meaningful behaviour has deliberate test coverage.
- Fix anything ruff and mypy do not catch but a human reviewer would flag.

No new features. No spec needed — implement as a single PR with a checklist commit message.

### Phase 4 — Pattern integration

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
- `GET /patterns/{id}.json` — pattern detail including `yardage`, `yardage_max`, `yarn_weight`, `craft`, `pdf_in_library`.

Tasks:
- Add `RavelryClient` methods for pattern search and pattern detail.
- Add raw pattern models (`RawPattern`, `RawPatternList`) and a normalized `PatternSummary` domain model.
- Add `pattern_search` node to the graph: takes filtered stash, searches for matching patterns, returns ranked candidates.
- Update `recommend` node: prompt now asks LLM to pair yarn candidates with specific pattern candidates.
- Update `Recommendation` model: add `pattern_id: int | None`, `pattern_name: str | None`, `pattern_url: str | None`.
- Update `format_output`: show pattern title and URL alongside yarn and rationale.
- Future hook (not in scope): when `low_confidence_output` fires, offer to search for yarn to buy that would satisfy the goal.

### Phase 5 — Human approval checkpoints

Goal: demonstrate safe agentic control before any write operations.

Tasks:
- Add LangGraph interrupt/checkpoint before writes.
- Show draft payload before side effects.
- Require explicit approval to continue.
- Store graph thread state.
- Add rejection/edit path.

Note: the low-confidence interactive prompt added in Phase 3b is a lightweight precursor to this — same concept applied earlier in the graph.

### Phase 6 — Ravelry project write-back

Goal: create or update a Ravelry project from an approved recommendation.

With Phase 4 complete, write-back now has a real pattern reference to include alongside the yarn link.

Tasks:
- Add `draft_ravelry_project` and `create_ravelry_project` tools.
- Link stash yarn and pattern ID to the created project.
- Add dry-run mode.
- Add verification read-back.

API reference: `docs/ravelry-api/api-reference-skeinminder.md` covers project endpoints.

### Phase 7 — External productivity integration (tentative)

Google Calendar first (value is easy to demo). Schedule swatching and milestones.

Note: Ravelry projects support start dates natively, which may make calendar integration unnecessary. Revisit after Phase 6 before committing to Phase 7.

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
        models.py        # raw Pydantic models (RawUser, RawYarn, RawPack, RawStashItem, etc.)
        client.py        # RavelryClient (Basic Auth, retries, pagination)
        normalizer.py    # StashItem, enums, normalize_stash, scoring helpers
        sanitizer.py     # strip personal data before committing fixtures
        recorder.py      # one-shot: captures live API responses as fixtures; --raw for pre-Pydantic capture
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

## Pending housekeeping

- **Regenerate Ravelry credentials.** The API access key was exposed in a chat session. Revoke the current Personal Account Access app key and generate a new one. Update `.env` with the new credentials.
- **Merge `phase2b` to `main`.** PR pending. 73 tests passing, CI clean.

---


---

## Background: Ravelry API sources

- https://www.ravelry.com/api (requires login for full docs)
- https://www.ravelry.com/about/goodies
- Old ravelry_playground repo: https://github.com/ReneeErnst/ravelry_playground
- `pyravelry` wrapper: https://www.coultontheuer.com/pyravelry/
- Rust client (reference only): https://github.com/strickvl/ravelry-rs
