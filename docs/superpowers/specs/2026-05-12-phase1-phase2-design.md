# SkeinMinder: Phase 1 + Phase 2 Design

_Date: 2026-05-12_

## Scope

This spec covers the Ravelry data layer: a typed HTTP client (Phase 1) and stash normalization with scoring (Phase 2). No LLM agents are included. The exit criterion for this work is a CLI command that reads from live Ravelry or committed fixtures and prints a normalized stash summary.

Phase 3 (first LangGraph MVP) is out of scope here and will get its own spec.

---

## Package layout

The current flat `main.py` is replaced by a proper `src/skeinminder/` installable package. The recorder, sanitizer, and CLI are all entry points within the package — nothing lives at the repo root except `main.py` as a thin shim if needed.

```
src/skeinminder/
  __init__.py
  config.py              # env var loading: credentials, base URL
  cli.py                 # CLI entry point: `skeinminder stash`
  ravelry/
    __init__.py
    client.py            # RavelryClient
    models.py            # raw Pydantic models mirroring API shapes
    normalizer.py        # raw models → StashItem, scoring helpers
    recorder.py          # one-shot script: live API → tests/fixtures/
    sanitizer.py         # strips personal fields from recorded JSON

tests/
  fixtures/
    current_user.json
    stash_list.json
    stash_detail_sample.json   # detail records for 5 sampled stash items
  conftest.py
  test_ravelry_client.py
  test_normalizer.py
  test_scoring.py
```

The package is wired into `pyproject.toml` as:

```toml
[project.scripts]
skeinminder = "skeinminder.cli:main"
```

---

## Dependencies

Add to `[project.dependencies]` in `pyproject.toml`:

- `httpx` — HTTP client, clean auth and timeout API
- `pydantic>=2` — models and validation
- `tenacity` — retry logic with exponential backoff
- `python-dotenv` — load `.env` at startup

No additional dev dependencies beyond the existing ruff / mypy / pytest / pre-commit stack.

---

## Setup required

Create a `.env` file at the repo root (gitignored):

```
RAVELRY_USERNAME=your_basic_auth_username
RAVELRY_PASSWORD=your_basic_auth_password
```

These are the Basic Auth credentials from the Ravelry developer settings, not the login password. A `.env.example` with blank values is committed to the repo.

No other accounts or API keys are needed for Phases 1+2. Anthropic, LangSmith, Google Calendar, and Notion come in later phases.

---

## Phase 1: RavelryClient

### Endpoints

Three endpoints for Phase 1:

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/current_user.json` | Verify credentials, retrieve username |
| GET | `/stash/{username}/list.json` | Paginated stash entries |
| GET | `/stash/{username}/{id}.json` | Single stash item detail |

### Client design

`RavelryClient` in `client.py`:

- Reads credentials from `config.py` (which loads from environment variables)
- Uses httpx `BasicAuth`
- Base URL: `https://api.ravelry.com`
- Timeouts: 10s connect, 30s read
- Retries: up to 3 attempts with exponential backoff, on 429 and 5xx responses only (via `tenacity`)
- Raises typed exceptions rather than raw httpx errors:
  - `RavelryAuthError` — 401/403
  - `RavelryRateLimitError` — 429 after retries exhausted
  - `RavelryAPIError` — all other non-2xx
- Logs requests at DEBUG level; never logs credential values or response bodies

### Pagination

The stash list endpoint is paginated. The client handles pagination internally: `get_stash_list()` returns a complete list of all stash entries, fetching additional pages as needed. Page size defaults to 100.

### Auth note

Basic Auth covers all read endpoints needed for Phases 1+2. OAuth 2.0 is deferred until Phase 6 (write-back), when it may be required for project creation endpoints. The client is designed so auth can be swapped without changing callers.

---

## Fixture recording and sanitization

### Recorder (`recorder.py`)

A standalone script invoked with:

```bash
uv run python -m skeinminder.ravelry.recorder
```

It:

1. Instantiates `RavelryClient` with live credentials from `.env`
2. Calls `/current_user.json` and `/stash/{username}/list.json`
3. Fetches stash detail for a sample of 5 items (first 5 from the list) to keep fixture size manageable
4. Writes raw JSON responses to `tests/fixtures/`
5. Calls the sanitizer on each file

Run once, review output, commit. Tests never touch the network.

### Sanitizer (`sanitizer.py`)

Strips personally identifiable fields in-place from fixture JSON:

- `username`, `permalink`, `user_id`
- Display names, email addresses, profile URLs
- Free-text `notes` fields (replaced with placeholder text)
- Any fields containing the real Ravelry username

Yarn names, brand names, colorways, weight, yardage, fiber content, and stash IDs are preserved — these are needed for meaningful normalization tests.

### Future: fixture mode in the client

Option C from the design discussion — a `fixture_dir` argument on `RavelryClient` that replaces HTTP calls with fixture reads — is intentionally deferred. It becomes worth doing in Phase 8 (demo polish) when offline demo reliability matters more. The recorder/sanitizer approach is sufficient for Phases 1+2 and keeps the client free of test concerns.

---

## Phase 2: Normalization and scoring

### Model layers

Two distinct layers:

**Raw models** (`models.py`) mirror the Ravelry API response shapes exactly. No logic. These are what the recorder serializes and tests deserialize from fixtures.

**Normalized models** (`normalizer.py`) are what the rest of the app consumes. The normalizer maps raw → normalized and computes derived fields.

### Normalized StashItem

```python
class WeightCategory(str, Enum):
    LACE = "lace"
    FINGERING = "fingering"
    SPORT = "sport"
    DK = "dk"
    WORSTED = "worsted"
    ARAN = "aran"
    BULKY = "bulky"
    SUPER_BULKY = "super_bulky"
    UNKNOWN = "unknown"

class ProjectQuantity(str, Enum):
    SCRAP = "scrap"          # < 200 yards
    ACCESSORY = "accessory"  # 200–799 yards
    SWEATER = "sweater"      # 800+ yards

class StashItem(BaseModel):
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
    project_quantity: ProjectQuantity  # derived from yards_total
```

Yardage thresholds for `ProjectQuantity` are constants in the normalizer, easy to adjust.

### Scoring helpers

Pure functions, deterministic, fully unit-tested. No LLM.

**`yardage_buffer(stash_item, pattern_yards) -> float`**
Returns percent overage (positive) or deficit (negative). Example: 1100 yards stash, 950 yards pattern → +15.8%.

**`weight_match(stash_item, pattern_weight) -> MatchScore`**
Returns `EXACT`, `ADJACENT` (one step away on the weight scale), or `MISMATCH`. Adjacent matches are flagged in recommendations but not disqualifying.

**`fiber_suitability(stash_item, garment_type) -> MatchScore`**
Evaluates fiber against garment type. Examples: wool → cardigan is `EXACT`; superwash wool → baby item is `EXACT`; acrylic → structured tailored coat is `ADJACENT`; delicate silk → heavily textured cable is `MISMATCH`. Rules are a lookup table, not LLM judgment.

```python
class MatchScore(str, Enum):
    EXACT = "exact"
    ADJACENT = "adjacent"
    MISMATCH = "mismatch"
```

---

## CLI

`skeinminder stash` (entry point in `cli.py`) prints a normalized stash summary to stdout:

```
Stash summary for [username]
─────────────────────────────────────
Sweater quantities (800+ yds): 4 items
Accessory quantities (200–799 yds): 7 items
Scraps (< 200 yds): 3 items

Top sweater quantities:
  • Example Worsted in Moss — 1100 yds, Worsted, wool
  • ...
```

The CLI reads from live Ravelry by default. A `--fixture` flag reads from committed fixture files instead, enabling offline use and quick local testing without credentials.

---

## Error handling

- Missing or blank env vars: `RavelryClient.__init__` raises `ConfigError` with a clear message naming the missing variable. `config.py` returns `None` for missing vars so `--fixture` mode works without credentials set.
- Auth failures: `RavelryAuthError` with a message pointing to `.env.example`.
- Network failures after retries: `RavelryAPIError` with status code and URL.
- Normalization failures: unknown weight strings map to `WeightCategory.UNKNOWN` (not a crash); missing yardage raises `NormalizationError` since scoring is impossible without it.

---

## Testing strategy

- All tests use committed fixture JSON. No test makes a live HTTP call.
- `conftest.py` provides a `fixture_client` fixture that returns a `RavelryClient` instance with responses mocked from fixture files using `httpx`'s built-in transport mocking.
- `test_ravelry_client.py`: exercises client methods against mocked transport — correct URL construction, pagination, auth header presence, retry behavior on 429/500.
- `test_normalizer.py`: exercises raw → normalized mapping for a range of weight strings, fiber lists, and yardage values including edge cases.
- `test_scoring.py`: exercises `yardage_buffer`, `weight_match`, `fiber_suitability` with known inputs and expected outputs.

---

## Exit criteria

**Phase 1:**
- `uv run skeinminder stash --fixture` prints a stash summary without network access
- `uv run skeinminder stash` prints the same summary against live Ravelry
- No secrets appear in logs or output
- `make check` passes

**Phase 2:**
- Given fixture files, `normalizer.normalize_stash(raw)` returns correctly classified `StashItem` list
- All scoring helpers return predictable results for known inputs
- `make check` passes
