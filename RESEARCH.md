# SkeinMinder Research Notes

_Last updated: 2026-05-12_

## Working project name

**SkeinMinder** — a Ravelry-powered multi-agent studio planner that turns a real yarn stash into feasible, scheduled, human-approved fiber projects.

## Demo thesis

This should be positioned as more than a hobby app. The interview story is:

> I took an older exploratory Ravelry API/data science project, extracted the useful integration ideas, and rebuilt the concept as a production-shaped LangGraph application. The system reads my real Ravelry stash, uses multiple specialized agents to evaluate project feasibility, and only writes back to Ravelry or external tools after a human approval checkpoint.

The strongest engineering themes to demonstrate are:

- API integration with a real third-party system.
- Typed service-layer design around legacy exploratory code.
- Stateful multi-agent orchestration with LangGraph.
- Human-in-the-loop approvals before side effects.
- Deterministic tool execution separated from LLM reasoning.
- Observability, test fixtures, dry-run mode, retries, and validation.

## Repository strategy

### Recommendation: create a new repo, preserve the old repo as provenance

The old repo, [`ReneeErnst/ravelry_playground`](https://github.com/ReneeErnst/ravelry_playground), is useful evidence of prior Ravelry API exploration, but it is not the shape I would use for an interview-ready LangGraph application.

The old repo is framed as “a place to play with data from the Ravelry API,” and the README describes large exploratory pulls, Cauldron notebooks, sweater-pattern data, pattern detail pulls, project-level data, yarn detail pulls, and chunked saves to local files or GCS. That is valuable background, but the new project needs a cleaner application architecture.

Best path:

1. Create a new repo, probably named `skeinminder`, `ravelry-stash-agent`, or `skeinminder-langgraph`.
2. Add a note in the new README that it is inspired by and partially informed by the older `ravelry_playground` exploration.
3. Copy no secrets and avoid copying old notebook-heavy code directly.
4. Reuse concepts, not structure: Ravelry auth, reusable request helper, chunking/caching awareness, pattern search, yarn detail normalization.
5. Optionally archive the old repo or add a short pointer in its README to the new project.

### Why not revive the old repo directly?

The old repo is valuable, but its current shape is exploratory:

- It uses Cauldron notebooks rather than a modern app/test structure.
- It has data science dependencies such as `pandas`, `pandas_gbq`, `numpy`, `h5py`, `tables`, and Google Cloud libraries.
- It stores credentials through local files like `user.txt`, `pwd.txt`, and `token.txt`, which made sense for exploration but should be replaced with environment variables or a secret manager.
- It is oriented around batch data pulls and analysis rather than interactive, stateful agent workflows.

For an interview demo, a new repo communicates intentional product engineering. The old repo can still be used as a credibility anchor: “I had explored this API before; this project is the modernized application version.”

### If choosing to revive the old repo anyway

Revival would require a modernization pass before adding LangGraph:

- Create a fresh branch, e.g. `modern-langgraph-demo`.
- Replace Cauldron workflow with a standard Python package layout.
- Move credentials to `.env` and document required variables.
- Add `.env.example`.
- Remove or quarantine old GCP/BigQuery dependencies unless needed.
- Add `pyproject.toml` with modern dependency management.
- Add `ruff`, `pytest`, and type checking.
- Add a typed `RavelryClient` using `httpx` or `requests`.
- Add Pydantic models for stash items, yarns, patterns, and projects.
- Add fixture recordings for demo stability.
- Add a dry-run mode for all write operations.
- Add CI that runs formatting, linting, and unit tests.
- Add a new README section explaining what is legacy exploration versus current app code.

## Current findings

### Existing `ravelry_playground` repo

The existing repo already contains useful signals:

- It is public and has 36 commits.
- The README describes Ravelry API data pulls for sweater patterns, pattern details, pattern projects, and yarn details.
- It explicitly mentions responsible chunking and monitoring API usage.
- The technical README documents both Basic Auth and OAuth 2.0 paths.
- The helper function `ravelry_get_data` builds URLs like `https://api.ravelry.com/{path}.json` and supports Basic Auth or bearer-token OAuth.
- The old dependency list is data-exploration oriented: `wheel pandas pandas_gbq numpy cauldron-notebook h5py tables google-cloud-bigquery google-cloud-storage`.

Relevant source:

- https://github.com/ReneeErnst/ravelry_playground
- https://raw.githubusercontent.com/ReneeErnst/ravelry_playground/master/README_tech.md
- https://raw.githubusercontent.com/ReneeErnst/ravelry_playground/master/ravelry_playground/puller.py
- https://raw.githubusercontent.com/ReneeErnst/ravelry_playground/master/requirements.txt

### Ravelry API status and caveats

- Ravelry still publicly points developers toward the Ravelry API group from its Goodies page.
- Ravelry still documents stash spreadsheet export as a fallback by clicking the Excel icon in the stash section of the notebook.
- Ravelry’s public Goodies page also mentions a Project Progress API for exporting much of project data as JSON.
- Official detailed API documentation appears to require a Ravelry login, so exact endpoint schemas should be verified from the logged-in developer account before implementation.
- The `pyravelry` wrapper documentation says the API wrapper requires a Ravelry account and username/API key using HTTP Basic Auth, and it advises getting read/write permissions for full endpoint access.
- A newer Rust client, `ravelry-rs`, claims typed async coverage for patterns, yarns, projects, stash, messages, uploads, favorites, bundles, and friends. It lists project methods including `list`, `show`, `create`, `update`, and `delete`. This is useful supporting evidence but should not replace verification against official Ravelry docs.

Relevant sources:

- https://www.ravelry.com/about/goodies
- https://www.ravelry.com/api
- https://www.coultontheuer.com/pyravelry/
- https://github.com/strickvl/ravelry-rs

### LangGraph fit

LangGraph is a good fit because the project needs state, routing, persistence, and human-in-the-loop control. The LangGraph persistence docs say checkpointing enables human-in-the-loop workflows, memory, time travel, and fault-tolerant execution. This is directly relevant for pausing before writing to Ravelry, Notion, Google Calendar, or Google Drive.

Relevant source:

- https://docs.langchain.com/oss/python/langgraph/persistence

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
- Pull current user and stash.
- Normalize stash fields.
- Identify sweater quantities, accessory quantities, single skeins, and scraps.
- Cache responses for demo stability.

### 3. Yarn Normalizer Agent

Turns Ravelry data into agent-friendly project constraints.

Example normalized shape:

```json
{
  "stash_id": 98765,
  "brand": "Example Yarn Co.",
  "yarn_name": "Example Worsted",
  "colorway": "Moss",
  "weight": "Worsted",
  "fiber": ["wool"],
  "skeins": 5,
  "yards_total": 1100,
  "grams_total": 500,
  "color_family": "green",
  "notes": "possible cardigan yarn"
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

- Yardage buffer.
- Yarn weight match.
- Fiber and drape match.
- Gauge risk.
- Garment type.
- Color suitability.
- Washability.
- Need for contrast yarn.

### 6. Project Fit Agent

Evaluates human/project fit.

Signals:

- Desired season.
- Time available.
- Difficulty mood.
- Wardrobe usefulness.
- Project novelty.
- Likelihood of completion.

### 7. Project Planner Agent

Creates a realistic plan.

Responsibilities:

- Swatch step.
- Pattern review step.
- Cast-on/start step.
- Milestones.
- Blocking/finishing.
- Notes for Ravelry project page.
- Calendar-ready tasks.

### 8. Ravelry Project Creator Agent

Prepares a project payload and asks for approval.

Important design rule:

- The LLM should draft the payload.
- A deterministic tool should validate and execute the API write.
- No write should happen without explicit approval.

Potential payload concept:

```json
{
  "name": "Fall Texture Cardigan",
  "pattern_id": 12345,
  "craft": "knitting",
  "status": "in-progress",
  "started": "2026-05-18",
  "completed": null,
  "notes": "Generated by SkeinMinder. Swatch first. Yardage buffer: 12%. Use stash item 98765 as main yarn.",
  "stash_links": [
    {
      "stash_id": 98765,
      "skeins_planned": 5,
      "role": "main color"
    }
  ]
}
```

Exact field names must be verified in the logged-in Ravelry API docs.

### 9. Verification Agent

Reads back created/updated records and confirms the side effect succeeded.

Responsibilities:

- Read created Ravelry project.
- Confirm name, pattern, notes, dates, and stash linkage if supported.
- Report any mismatch.
- Log result to the trace/debug view.

## Tool integrations

### Must-have

- Ravelry API read for stash.
- Ravelry API pattern search/detail, if available.
- LangGraph orchestration.
- LangSmith tracing or equivalent logging.
- Dry-run mode with fixtures.

### Strong next integration

- Ravelry project creation/update.

### Optional but demo-friendly

- Google Calendar for swatching and project milestones.
- Notion or Airtable for project dashboard.
- Google Drive for generated project briefs, notes, and images.
- Slack/email for progress nudges.

## Implementation plan

### Phase 0 — Project setup and repo decision

Goal: create the foundation.

Tasks:

- Create new repo.
- Add README with project pitch and old-repo provenance.
- Add `RESEARCH.md`.
- Add `pyproject.toml`.
- Choose stack: Python, LangGraph, Pydantic, httpx or requests, pytest, ruff.
- Add `.env.example`.
- Add secret-handling guidance.
- Add basic CI.

Exit criteria:

- Repo installs locally.
- Tests run.
- README clearly explains the interview-demo value.

### Phase 1 — Ravelry read-only client

Goal: prove live Ravelry integration.

Tasks:

- Implement `RavelryClient`.
- Support Basic Auth first.
- Add OAuth only if needed for notebook/private/write endpoints.
- Implement current-user call.
- Implement stash list call.
- Implement stash detail call if available.
- Add retries, timeout, error handling, and logging.
- Add fixture recording/sanitization.

Exit criteria:

- CLI command can print normalized stash summary.
- No secrets are logged.
- Tests pass using fixtures.

### Phase 2 — Stash normalization and scoring

Goal: turn raw API data into project constraints.

Tasks:

- Create Pydantic models: `StashItem`, `Yarn`, `PatternCandidate`, `ProjectRecommendation`.
- Normalize yarn weight, yardage, grams, fiber, color, notes, quantity.
- Compute stash categories: sweater quantity, accessory quantity, single skein.
- Implement scoring helpers for yardage buffer and fiber suitability.

Exit criteria:

- Given raw stash fixtures, system returns clean structured stash summary.
- Scoring is deterministic and unit-tested.

### Phase 3 — First LangGraph MVP

Goal: build the simplest useful graph.

Workflow:

```text
User goal -> Read stash -> Normalize stash -> Recommend project archetypes -> Return ranked options
```

Tasks:

- Define graph state.
- Add Supervisor node.
- Add Stash node.
- Add Recommendation node.
- Add final response formatter.
- Add LangSmith tracing if available.

Exit criteria:

- User can ask “What can I make from my stash?”
- System returns 3 recommendations with structured rationale and risks.

### Phase 4 — Pattern search and candidate matching

Goal: use real pattern data when available.

Tasks:

- Verify Ravelry pattern search and pattern detail schemas.
- Add `PatternScoutAgent`.
- Match pattern requirements to stash yarn.
- Add fallback mode for unavailable API fields.
- Rank candidates by stash fit, yardage risk, difficulty fit, and project type.

Exit criteria:

- System can recommend specific patterns or clearly explain when it is using archetypes instead.

### Phase 5 — Human approval checkpoints

Goal: demonstrate safe agentic control.

Tasks:

- Add LangGraph interrupt/checkpoint before writes.
- Show draft payload before side effects.
- Require explicit approval to continue.
- Store graph thread state.
- Add rejection/edit path.

Exit criteria:

- Graph can pause, show proposed action, resume after approval, or revise after edits.

### Phase 6 — Ravelry project write-back

Goal: create or update a Ravelry project.

Tasks:

- Verify official project create/update endpoints and payloads.
- Add read/write credentials.
- Implement `draft_ravelry_project` tool.
- Implement `create_ravelry_project` tool.
- Implement `update_ravelry_project_notes` if needed.
- Implement stash linkage if API supports it.
- Add verification read-back.
- Add dry-run mode.

Exit criteria:

- In dry-run mode, payload is displayed but not written.
- In live mode, after approval, a test Ravelry project is created and verified.

### Phase 7 — External productivity integration

Goal: show cross-service orchestration.

Recommended first external write:

- Google Calendar, because the value is easy to see in a demo.

Tasks:

- Add calendar tool.
- Schedule swatching, cast-on, check-in, and target finish milestones.
- Add approval before calendar writes.
- Add verification.

Optional:

- Notion or Airtable project dashboard.
- Google Drive generated project brief.

Exit criteria:

- Approved project creates Ravelry project plus calendar milestones.

### Phase 8 — Interview demo polish

Goal: make it reliable and explainable.

Tasks:

- Add deterministic demo data.
- Add live mode / fixture mode toggle.
- Add CLI or simple Streamlit/FastAPI UI.
- Add sample prompt scripts.
- Add screenshots/GIFs.
- Add architecture diagram.
- Add “what I would do next” section.
- Add known limitations.

Exit criteria:

- Demo works without live API access.
- Live integration can be shown when credentials/network cooperate.
- README tells a strong architecture story.

## Suggested repo structure

```text
skeinminder/
  README.md
  RESEARCH.md
  pyproject.toml
  .env.example
  src/
    skeinminder/
      __init__.py
      config.py
      ravelry/
        client.py
        models.py
        normalizer.py
        fixtures.py
      graph/
        state.py
        nodes.py
        workflow.py
      agents/
        supervisor.py
        stash.py
        pattern_scout.py
        feasibility.py
        planner.py
        project_creator.py
        verifier.py
      tools/
        ravelry_project.py
        calendar.py
        notion.py
      cli.py
  tests/
    fixtures/
      stash_list_sanitized.json
      pattern_search_sanitized.json
    test_ravelry_client.py
    test_normalizer.py
    test_scoring.py
    test_graph_mvp.py
```

## Demo guardrails

- Do not let the LLM call write tools directly.
- Use explicit tool schemas and validation.
- Add dry-run mode for every write.
- Add a `requires_approval` flag in graph state.
- Never log API keys, OAuth tokens, or personal Ravelry data.
- Use sanitized fixtures for tests and public demos.
- Do not rely on live Ravelry during the interview unless you have a fallback.
- Read back any created/updated resource to verify success.

## Open questions

These should be answered from the logged-in Ravelry developer docs or through controlled API tests:

1. What is the exact endpoint and payload for project creation?
2. Can the API link stash items to a project directly?
3. Can start date, end date, status, and notes be set at creation time?
4. Are project notes plain text, HTML, Markdown, or Ravelry-specific markup?
5. Does project creation require OAuth 2.0, Basic Auth with write permissions, or either?
6. Are there documented rate limits or best-practice limits?
7. What fields are returned by stash list versus stash detail?
8. Which fields are available in pattern search versus pattern detail?
9. Can project photos be uploaded and attached through the API?
10. Are there API terms that affect demo/public use?

## Interview framing

Strong explanation:

> SkeinMinder uses LLM agents for ambiguous judgment and deterministic tools for side effects. The agents evaluate yarn, pattern, timeline, and project fit. LangGraph manages the state, routing, persistence, and human approval gates. Ravelry and Calendar integrations are wrapped as typed tools with validation, dry-run support, and verification reads.

What this demonstrates:

- Legacy-to-modern refactoring judgment.
- API integration and auth design.
- State-aware agent orchestration.
- Safe write workflows.
- Domain modeling.
- Testability and demo reliability.
- Product sensibility around a personally meaningful use case.
