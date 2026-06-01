# SkeinMinder Research Notes

_Last updated: 2026-05-31_

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
Cauldron notebooks, BigQuery, and GCS.

## Implementation status

### Phases 0–8 ✅ ALL COMPLETE (merged to main, 211 tests passing)

- **Phase 0**: Project setup — Python 3.13, uv, ruff, mypy strict, pytest, CI.
- **Phase 1**: Ravelry read-only client — `RavelryClient` with Basic Auth/retry/pagination, raw Pydantic models, `FixtureTransport`, `skeinminder stash` CLI.
- **Phase 2**: Stash normalization — `StashItem`, `WeightCategory`, `ProjectQuantity`, scoring helpers (`yardage_buffer`, `weight_match`, `fiber_suitability`). Weight-adjusted sweater yardage thresholds.
- **Phase 2b**: API investigation — skeins field resolved (lives in `packs[n].skeins` on detail endpoint only), weight-adjusted thresholds, raw fixture capture mode.
- **Phase 3**: First LangGraph MVP — `supervisor`, `project_first_filter`, `stash_first_filter`, `recommend`, `format_output`, `skeinminder recommend` CLI.
- **Phase 3b**: Recommendation quality — weaving yarn exclusion (`is_weaving_yarn` heuristic), sweater quantity gate, fiber suitability filtering, low-confidence path (`assess_filter_quality` + `low_confidence_output`).
- **Phase 3c**: Code quality — deferred imports lifted, docstrings added, dead code removed, magic values named.
- **Phase 4**: Observability — self-hosted Langfuse via Docker Compose, `@observe` decorators on all nodes, eval dataset scaffold.
- **Phase 5**: Evaluation — two-layer eval suite (deterministic assertions + LLM-as-judge), `skeinminder eval` CLI, 3 golden examples, `setup_langfuse_dataset.py`.
- **Phase 5b**: Observability improvements — token cost tracking fixed (`as_type="generation"`, `include_raw=True`), stash truncated from spans, test traces suppressed via autouse fixture, Anthropic model pricing registered in Langfuse.
- **Phase 6a**: Pattern data layer — `patterns.py` (`RawPattern`, `PatternSummary`, `normalize_pattern`), `FixtureTransport` extended for pattern endpoints, four pattern fixture files.
- **Phase 6b**: Pattern graph integration — `pattern_search` node (deterministic, graceful), `pattern_candidates` in `GraphState`, pattern-aware `recommend` and `format_output`.
- **Phase 7**: Web UI — FastAPI + SSE backend, vis-network graph animation, recommendation cards with pattern photos, `skeinminder web` CLI. `POST /approve` and `POST /cancel` are Phase 11 stubs.
- **Phase 8**: Stash date filtering — `created_at` surfaced from Ravelry, `added_date` on `StashItem`, `oldest_first` sort order, temporal keyword detection in supervisor (`_TEMPORAL_TRIGGERS`).

---

**Demo completion order.** To reach a strong live demo for a technical audience:

1. **Phase 9** — pattern search quality (live runs currently return no pattern matches; most visible gap)
2. **Phase 10a** — interrupt migration (`click.confirm` hangs the web UI — hard blocker; also wires MemorySaver)
3. **Phase 10b** — streaming + polish (LLM streaming, mode echo, graph pre-compilation, TTL eviction)
4. **Phase 11** — human approval (the product's core safety claim is today a stub)
5. **Phase 13** — eval depth (a failing golden example with a Langfuse trace is stronger demo material)

Phases 12 and 14–19 strengthen the product but are not required for a compelling technical demo.

---

### Phase 9 — Pattern search: category filtering and weight targeting

Goal: make pattern recommendations consistently appear in live runs by fixing the `pattern_search` node to use Ravelry's category taxonomy instead of free-text search, and correcting weight selection and candidate pre-filtering.

Background: live testing showed a fingering-weight stash run returning 10 pattern candidates — all non-sweater garment types — and the LLM correctly declining to match any of them. Root cause: the search passes the full goal text as the free-text query with no category filter. `GET /pattern_categories/list.json` confirms a `pc=<permalink>` filter parameter exists (e.g., `pc=cardigan`, `pc=hat`, `pc=shawl-wrap`). See improvement backlog item 3 for the full keyword→permalink mapping and confirmed category IDs.

Tasks:
- Expand `_extract_garment_type` to cover the full common-knitting vocabulary — hat, sock, shawl, cowl, scarf, mittens, gloves, fingerless, slippers, headband, earwarmers, blanket, bag, tote, shrug, dress, and their common synonyms. Currently limited to 6 sweater-scale terms.
- Return the Ravelry category permalink from the function (or add a parallel `_GARMENT_TO_PC` dict mapping the extracted keyword to its permalink). The permalink is what gets passed to the API.
- In `pattern_search`, pass `pc=<permalink>` to `search_patterns` when a garment category is detected; fall back to free-text `query` with the goal string when no category is found (covers vague inputs like "something cozy" or "a gift").
- Fix weight selection priority: (1) weight keyword found in the user's goal text via `find_weight_in_text`, (2) modal weight across filtered stash items, (3) heaviest-yardage item's weight (current behavior). This prevents the search from targeting the wrong weight when the stash spans multiple categories.
- Pre-filter `pattern_candidates` to exclude patterns whose `weight_name` is more than one adjacent step from the dominant stash weight before writing to state. Library patterns span all weights and currently consume slots in the 10-candidate cap that belong to weight-matched patterns.

Tests:
- Parametrized unit tests for the expanded keyword → permalink mapping (one test per garment family is enough — not every synonym needs its own case).
- Update `pattern_search` fixture tests to pass `pc` in the mock call assertions.
- Tests for the weight selection priority fix (goal weight takes precedence over stash modal weight).
- Tests for the weight-adjacency pre-filter (out-of-range patterns are excluded; adjacent-weight patterns are kept).

---

### Phase 10a — Interrupt migration + checkpointer

Goal: unblock the web UI on the low-confidence path, and lay the MemorySaver foundation Phase 11 depends on. This is the hard blocker; nothing in 10b or 11 can proceed until this is done.

`low_confidence_output` uses `click.confirm()` — a blocking terminal call that is incompatible with the web UI and prevents clean testing of the low-confidence graph path. Migrating to LangGraph's `interrupt()` mechanism also requires wiring a `MemorySaver` checkpointer into `build_graph()`, which Phase 11 needs anyway.

Tasks:
- Replace `click.confirm()` in `low_confidence_output` with `interrupt()`. The interrupt value should include the low-confidence summary (what was found, candidate count) so the web UI can render a meaningful prompt rather than a generic pause.
- Wire `MemorySaver` checkpointer into `build_graph()`; propagate `thread_id` through the CLI (`skeinminder recommend`) and web server (`POST /recommend` → `GET /stream/{id}`).
- Wire the existing `/approve/{id}` stub to resume the paused thread via `graph.astream(Command(resume=True), config={"configurable": {"thread_id": id}})`. Wire `/cancel/{id}` to abort and clear the thread.
- Update tests for the interrupt-based low-confidence path — both the approve (graph continues to `recommend`) and cancel (graph exits to `END`) paths.

---

### Phase 10b — Streaming + server polish

Goal: visible LLM progress during the 2–5 second `recommend` wait, plus three small server improvements that are cleaner to do together. None of these block the demo, but streaming is the highest-impact UX win relative to effort.

Tasks:
- Add streaming to `recommend` node; emit SSE token events so the frontend shows incremental LLM output. The SSE infrastructure in `events.py` already carries the result payload — the change is in how `recommend` produces tokens, not how the frontend receives them.
- Echo the detected mode in the web UI before the graph continues (e.g., "Running in stash-first mode…"). One sentence of feedback that makes silent supervisor misclassification visible.
- Compile the LangGraph graph once at server startup rather than per-request. `stream_graph_events()` currently calls `build_graph()` on every SSE request; move compilation into `create_app()` and pass the compiled graph through.
- Wire TTL-based eviction for `_streams` — this is a memory leak, not cleanup. Store a creation timestamp alongside each queue; a lightweight `asyncio` background task sweeps entries older than ~5 minutes.

---

### Phase 11 — Human approval checkpoint

Goal: demonstrate safe agentic control — the centerpiece feature for a technically demanding audience. Surfaces the interrupt/resume pattern applied to a meaningful decision point: the user sees a draft project plan and explicitly approves before anything is written.

Phase 10a lays the required groundwork (MemorySaver checkpointer, thread_id propagation). Phase 11 applies the same interrupt pattern to the recommendation approval gate.

**What is being approved:** After `format_output` produces recommendations, the graph pauses and presents a draft plan: the recommended yarn(s), pattern name and URL, a suggested Ravelry project title, and proposed notes. The user approves to proceed to write-back (Phase 12) or cancels. The Phase 7 approval modal in the web UI is already built for this.

Tasks:
- Add an `await_approval` node that fires after `format_output` and calls `interrupt()` with the draft plan payload. `GraphState` gains `approved: bool = False`; downstream write nodes (Phase 12) check this before executing.
- The draft payload passed to `interrupt()` should include: `yarn_names`, `pattern_name`, `pattern_url`, `suggested_project_title`, `proposed_notes`. This is what the approval modal renders.
- Wire `/approve/{id}` to resume the thread (`Command(resume=True)`). Wire `/cancel/{id}` to abort and clear the thread state from `MemorySaver`. Both should emit a corresponding SSE event (`approved` / `cancelled`) so the frontend can transition out of the approval state.
- Rejection path: on cancel, the graph exits to `END`. No restart or re-run logic needed yet — the user can submit a new request from the input screen.
- Add tests: approval happy path (graph resumes from the approval interrupt), cancellation path (graph exits cleanly), unknown thread_id → 404.

**Note on checkpointer scope:** `MemorySaver` is in-process and sufficient for demo. For multi-user deployment, `PostgresSaver` is required (graph pauses can span requests, server may restart). The switch from `MemorySaver` to `PostgresSaver` is a Phase 19 concern — wire the interface cleanly in Phase 10a so Phase 19 is a configuration change, not a refactor.

---

### Phase 12 — Ravelry project write-back

_Depends on Phase 11 (approval gate). Demo path: defer until after Phase 13._

Goal: create or update a Ravelry project from an approved recommendation, completing the first end-to-end write loop. With Phase 6 complete, write-back now has a real pattern reference to include alongside the yarn link.

**Prerequisite:** Open questions 1–4 (project creation endpoint, payload shape, stash linking, date fields, notes format) are all unanswered. API exploration must be the first task of this phase — use `recorder.py` or the Ravelry API docs in `docs/ravelry-api/` to answer them before writing any tools.

Tasks:
- Explore and document the project creation endpoint: exact path, required fields, response shape, error codes. Answer open questions 1–4 and update the open questions section.
- Add `draft_ravelry_project` (deterministic: builds payload from `Recommendation`, validates fields, returns dry-run summary) and `create_ravelry_project` (executes the API write) tools.
- Link stash yarn and pattern ID to the created project, if the API supports it (open question 2).
- Add dry-run mode: `create_ravelry_project` accepts a `dry_run: bool` flag; when True, logs the payload but makes no API call. Required for testing and demos without side effects.
- Add verification read-back: after creation, call the project detail endpoint and confirm key fields match what was written.

API reference: `docs/ravelry-api/api-reference-skeinminder.md` covers project endpoints.

---

### Phase 13 — Eval depth pass

Goal: strengthen the eval suite for a technically demanding audience. Walking through a failing example — and showing how the Langfuse trace illuminates the failure — is a stronger demo than three examples that all score well.

Tasks:
- Add one failing or edge-case golden example: an input that fails a deterministic assertion (e.g., hallucinated stash ID) or scores below threshold on the LLM-as-judge. Document why it fails and what the graph state shows.
- Add a third judge dimension: **pattern relevance**. Now that Phase 6 ships real pattern links, the judge can score whether the recommended pattern is a plausible fit for the stash yarn, not just whether the reasoning is coherent.
- Verify the Langfuse dashboard is demo-ready: a recent run logged with visible token counts, cost per run, and judge scores on all three dimensions. Run `skeinminder eval` against live fixtures before the interview.
- Confirm prompt caching is working: a second identical run should show `cache_read_input_tokens` in the `recommend` node's Langfuse span.

---

### Phase 14a — UX wizard backend + Mode 2

_Product UX improvement — deprioritized in favor of Phase 11 before the interview. Resume after Phase 13._

Goal: wire the backend for the three-mode wizard and add the Mode 2 frontend form. Mode 2 is a minimal frontend change (label update on the existing text box); the real work is adding the backend endpoints and supervisor bypass that both Mode 2 and Mode 3 depend on.

Backend tasks:
- `GET /stash` endpoint: returns normalized stash as a lightweight list (`{stash_id, brand, yarn_name, colorway, weight_category, yards_total}`) for client-side search by Mode 3.
- `POST /recommend` body gains `mode: Literal["project_first", "stash_first"] | None` and `stash_id: int | None`. When provided, these are injected into the initial `GraphState` before the graph runs.
- `supervisor` node: if `state["mode"]` is already set, skip mode classification but still run temporal keyword extraction (`oldest_first` detection). Only the routing decision is bypassed — filter enrichment still applies.

Frontend tasks:
- Add `phase-mode` screen before `phase-input`: three option cards (Mode 1 visible but disabled with "Coming soon" label, Modes 2 and 3 selectable).
- Mode 2 form: existing text box with updated label and placeholder. No behavior change.
- Mode card styles in `style.css`.

---

### Phase 14b — Mode 3 yarn search UI

Goal: implement the "Use a specific yarn" flow — the most complex of the three modes. The backend from Phase 14a is a dependency; this phase is entirely frontend and pre-graph disambiguation.

**Mode 3 — "Use a specific yarn":** Step 2 shows a yarn search field. As the user types, results filter against the `/stash` data fetched in Phase 14a. The user confirms a match, then the graph runs with `specific_stash_id` pre-set — supervisor skips classification, `recommend` receives a 1-item filtered stash.

Frontend tasks:
- On `phase-mode` → Mode 3 selection, fetch `/stash` and hold it in memory.
- Render a search input that filters client-side against `yarn_name`, `brand`, and `colorway` as the user types (debounced, no additional API calls).
- Render a result list with yarn name, brand, colorway, weight, and yardage. Selecting an item shows a confirmation step before enabling the submit button.
- Fallback: if the user clears the search or hits submit with no selection, fall through to a free-text description box (supervisor runs as today's stash-first path).
- On submit with a confirmed yarn: include `stash_id` and `mode="stash_first"` in the `POST /recommend` body.

Edge cases:
- Yarn not found in stash (empty search results): show "No matches — describe what you'd like to make instead" and render the fallback text box.
- Stash fetch fails: show an error and fall through to the text box gracefully. Never block the user from making a recommendation.

---

### Phase 15 — Allow Purchase Mode (Mode 1)

_Depends on Phase 14b (Mode 3 UI). The backend changes in Phase 14a are sufficient to implement allow_purchase; Phase 14b is needed so Mode 1 has a wizard card to enable._

Goal: implement the "open to buying yarn" mode, completing the three-mode wizard. The LLM can recommend projects that require purchasing yarn, while still prioritizing stash matches when available.

Backend changes:
- `allow_purchase: bool` added to `GraphState` (default `False`).
- `POST /recommend` body gains `allow_purchase: bool`; set to `True` for Mode 1.
- `recommend` prompt: when `allow_purchase=True`, the stash-only constraint is lifted. The prompt adds: "If no stash yarn is a good fit, you may suggest that the user purchase yarn for this project. Populate `purchase_suggestion` with a brief description of what to look for (weight, fiber, yardage)."
- `Recommendation` model: add `purchase_suggestion: str | None = None`.
- `format_output` and `_build_result_payload`: render `purchase_suggestion` when set.

**Key distinction from Mode 2:** Mode 2 recommendations always reference a stash yarn. Mode 1 recommendations may include a `purchase_suggestion` instead of or alongside `yarn_candidate_ids` when no stash yarn is a good fit.

---

## Improvement backlog

These are known quality gaps that don't fit a specific upcoming phase. Items can be tackled opportunistically — folded into any PR that touches the relevant code — or promoted to a named phase when prioritized. Items 5 and 6 are trivially small and should be done in the next PR that touches those files.

_Streaming, interrupt migration, stream TTL eviction, and mode echo-back were pulled forward to Phases 10a/10b. Parallelism, async pagination, and caching are deferred to the production milestone._

**1. Richer filter quality signals**

`assess_filter_quality` checks only two conditions: empty filtered stash, or sweater goal with <500 yards. Additional signals worth adding:

- All candidates are the same fiber (a mono-fiber result is suspicious for a 1,300-item stash)
- No candidates match the fiber suitability score for the goal garment type (all MISMATCH)
- Pattern candidates found but no stash yarn within one weight step of any pattern's required weight

**2. Supervisor robustness**

The `supervisor` node classifies input using hardcoded phrase-matching. Natural-language inputs outside this vocabulary are silently misclassified.

Recommended path, in order of complexity:

1. Expand the keyword set with common paraphrases ("i've got some", "there's yarn in my stash", "i want to use"). Handles the majority of real inputs at zero latency cost — do this first regardless.
2. Add a sentence-transformer embedding classifier (e.g., `all-MiniLM-L6-v2`, ~80MB) as a fallback when no keyword matches. Computes cosine similarity against prototype sentences per class. Runs in ~10–30ms on CPU.

Mode echo-back (let the user see and correct the detected mode) was pulled forward to Phase 10b.

A full generative LLM call for binary intent detection (~200–400ms API round-trip) is disproportionate. Defer option 2 until keyword expansion is in place and still producing visible misclassifications.

**3. `pattern_search` — category-based filtering and candidate pre-filtering**

Two related problems that together cause pattern fields to be null even when the LLM has good yarn candidates. Full implementation notes are in Phase 9. Key permalink mapping (from the live category tree, confirmed 2026-05-31):

| User term(s) | Ravelry permalink | Category ID |
|---|---|---|
| cardigan | cardigan | 304 |
| pullover, jumper | pullover | 306 |
| sweater (generic) | sweater | 319 |
| vest | vest | 310 |
| coat, jacket | coat | 311 |
| shrug, bolero | shrug | 305 |
| hat, beanie, toque | hat | 411 |
| beret, tam | beret-tam | 412 |
| brimmed hat | brimmed | 415 |
| earflap hat | earflap | 419 |
| scarf | scarf | 339 |
| cowl | cowl | 340 |
| shawl, wrap | shawl-wrap | 350 |
| poncho | poncho | 349 |
| cape | cape | 348 |
| mittens | mittens | 391 |
| gloves | gloves | 394 |
| fingerless | fingerless | 395 |
| socks, sock | socks | 354 |
| slippers | slippers | 363 |
| legwarmers | legwarmers | 365 |
| headband | headband | 403 |
| earwarmers | earwarmers | 409 |
| blanket, throw | blanket | 450 |
| bag | bag | 372 |
| tote | tote | 374 |
| dress | dress | 325 |
| skirt | skirt | 313 |
| top | tops | 912 |

When no garment type is detected, omit `pc` and fall back to free-text `query` — this handles vague inputs ("something cozy", "a gift") acceptably.

**Weight selection priority.** Better than current (heaviest-yardage item): (1) weight keyword in the user's goal, (2) modal weight across filtered items, (3) heaviest-yardage item's weight.

**Candidate pre-filtering.** Keep only patterns whose `weight_name` is within one step of the dominant stash weight before the LLM sees them.

**4. Stash/yarn photos in result cards**

Result cards show no image when no pattern is matched, even though Ravelry stash entries have photos. The stash list endpoint returns `first_photo` on the yarn object. Implementation path: expose `first_photo` on `RawYarn`, carry it through `StashItem` → `_build_result_payload`, and render it as a fallback `<img>` in `_renderCards` when `photo_url` is null.

**5. Hallucinated stash IDs fail silently** _(trivial — do in next PR touching `format_output`)_

`format_output` calls `stash_by_id.get(sid)` and silently drops any ID the LLM invented. The eval suite catches this in tests, but production runs have no signal. Add `_logger.warning("LLM returned stash ID %d not in filtered_stash", sid)` — one line, materially improves debuggability.

**6. `LAST_RUN_PATH` is a process-relative path** _(trivial — do in next PR touching `events.py`)_

`LAST_RUN_PATH = Path("last_run.json")` resolves against whatever directory `uvicorn` starts in. Pin it relative to `__file__` or make it configurable via env var. Low priority until the production milestone replaces it with a proper result store, but trivial to harden now.

---

### Phase 17 — External productivity integration (tentative)

Google Calendar first (value is easy to demo). Schedule swatching and milestones.

Note: Ravelry projects support start dates natively, which may make calendar integration unnecessary. Revisit after Phase 12 (Ravelry write-back) before committing to this phase.

### Phase 18 — Documentation polish

Screenshots/GIFs for the README, architecture diagram, sample prompt scripts, known-limitations section.

---

## Production milestone (post-demo)

_Not a single phase — this is a multi-sprint initiative to make SkeinMinder safe to deploy for more than one user. Break it into sub-phases when you approach it. Phase 11's checkpointer decision directly shapes the persistence choices here, so Phase 11 should be complete before starting._

Sub-phases when ready:
- **Caching**: per-user normalized stash cache (TTL ~15 min, Redis for multi-process); shared pattern search cache keyed by `(weight, query)`.
- **Auth/session**: per-request Ravelry credentials via OAuth or equivalent; `create_app()` no longer takes a single `stash` argument.
- **Persistence**: replace `last_run.json` with a `runs` table (Postgres, keyed by `user_id + run_id`); switch LangGraph checkpointer from `MemorySaver` to `PostgresSaver`.
- **Async/parallelism**: LangGraph fan-out so `pattern_search` and stash filtering run concurrently after `supervisor`; async Ravelry pagination via `httpx.AsyncClient` + `asyncio.gather()`.
- **Rate limiting**: per-user middleware before Ravelry enforces it; Ravelry rate limits are undocumented (open question 5) so test empirically first.

Minimum infrastructure additions: Redis, Postgres schema extensions, session/auth layer. The existing Docker Compose Postgres instance can host LangGraph checkpointer tables in a separate schema.

---

## Critical Ravelry API discoveries

These were found through live testing and should save time in future sessions.

**Authentication:**

- Use "Personal Account Access" app type (not "Read Only"). The stash endpoint requires write-level auth even for reads. A read-only app returns: `403 Forbidden. This is not a read only API method.`
- Basic Auth: `RAVELRY_USERNAME` = access key (alphanumeric API key), `RAVELRY_PASSWORD` = personal key. These are NOT the Ravelry login credentials.

**Pattern category endpoint (confirmed 2026-05-31):**

`GET /pattern_categories/list.json` returns the full Ravelry category tree — nested objects with `id`, `name`, `long_name`, `permalink`, and `children`. No auth required beyond Basic Auth. The `patterns/search` endpoint accepts `pc=<permalink>` to filter by category. See improvement backlog item 3 for the full mapping.

**Endpoint corrections (verified against official docs):**

| Endpoint | Correct path |
|---|---|
| Current user | `GET /current_user.json` |
| Stash list | `GET /people/{username}/stash/list.json` |
| Stash detail | `GET /people/{username}/stash/{id}.json` |

Note: the username in these URLs is the Ravelry display username (e.g., "KnittingBunnyMom"), NOT the API access key. Always call `get_current_user()` first to get the correct username from `user.username`.

**Paginator field name:** The real API returns `page_count` (not `pages`). `RawPaginator.pages` uses `AliasChoices("pages", "page_count")` to accept both.

**Stash list endpoint ("small" format):**

- Returns `skeins=null` for all items — skein count is not populated in the list response.
- Returns `yarn.yardage` and `yarn.yarn_weight` reliably for items with linked yarn.
- Returns empty `fiber_categories=[]` for all items — fiber data is not in the list format.
- `yarn_name` is null for all items; use `yarn.name` as fallback.
- Items without a linked yarn (`yarn=null`) cannot be normalized for yardage.

**Stash detail endpoint:**

- Skein count lives in `packs`, not the stash item directly. Each pack has `skeins` (float|null). The primary pack (`primary_pack_id: null`) is authoritative. `skeins` can still be null if the user hasn't entered a count on Ravelry.
- The packs structure always has two entries per stash item: a primary pack and a secondary UI-layer duplicate — only the primary pack should be used for quantity calculations.
- `fiber_categories` is absent in both list and detail formats. Fiber requires a separate yarn detail request.
- `created_at` is present in both formats. Format: `"YYYY/MM/DD HH:MM:SS ±HH:MM"`. Used for age-based sorting (Phase 8).
- `updated_at` is present in both formats; same format. Lower priority than `created_at`.

**Real stash scale:** The demo user has 1,379 stash items. Of those, 1,313 normalize successfully; 66 have no linked yarn and are silently skipped. With 1,379 items, even a compact normalized representation would overflow the LLM context window — the filtering architecture is a real design constraint that makes the story stronger.

---

## API discrepancies (to report to Ravelry)

- **`skeins` field on stash item**: The Ravelry API documentation describes `skeins` as a top-level field on a stash item. In observed behavior, `skeins` is null on all stash items in both the list and detail endpoints. The actual skein count is nested inside the `packs` array on the detail endpoint (`packs[n].skeins`), not at the stash-item level.

- **`fiber_categories` field on stash item**: The list endpoint returns `fiber_categories: []` (empty array) for all items even when yarn has known fiber content. The detail endpoint does not return `fiber_categories` at all. Fiber data must be fetched via a separate yarn detail request.

---

## LangGraph fit

LangGraph is a good fit because the project needs state, routing, persistence, and human-in-the-loop control. The LangGraph persistence docs say checkpointing enables human-in-the-loop workflows, memory, time travel, and fault-tolerant execution. This is directly relevant for pausing before writing to Ravelry, Notion, Google Calendar, or Google Drive.

---

## Product concept

### Three entry modes

All three modes share the same downstream filtering and recommendation logic — only the starting point and purchasing constraint differ.

**Mode 1 — Open ("I want to make something new"):** User describes a project goal; recommendations use stash yarn where available but may suggest purchasing yarn if no stash item fits. Implemented in Phase 15.

**Mode 2 — Stash-constrained ("I want to make something with my stash"):** User describes a project goal; recommendations are constrained to stash yarn only. Equivalent to the original project-first behavior. Implemented in Phase 14.

**Mode 3 — Yarn-specific ("I want to use a specific yarn"):** User identifies a yarn from their stash; the agent finds fitting project archetypes for that yarn. Pre-graph disambiguation means the graph gets a single confirmed stash item rather than a filtered list — smaller LLM context, faster response. Implemented in Phase 14.

The graph state accommodates all three entry points. `user_goal` (free-text goal) and `stash_filter` (weight, color, specific item, or yardage range) are both optional; at least one must be present. `allow_purchase` (Phase 15) controls whether Mode 1's looser constraint is active.

### Core workflow

```text
User goal / stash filter
  -> Supervisor Agent
  -> Stash filter (project_first or stash_first)
  -> assess_filter_quality
  -> pattern_search
  -> recommend
  -> format_output
  -> Human Approval Gate (Phase 11)
  -> Ravelry Project Creator (Phase 12)
```

---

## Agent architecture (current nodes)

- **supervisor**: classifies input into `project_first` or `stash_first` mode; extracts weight/yardage into `StashFilter`; detects temporal phrases and sets `oldest_first`; respects pre-set `mode` in `GraphState` (skips classification, still runs filter extraction).
- **project_first_filter / stash_first_filter**: filter `normalized_stash` down to ≤20 candidates; sort by `added_date` ascending when `oldest_first=True`, otherwise by `yards_total` descending.
- **assess_filter_quality**: sets `filter_confidence` to `"high"` or `"low"`; routes to `pattern_search` or `low_confidence_output`.
- **low_confidence_output**: warns user about low-quality filter results; currently uses `click.confirm()` — migrates to `interrupt()` in Phase 10a.
- **pattern_search**: deterministic node, four Ravelry API calls (library IDs, free search, popular search, batch detail), each independently graceful. Writes `pattern_candidates` sorted library→free→popular, capped at 10.
- **recommend**: calls the LLM with system-prompt-cached prompt; conditionally includes pattern list and pairing rule. Returns up to 3 `Recommendation` objects via structured output.
- **format_output**: renders recommendations as a plain-text CLI report. Renders `Pattern: <name> — <url>` when pattern fields are set. Groups same-yarn skeins into one line; deduplicates yarn names.

Future nodes (Phases 11–12): approval gate, Ravelry project creator, verification agent.

---

## Open questions

Answered:

- ~~What is the stash list endpoint?~~ `/people/{username}/stash/list.json`
- ~~Does the stash list return skeins and fiber?~~ No — skeins=null, fiber_categories=[] in list format.
- ~~Does project creation require write permissions?~~ Yes, "Personal Account Access" app required.
- ~~Does the paginator use `pages` or `page_count`?~~ `page_count` in the real API.
- ~~What fields does the stash detail endpoint add?~~ Detail adds `packs` (carries actual skein and yardage data), `photos`, `notes_html`, `yarn_weight_name`, `long_yarn_weight_name`, `personal_yarn_weight`, `user`, `user_id`. `fiber_categories` is absent in both formats.
- ~~Does the stash detail endpoint return `skeins` as non-null?~~ Yes, but in `packs[n].skeins` on the primary pack. Can still be null if the user has not entered a count.
- ~~Pattern search vs. pattern detail fields?~~ `patterns/search` returns `Pattern (list)` — id, name, permalink, free, designer, first_photo. `patterns/show` returns `Pattern (full)` — adds craft, yardage, yardage_max, yarn_weight, gauge, pdf_in_library, packs (suggested yarns), pattern_categories, download_location.

Still open:

1. What is the exact endpoint and payload for project creation?
2. Can the API link stash items to a project directly?
3. Can start date, end date, status, and notes be set at creation time?
4. Are project notes plain text, HTML, Markdown, or Ravelry markup?
5. Are there documented rate limits?
7. Can project photos be uploaded via the API?
8. **Multi-colorway project support:** The yarn group aggregation feature groups stash entries by `(yarn_id, colorway)`. A future enhancement should consider multi-color projects (striped sweater, colorblock cardigan) — requires both a UX mechanism for the user to declare intent and a recommendation schema that can express "use yarn A for the body, yarn B for the yoke."

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

## Background: Ravelry API sources

- https://www.ravelry.com/api (requires login for full docs)
- https://www.ravelry.com/about/goodies
- Old ravelry_playground repo: https://github.com/ReneeErnst/ravelry_playground
- `pyravelry` wrapper: https://www.coultontheuer.com/pyravelry/
- Rust client (reference only): https://github.com/strickvl/ravelry-rs
