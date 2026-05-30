# Ravelry API Documentation — Local Reference

Captured 2026-05-16 from https://www.ravelry.com/api (last updated 2026-03-30).

This is a partial capture focused on endpoints relevant to SkeinMinder.
See `api-methods.md` for endpoint docs and `result-objects.md` for data schemas.

## Key findings for SkeinMinder

**Craft field on yarns:** The Ravelry Yarn API does NOT expose a `craft` field (knitting vs. weaving).
`Yarn (full)` has `yarn_attributes` (e.g. "Superwash", "Gradient") but no craft classification.
Weaving yarn detection must use heuristics (count/ply naming pattern like "16/2 Bamboo").

**Craft field on patterns:** Pattern (full) has `craft: Craft (list)` and Pattern (public)/(POST)
has `craft_id` (crochet = 1, knitting = 2). Can filter pattern search to knitting only.

**Free patterns:** `Pattern (list)` has `free: Boolean`. Pass `free=true` to patterns/search.

**Library patterns:** `Pattern (full)` has `pdf_in_library: Boolean`. The `library/search` endpoint
(`GET /people/{username}/library/search.json`) searches the user's owned patterns.

**Popular patterns:** `patterns/search` accepts `sort` — options include `best`, `rating`, `projects`.
"Hot right now" maps to sorting by recent projects or favorites.

**Pattern search filters:** The API docs note that patterns/search accepts "any of the (many)
parameters for filters that are available in the on-site pattern search." These are undocumented
but include: `weight`, `craft`, `availability` (free/purchase), `fiber`, etc.
