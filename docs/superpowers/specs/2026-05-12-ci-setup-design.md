# CI Setup Design

_Date: 2026-05-12_

## Overview

Add GitHub Actions CI, pre-commit hooks, and a Makefile to the skein-minder repo. The goal is baseline code quality enforcement (linting, formatting, type checking, tests) that runs consistently both locally and in CI.

## Trigger

CI runs on pull requests targeting `main` only. No push-triggered runs.

## Pre-commit Config (`.pre-commit-config.yaml`)

Two hooks using official mirrors:

- **ruff-pre-commit**: runs `ruff check` (lint) and `ruff format --check` (formatting) on every commit
- **pre-commit-mirrors-mypy**: runs mypy for type checking on every commit

Pre-commit enforces these checks locally at commit time. In CI, `pre-commit run --all-files` applies them to the full codebase.

## GitHub Actions (`.github/workflows/ci.yml`)

Two parallel jobs, both triggered on `pull_request` to `main`:

| Job | Steps |
|-----|-------|
| `pre-commit` | Set up Python 3.12, install pre-commit, run `pre-commit run --all-files` |
| `test` | Set up Python 3.12, install uv, run `uv sync --dev`, run `pytest` |

Jobs are parallel so a lint failure doesn't suppress test results.

## Makefile

| Target | Command | Purpose |
|--------|---------|---------|
| `install` | `uv sync` | Install all dependencies including dev |
| `lint` | `uv run ruff check .` | Run linter |
| `format` | `uv run ruff format .` | Auto-format code |
| `typecheck` | `uv run mypy .` | Run type checker |
| `test` | `uv run pytest` | Run test suite |
| `check` | `pre-commit run --all-files && uv run pytest` | Full local CI equivalent |

## `pyproject.toml` Updates

### Dev dependencies

```
ruff
mypy
pytest
pre-commit
```

### Config sections to add

**`[tool.ruff]`**
- `line-length = 88`
- `target-version = "py312"`
- `select = ["E", "F", "I"]` (pycodestyle errors, pyflakes, isort)

**`[tool.mypy]`**
- `strict = true`
- `python_version = "3.12"`

**`[tool.pytest.ini_options]`**
- `testpaths = ["tests"]`

## Files Created or Modified

| File | Action |
|------|--------|
| `.pre-commit-config.yaml` | Create |
| `.github/workflows/ci.yml` | Create |
| `Makefile` | Create |
| `pyproject.toml` | Modify (add dev deps + tool config) |
| `tests/__init__.py` | Create (empty, establishes test directory) |
