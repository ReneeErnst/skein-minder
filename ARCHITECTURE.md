# SkeinMinder Architecture

This document explains the design choices behind SkeinMinder — what we chose, why, and what the tradeoffs are. It also 
covers what would need to change if the tool were to grow beyond its current single-user, demo-oriented shape.

---

## What this is

SkeinMinder is a production-shaped LangGraph application. It reads a real user's Ravelry yarn stash, routes that data 
through a pipeline of deterministic filter nodes and one LLM reasoning node, and produces project recommendations 
paired with real Ravelry patterns. It only writes back to any external service after a human approval checkpoint.

The domain is intentionally non-trivial: Ravelry's API has undocumented behavior, stash sizes can run to thousands of 
items, fiber and weight constraints are craft-domain knowledge the LLM must apply correctly, and the difference 
between a good recommendation and a useless one is whether the yarn actually has enough yardage for the project. That 
specificity is what makes the engineering interesting — it's a real constraint-satisfaction problem, not a toy chatbot.

The engineering goals, in order: real third-party API integration with typed models and graceful failure; stateful 
multi-agent orchestration with correct routing; LLM calls that are scoped, reproducible, and observable; and a 
human-in-the-loop gate before any side effects. The web UI and Langfuse tracing are layer-on-top additions that make 
those properties visible.

---

## Stack at a glance

| Concern | Choice |
|---|---|
| Language | Python 3.13 |
| Dependency management | uv + pyproject.toml |
| Linting / formatting | ruff (E/F/I, line-length 88) |
| Type checking | mypy strict mode |
| Orchestration | LangGraph (StateGraph) |
| LLM client | langchain-anthropic + ChatAnthropic |
| API client | httpx + tenacity (retry on 429/5xx) |
| Data validation | Pydantic v2 |
| Web framework | FastAPI + uvicorn, SSE streaming |
| Frontend | Vanilla JS + CSS, vis-network (no build step) |
| Observability | Langfuse v2, self-hosted via Docker Compose |
| Testing | pytest, FixtureTransport (no live API in tests) |
| CI | GitHub Actions — pre-commit + pytest on PRs and `main` |

---

## System layers

**Ravelry client (`ravelry/client.py`).** All network I/O lives here. The client speaks Basic Auth, paginates 
automatically, and retries on 429 and 5xx with exponential backoff via tenacity. It exposes typed 
methods (`get_stash_list`, `get_pattern_details`, etc.) that return raw Pydantic models. Nothing above this layer ever 
sees an HTTP response.

**Normalizer (`ravelry/normalizer.py`).** Converts raw Ravelry API objects into the domain model the graph operates 
on. `RawStashItem` becomes `StashItem`; that translation handles the Ravelry API's quirks (skeins buried in `packs`, 
fiber missing from list format, weight thresholds by category) so the graph never has to. Scoring 
helpers (`weight_match`, `fiber_suitability`, `yardage_buffer`) live here and are pure functions — testable without 
the graph.

**Graph (`graph/`).** The LangGraph StateGraph. `supervisor` classifies the user's intent and routes to one of two 
filter nodes. The filters narrow the stash to ≤20 candidates. `assess_filter_quality` decides whether to proceed or 
warn. `pattern_search` runs four Ravelry API calls deterministically. `recommend` is the only LLM node. `format_output` 
renders the result. All state is a typed `GraphState` TypedDict passed between nodes; nothing is global.

**Web layer (`web/`).** A thin FastAPI wrapper around the graph. `POST /recommend` launches a background task; 
`GET /stream/{id}` streams its events as SSE. The frontend is three HTML phases (input → running → results) driven by 
a vanilla JS SSE consumer. The graph, business logic, and test suite are untouched by the web layer — the web server 
only wraps them.

---

## Named decisions

### Two-layer data model: `Raw*` vs. `StashItem`

Every Ravelry API response is parsed first into a `Raw*` Pydantic model (`RawStashItem`, `RawYarn`, `RawPack`, etc.) 
with `extra="ignore"`. These models map directly to the API JSON shape and are deliberately thin. The graph never 
touches them. Instead, `normalize_stash_item()` converts each raw item into a `StashItem`, resolving the quirks: skein 
count from `packs[0].skeins` (not the null top-level field), weight from the nested `yarn.yarn_weight` object, and 
date from a non-standard timestamp format. Fiber data is not available from the stash list endpoint (`fiber_categories` 
is always empty there); it is populated by a separate `enrich_stash_with_fiber` step that calls the yarn detail API for
items where fiber is missing.

**Why:** The Ravelry API has evolved quietly over time (the `page_count` vs. `pages` paginator field, `skeins` that's 
always null at the list level, `fiber_categories` absent from both list and detail formats). Isolating API shape from 
domain shape means the graph code doesn't break when the API drifts. It also means the scoring helpers and graph nodes 
can be tested with clean `StashItem` objects without constructing realistic nested API blobs.

**Tradeoff:** Two layers means two places to change when the API adds a field you care about. That's acceptable: raw 
model changes are additive (`extra="ignore"` absorbs new fields silently), and the normalizer is the only translation 
point, so the surface area is small.

**At scale:** No change needed. The two-layer pattern gets more valuable as the API surface grows.

---

### Filter the stash before the LLM sees it

The `project_first_filter` and `stash_first_filter` nodes run before `recommend`. They cut the 1,300+ item stash down 
to ≤20 candidates using deterministic rules: weight match, yardage floor, fiber suitability, sweater quantity gate, 
weaving yarn exclusion, date sort. The LLM sees only the filtered list.

**Why:** 1,300 normalized stash items at ~100 tokens each would be 130,000 tokens per call — well over a context 
window and expensive regardless. More importantly, deterministic filtering is testable and auditable in a way LLM 
filtering is not. If a recommendation is wrong, the filter nodes are the first place to look; their logic is pure 
Python and covered by unit tests.

**Tradeoff:** The filter nodes must be smart enough to not drop good candidates. Getting the sweater quantity 
thresholds right (800 yards for worsted, 1500 for fingering) and the fiber suitability rules right matters more than 
it would if the LLM were doing its own filtering. False negatives (good yarn filtered out) produce silent failures. 
The `assess_filter_quality` node catches the worst case (empty or clearly insufficient filtered stash) but not subtle 
filter miscalibration.

**At scale:** The filter logic will need to evolve as the use cases expand (Mode 1 / allow-purchase, Mode 3 / 
specific yarn). The 20-item cap is a tunable constant, not a principled limit.

---

### Keyword-based supervisor (not an LLM classifier)

The `supervisor` node classifies the user's intent using frozenset membership tests on lowercased input: `"use my"`, 
`"i have"`, `"make with"`, `"use up"` → `stash_first`; anything else → `project_first`. Temporal keywords (`"oldest"`, 
`"longest"`, `"been sitting"`) set `oldest_first=True` on the filter.

**Why:** Classification latency is zero, cost is zero, and the logic is trivially testable. For the current two-class 
problem — project-first vs. stash-first — a small keyword set covers the overwhelming majority of real inputs. A 
generative LLM call for binary intent detection would add 200–400ms and $0.001 per query for no accuracy gain on 
common inputs.

**Tradeoff:** The supervisor misclassifies inputs that express the same intent without the trigger phrases. "There's a 
gorgeous DK in my stash I'd like to use" routes `project_first` because none of the trigger words appear. RESEARCH.md 
documents the planned remediation: expand the keyword set first (covers most paraphrases at zero cost), then add a 
sentence-transformer embedding classifier as a fallback (a ~80MB model that runs in ~10–30ms on CPU with no network 
call). A full LLM call for this task would be disproportionate.

**At scale:** Phase 14a's guided UX wizard bypasses the supervisor entirely for Modes 2 and 3 — the user's explicit mode
selection pre-sets `mode` in `GraphState`, and the supervisor skips classification. That's the right long-term 
direction: move intent disambiguation to the UI rather than making the NLP harder.

---

### FixtureTransport: test isolation from a live API

All tests use `FixtureTransport`, a custom `httpx.BaseTransport` subclass that routes HTTP requests to JSON fixture 
files in `tests/fixtures/` based on URL pattern matching. `RavelryClient` accepts a `transport=` kwarg; injecting 
`FixtureTransport()` replaces all network I/O without touching any other code. `recorder.py` is the one-shot script 
for refreshing fixtures from the live API; it writes sanitized JSON (personal data stripped by `sanitizer.py`) to the 
fixture directory.

**Why:** Ravelry has no sandbox or test environment. Tests that call the live API are slow, flaky, require credentials, 
and produce different results as the stash changes. Fixture-based tests are fast, hermetic, and runnable in CI without 
secrets. The `FixtureTransport` approach means the test client is a real `RavelryClient` — the transport is the only 
mock, so everything above it (pagination, retry logic, model parsing) is exercised without network calls.

**Tradeoff:** Fixtures drift from reality as the API evolves. The most important fixture — `stash_list.json` — is a 
curated 39-item subset of the real 1,379-item stash, specifically chosen to exercise edge cases (items with and without 
fiber data, items with `created_at`, items that normalize to different weight categories). It requires manual curation 
when new edge cases matter. Running `recorder.py` periodically keeps fixtures current; that step is intentionally 
manual so fixture changes are reviewed before commit.

**At scale:** No change needed. The pattern scales well to new endpoints — add a route to `FixtureTransport` and a 
fixture file. The sanitizer would need updating if new PII-bearing fields are added to the API responses.

---

### Graceful degradation in `pattern_search`

The `pattern_search` node runs four Ravelry API calls: library pattern IDs, free pattern search, popular pattern 
search, and batch pattern detail. Each is wrapped in its own exception handling. A failure in any one of them (network 
error, 429, unexpected API shape) produces an empty result for that call, not a node failure. If all four fail, 
`pattern_candidates` is set to `[]` and `recommend` falls back to abstract project archetypes.

**Why:** The pattern API calls are supplementary. The core value — recommending projects the user's stash can 
support — does not depend on them. Making the node brittle to any one Ravelry API hiccup would break the happy path 
for what is already a known-unreliable API. Each call degrades independently: a library search failure doesn't prevent 
free pattern results from appearing.

**Tradeoff:** Silent failures. When `pattern_search` falls back to archetypes, the user sees "a structured cardigan" 
instead of "Kiri by Kim Hargreaves." There's no visible signal that patterns were unavailable. Adding a 
`pattern_search_status` field to `GraphState` and surfacing it in the output is a low-effort improvement deferred to 
Phase 15.

**At scale:** No structural change needed. If pattern search reliability becomes a concern, a short TTL cache on the 
free/popular search results would reduce API call volume substantially — those results are weight+query-keyed and 
stable across users.

---

### LangGraph for orchestration

The graph uses LangGraph's `StateGraph` with typed state (`GraphState` TypedDict), conditional edges (for routing 
after `supervisor` and `assess_filter_quality`), and node-level observability via `@observe` decorators.

**Why:** The alternative — a plain Python function that calls filters and then the LLM in sequence — would work for 
the current linear path. LangGraph adds overhead now and pays it back as the system grows: conditional routing is 
declared rather than embedded in if/else chains, state is explicit and inspectable, and the checkpointing/interrupt 
mechanism (Phase 10) requires LangGraph's persistence layer to work correctly. A plain function cannot be paused 
mid-execution and resumed after a human approves an action.

**Tradeoff:** LangGraph's abstractions add indirection. The `build_graph()` / `nodes.*` split means you need to 
understand both the graph topology (in `graph.py`) and the node implementations (in `nodes.py`) to follow the 
execution. 

**At scale:** LangGraph's value increases with complexity. Fan-out (running `pattern_search` and filter nodes in 
parallel), human-in-the-loop checkpointing (Phase 10), time travel debugging via Langfuse, and multi-turn conversation 
(resuming from a prior checkpoint with "try worsted instead") all require the persistence and state management that 
LangGraph provides. The overhead is front-loaded; the payoff is incremental.

---

### FastAPI + SSE + vanilla JS (no build step)

The web server is a FastAPI app with one non-blocking POST endpoint and one SSE stream endpoint. The frontend is a 
single HTML file, one JS file, one CSS file, and the vis-network library loaded from a CDN. No bundler, no 
transpilation, no node_modules.

**Why:** The graph already exists. The web layer's job is to wrap it, stream its events to a browser, and render the 
results. SSE is the right primitive for that: it's one-directional, works over plain HTTP, and browsers have native 
`EventSource` support. A WebSocket would add bidirectionality the current design doesn't need. A JavaScript framework 
would add a build step with no user-visible benefit for a UI that has three states (input, running, results) and 
renders static cards.

**Tradeoff:** Vanilla JS without a framework means no component model, no reactivity, and manually managed DOM state.
 The current three-phase UI is manageable at this scale; adding the Phase 14a guided wizard (mode selector → 
 mode-specific input → results) and Phase 11 approval modal will push against the limits of manual DOM management. The 
 right point to evaluate a lightweight framework (Preact, Alpine.js) is when Phase 14a ships — not before.

SSE is also one-directional: the server can push events to the client, but the client can't send mid-stream messages
back. Phase 10a implemented `POST /approve/{id}` and `POST /cancel/{id}` to relay the user's decision back to the
paused graph; both return 404 for unknown run IDs.

**At scale:** Multi-user use would require replacing `_streams` (an in-process dict of `asyncio.Queue` objects) with a
Redis pub/sub or similar external message bus. Phase 10b plans to add a TTL-based eviction task to prevent unbounded
memory growth in `_streams`; until then, the dict can grow without bound in a long-running server process.

---

### Self-hosted Langfuse (not LangSmith or cloud Langfuse)

Observability is provided by a self-hosted Langfuse v2 instance running via Docker Compose alongside a Postgres 
database. The repo ships a pre-seeded `docker-compose.yml` with hardcoded API keys in `.env.example` so any 
contributor can start tracing immediately with `docker compose up -d`. `setup_langfuse_dataset.py` registers model 
pricing and creates the golden eval dataset idempotently.

**Why:** LangSmith requires a SaaS account and was replaced. Langfuse Cloud would work but introduces a third-party 
dependency and requires rotating cloud credentials in demos. Self-hosted Langfuse means no account, no external key 
rotation, and full control over trace retention. For a portfolio/demo project, "run `docker compose up -d` and 
everything works locally" is a better developer experience than "go create an account first."

**Tradeoff:** Self-hosted means you maintain the Langfuse + Postgres stack. `docker compose down -v` deletes all trace 
history and requires re-running `setup_langfuse_dataset.py`. There's no built-in model pricing table — the setup script 
registers Haiku, Sonnet, and Opus prices; those need updating when Anthropic changes rates.

**At scale:** Langfuse Cloud (or a shared self-hosted instance with a persistent volume) would be the right move for a 
multi-user deployment. The instrumentation code (`@observe` decorators, `langfuse_context.update_current_observation`) 
is identical between self-hosted and cloud — the only change is the `LANGFUSE_HOST` env var.

---

### Stash loaded at startup, not per-request

`create_app()` accepts the normalized stash as a parameter and holds it in a closure. Every recommendation request 
uses the same in-memory stash. The CLI and web command both fetch and normalize the stash once at startup before 
handing it to the graph.

**Why:** The stash doesn't change during a session. Loading it once avoids repeated Ravelry API calls (13+ pages of 
pagination for a 1,300-item stash), which are slow (several seconds) and rate-limited. For a single-user demo, startup 
cost is acceptable; per-request cost is not.

**Tradeoff:** The stash goes stale between restarts. If the user adds yarn to Ravelry during a session, the app won't 
see it until restart. There's no "refresh stash" button in the current UI (RESEARCH.md notes this as a Phase 18 item). 
More critically, the design is fundamentally single-user: `create_app()` takes one stash, one username.

**At scale:** Multi-user use requires moving stash loading into the request handler, guarded by a per-user TTL cache. 
RESEARCH.md's Phase 18 documents the full design: in-memory dict cache (single-process) or Redis (multi-process), 
15–30 minute TTL, keyed by authenticated user identity. The normalized stash is ~1–2MB per user, so 1,000 concurrent 
cached users is 1–2GB in Redis — manageable.

---

### Human approval as a design principle

`GraphState` carries a `requires_approval: bool` field. The rule is: no node writes to Ravelry, Google Calendar, 
Notion, or any external service without first setting `requires_approval = True` and pausing for human confirmation. 
Phase 10a wired the interrupt/resume infrastructure: `MemorySaver` checkpointer in `build_graph()`, `interrupt()` in 
`low_confidence_output`, and `POST /approve/{id}` / `POST /cancel/{id}` resolving the graph's resume future (returning 
404 for unknown IDs). `requires_approval` is still always `False` — the Phase 11 approval gate after `format_output` 
is the remaining stub before any write nodes are added.

**Why:** The core product claim is "it only writes after you approve." If that's not true in the implementation, the 
whole architecture story falls apart. The design rule is stated explicitly here so that every future write tool is 
built with the approval gate from the start, not retrofitted after the fact. The LangGraph checkpointer also enables 
multi-turn conversation within a session — "show me simpler options" can branch from the paused state rather than 
starting a new run.

**Tradeoff:** The interrupt/resume plumbing is live; the approval gate itself is not. Anyone reviewing the code should 
know that `requires_approval=False` and the absence of write nodes is intentional deferred work (Phase 11), not an 
overlooked gap.

**At scale:** `MemorySaver` (in-process) works for a single server instance. A multi-user deployment requires 
`PostgresSaver` or equivalent so that graph state survives across requests and server restarts. The Postgres instance 
already present for Langfuse can host the checkpointer tables in a separate schema.

---

### Prompt caching on the system prompt

The `recommend` node sends the system prompt with `"cache_control": {"type": "ephemeral"}`, using Anthropic's prompt 
caching feature. On repeated calls with the same system prompt, the input token cost for the cached portion drops by 
~90%.

**Why:** The system prompt (~250 tokens) is identical across all recommendation runs. Caching it is a one-line 
addition that meaningfully reduces cost when the eval suite, tests, or demo runs call `recommend` repeatedly. At Haiku 
pricing ($0.001 per 1k input tokens after cache miss, $0.0001 on cache hit), the saving per run is small — but it 
demonstrates correct use of the feature and becomes more significant if the system prompt grows or a more expensive 
model is used.

**Tradeoff:** Prompt caching requires the cached content to be bit-identical between calls. Any per-user content 
injected into the system prompt (e.g., username, preferences) breaks cache hits. The current design keeps all per-user 
context in the human message, not the system prompt, specifically to preserve caching. That constraint should be 
documented for anyone extending the prompt.

**At scale:** If the system prompt grows substantially (e.g., domain knowledge injected per craft type), caching the 
stable base and appending dynamic content as a separate message segment is the right pattern.

---

## What changes at scale

The current design is deliberately single-user and local-first. RESEARCH.md's Phase 18 documents the full production 
path; the key items are:

**Session and auth layer.** Ravelry credentials come from env vars today. Multi-user use requires an OAuth flow 
(Ravelry supports OAuth 2) or a per-request credential store. `GraphState.ravelry_username` and `create_app()`'s 
`stash` parameter would move from process-level constants to per-request values.

**Stash and pattern caching.** Stash loading (13+ Ravelry API pages) and the four pattern search calls per run both 
benefit from TTL-keyed caches. In-memory dict is sufficient for a single process; Redis for multi-process deployment.

**Async pagination.** `get_stash_list()` and `get_library_pattern_ids()` paginate sequentially with `httpx.Client`. 
Switching to `httpx.AsyncClient` with `asyncio.gather()` over page calls could reduce stash load time by 70–80% for 
large stashes. This requires an async variant of `RavelryClient` or a refactor of the existing client.

**LangGraph fan-out.** Pattern search and stash filtering are independent after `supervisor` resolves. LangGraph's 
fan-out support would let them run in parallel, hiding the ~500ms pattern API latency behind the near-instantaneous 
filter step.

**Persistent run results.** `last_run.json` is a single file in the working directory. A `runs` table in Postgres 
(keyed by user + run ID, with TTL) replaces it for multi-user use. The existing Postgres instance (for Langfuse) can 
host this.

**LangGraph checkpointer.** `MemorySaver` (Phase 10) works for a single server instance. Multi-user deployment needs 
`PostgresSaver` for persistence across requests and restarts.

**Supervisor robustness.** The keyword-based supervisor misclassifies inputs that paraphrase the trigger phrases. 
Expanding the keyword set (covers most cases at zero cost) and adding a sentence-transformer embedding classifier as a 
fallback are the right remediation steps, in that order (see improvement backlog). Phase 14a's guided wizard partially 
sidesteps this by moving intent disambiguation to the UI.
