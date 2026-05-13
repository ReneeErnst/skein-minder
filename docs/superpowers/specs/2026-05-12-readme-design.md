---
title: README and user docs design
date: 2026-05-12
status: approved
---

## Goal

Update the README to reflect the full project purpose and add a separate setup doc for user-facing documentation. Remove references to the project being interview prep from all files.

## Audience

Two readers: technical developers orienting to the codebase, and external visitors evaluating the project. Both benefit from clear structure and accurate framing. User docs live in a separate file linked from the README.

## Framing

Vision-forward. Lead with the full product concept, then note implementation status. Do not apologize for phases that aren't built yet — the planned architecture is part of the story.

---

## README structure

### 1. Header

- Title: `SkeinMinder`
- Tagline: "A Ravelry-powered multi-agent studio planner for fiber arts."
- CI badge linking to GitHub Actions workflow

### 2. What it does

2–3 sentence description of the full product concept: reads real Ravelry stash, uses specialized LangGraph agents to evaluate feasibility, gates all writes behind a human approval checkpoint.

### 3. Agent architecture

Table of all planned agents with one-line role descriptions:

| Agent | Role |
|---|---|
| Supervisor | Interprets user goal, routes between agents, controls approval gates |
| Stash | Authenticates to Ravelry, pulls and filters the stash, caches responses |
| Yarn Normalizer | Maps raw Ravelry data to typed `StashItem` with weight, yardage, fiber, and quantity |
| Pattern Scout | Searches or ranks project candidates by weight, yardage, difficulty, and craft type |
| Yarn Feasibility | Scores yardage buffer, weight match, fiber and drape suitability |
| Project Fit | Evaluates season, time available, difficulty mood, and likelihood of completion |
| Project Planner | Builds a swatch-to-bind-off milestone plan with Ravelry notes and calendar tasks |
| Project Creator | Drafts the Ravelry project payload; a deterministic tool executes the write after approval |
| Verification | Reads back created records to confirm side effects succeeded |

Closing note: LLM agents handle ambiguous judgment; deterministic tool wrappers execute all side effects. No write occurs without explicit human approval.

### 4. Implementation status

Phase table:

| Phase | Description | Status |
|---|---|---|
| 0 | Project setup — Python 3.13, uv, ruff, mypy strict, pytest, CI | Complete |
| 1 | Ravelry read-only client — auth, pagination, retries, fixture recording | Complete |
| 2 | Stash normalization and scoring — `StashItem`, weight/yardage/fiber helpers | Complete |
| 3 | First LangGraph MVP — supervisor, stash node, recommendation node | Planned |
| 4 | Pattern search and candidate matching | Planned |
| 5 | Human approval checkpoints and graph persistence | Planned |
| 6 | Ravelry project write-back with dry-run and verification | Planned |
| 7 | External integrations — Google Calendar, Notion | Planned |
| 8 | Demo polish — fixture mode, sample prompts, architecture diagram | Planned |

### 5. Quick start

- `uv sync`
- Note that credentials are required for live mode; link to `docs/setup.md`
- Two commands: `uv run skeinminder stash` (live) and `uv run skeinminder stash --fixture` (no credentials)

### 6. Development commands

Makefile targets: lint, format, typecheck, test, check.

### 7. Design principles

Five bullets:
- LLM agents for judgment, tools for side effects
- Human approval before any write (`requires_approval` graph state flag)
- Fixture-backed testing (sanitized API recordings)
- Stash filtering before the LLM (context window constraint with 1,379+ items)
- Dry-run mode for every write tool

---

## docs/setup.md structure

Separate file linked from the README Quick start section. Covers:

1. **Prerequisites** — Python 3.13, uv
2. **Install** — `uv sync`
3. **Ravelry credentials** — how to create a Personal Account Access app, what the username/password fields mean (access key and personal key, not Ravelry login credentials), where to put them (`.env`)
4. **Fixture mode** — how to run without credentials using `--fixture`
5. **Refreshing fixtures** — how to run the recorder to capture new live responses

---

## Files changed

- `README.md` — full rewrite
- `docs/setup.md` — new file
- `CLAUDE.md` — remove interview reference (already done)
- `RESEARCH.md` — remove interview-specific sections (already done)
