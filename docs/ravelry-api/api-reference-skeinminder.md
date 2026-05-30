# Ravelry API Reference — SkeinMinder Focus

Extracted 2026-05-16 from https://www.ravelry.com/api (last updated 2026-03-30).
Full rendered page text: `api-docs-full.txt` (223KB).

---

## library/search (authenticated)

`GET /people/{username}/library/search.json`

Search a user's pattern library (patterns they own/have saved).

| Parameter | Type | Description |
|-----------|------|-------------|
| query | String | Full text search |
| query_type | String | "patterns" or "tags" |
| type | String | book, magazine, booklet, pattern, pdf |
| sort | String | title, added, published, author |
| page | Integer | Defaults to 1 |
| page_size | Integer | Defaults to 100 |

Returns: `paginator`, `volumes: Array<Volume (list)>`

---

## patterns/search

`GET /patterns/search.json`

Search the Ravelry pattern database. Accepts all filters available on the on-site pattern search (many undocumented — see note below).

| Parameter | Type | Description |
|-----------|------|-------------|
| query | String | Full text search |
| page | Integer | Defaults to 1 |
| page_size | Integer | Defaults to 100 |
| personal_attributes | Boolean | Include queued/favorited/bookmark status |

**Undocumented filter parameters** (available on-site, usable in API):
- `craft` — filter by craft (knitting, crochet, weaving, etc.)
- `weight` — yarn weight
- `availability` — free, purchase, etc.
- `sort` — `best`, `rating`, `projects`, `created` (hot/new)

Returns: `patterns: Array<Pattern (list)>`, `paginator`

**Key Pattern (list) fields:**
- `id`, `name`, `permalink`
- `free: Boolean` — free pattern flag
- `personal_attributes.queued`, `personal_attributes.favorited`
- `designer`, `first_photo`

**Key Pattern (full) fields** (via `patterns/show`):
- `craft: Craft (list)` — craft type (knitting=2, crochet=1)
- `free: Boolean`
- `pdf_in_library: Boolean` — user owns this pattern's PDF
- `volumes_in_library: Array<Integer>` — volume IDs in user's library
- `yardage`, `yardage_max` — yardage requirements
- `yarn_weight: YarnWeight (list)` — required weight
- `packs: Pack (full)` — suggested yarns
- `gauge`, `gauge_divisor` — gauge info
- `pattern_categories: Array<PatternCategory>`
- `download_location` — URL, free flag, type ("ravelry" or "external")

---

## patterns/show

`GET /patterns/{id}.json`

Returns: `pattern: Pattern (full)`

---

## stash/list (authenticated)

`GET /people/{username}/stash/list.json`

| Parameter | Type | Description |
|-----------|------|-------------|
| page | Integer | Defaults to 1 |
| page_size | Integer | Defaults to 50 |
| sort | String | recent, alpha, weight, colorfamily, yards |

Returns: `stash: Array<Stash (small)>`

---

## stash/show (authenticated)

`GET /people/{username}/stash/{id}.json`

Returns: `stash: Stash (full)`, `user: User (small)`

`Stash (full)` includes `yarn: Yarn (full)` — the full yarn detail.

---

## yarns/show

`GET /yarns/{id}.json`

| Parameter | Type | Description |
|-----------|------|-------------|
| include | Array<String> | colorways, availability |

Returns: `yarn: Yarn (full)`

**Key Yarn (full) fields:**
- `id`, `name`, `permalink`, `yarn_company_name`
- `discontinued: Boolean`
- `yarn_weight: YarnWeight (full)` — weight name and id
- `grams`, `yardage` — per skein
- `wpi: Integer` — wraps per inch
- `min_gauge`, `max_gauge`, `gauge_divisor`
- `yarn_fibers: Array<YarnFiber (full)>` — fiber breakdown with percentages
- `yarn_attributes: Array<YarnAttribute (full)>` — e.g. "Superwash", "Gradient"
- `machine_washable: Boolean`, `certified_organic: Boolean`
- `notes_html`

**NOTE: Yarn objects have NO `craft` field.** There is no API-level distinction between
knitting yarn and weaving yarn. Weaving yarn must be detected by heuristics:
- Yarn name matches count/ply pattern: `\d+/\d+` (e.g. "16/2 Bamboo", "8/4 Cotton")
- Weight category is THREAD or COBWEB (usually weaving/industrial weights)

---

## yarns/search

`GET /yarns/search.json`

| Parameter | Type | Description |
|-----------|------|-------------|
| query | String | Full text search |
| sort | String | best, rating, projects |
| personal_attributes | Boolean | Include stash_ids, favorited, bookmark_id |

---

## Craft (list) result object

| Field | Type | Description |
|-------|------|-------------|
| id | Integer | 1=crochet, 2=knitting |
| name | String | "Knitting", "Crochet", etc. |
| permalink | String | |

Pattern (full) returns `craft: Craft (list)`.
Pattern (public) and Pattern (POST) use `craft_id: Integer`.

---

## Pattern priority for SkeinMinder

To prioritize patterns in recommendations:

1. **User's library first:** `pdf_in_library: true` on Pattern (full), or search `library/search`
2. **Free patterns:** `free: true` on Pattern (list/full); pass `availability=free` to search
3. **Popular/hot:** sort by `projects` (most queue-adds) or `rating`; Ravelry "hot right now" maps to recent project activity
