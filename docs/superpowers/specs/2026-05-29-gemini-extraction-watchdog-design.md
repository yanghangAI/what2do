# Gemini Extraction Watchdog — Design

- **Date:** 2026-05-29
- **Status:** Approved (design); pending implementation plan
- **Author:** brainstormed with Claude Code

## Context

The site (`what2do`) shows UMass recreation facility hours and class schedules
scraped daily into `data/hours.json` and rendered by `assets/app.js`. Each source
is parsed by hand-written regex/BeautifulSoup code under `scraper/`.

On 2026-05-29 we found that **RockWell Climbing Gym was shown CLOSED all week
while the source listed it open 4:00pm–8:00pm every day.** Root cause: the
RecWell hours page lists RockWell as `Monday 4pm - 8pm` (no colon), and
`scrape_recwell._parse_schedule_line` discards any line without a colon. The
parser returned empty hours, `merge.py` stamped the facility `ok`, and the wrong
"closed" shipped for 12 days with no alarm.

The deeper problem is **silent degradation**: a parser that extracts nothing is
indistinguishable, in the data, from a facility that is genuinely closed. The
existing `stale`/`failed` safety net in `merge.py` only triggers when a scraper
*raises*; a successful-but-empty (or successful-but-wrong) parse slips through,
and CI stays green.

We already use Gemini successfully elsewhere: `scraper/vision_puffer.py` reads
Puffer's Pond water-quality PDFs via the Gemini REST API (model-fallback chain,
JSON mode, `temperature 0`, strict validation, content-hash caching, graceful
degradation when the key/output is missing).

## Goal

Make the displayed hours/schedules **more accurate** by adding a Gemini-based
safety net that (a) catches when a deterministic parser silently produces wrong
or missing data, and (b) fills in a value when the parser produces nothing —
without letting an LLM become the unreviewed source of truth for
safety-relevant data.

## Non-goals

- Gemini does **not** replace the deterministic parsers as the primary
  extractor. Parsers remain the source of truth and auto-ship their results.
- No change to the fetch layer (`requests` / Playwright), the `models.py`
  data shapes, the `merge.py` stale/failed machinery, or main.py's
  alert-gap/override application logic.
- Programs scraping is out of scope (see Scope).
- Puffer's Pond is already Gemini-based and is unchanged.

## Design overview

For each in-scope source, on each run:

1. **Fetch** the source (unchanged): `requests`/Playwright → HTML or rendered text.
2. **Parse** deterministically → `D` (the existing parser output).
3. **Extract** with Gemini from the *same* fetched text → `G`.
4. **Compare** `D` and `G` (normalized) and decide what ships:

```
D = deterministic parse        G = gemini extract
┌──────────────────────────────────────────────────────────┐
│ D non-empty,  D == G        → ship D,  status ok           │
│ D non-empty,  D != G        → ship D,  status ok + CI WARN │  review: catches wrong parse
│ D empty,      G non-empty   → ship G (backup) + CI WARN    │  backup: RockWell auto-heals
│ D empty,      G empty       → ship D (genuinely closed)    │  Mullins-tennis stays correct
│ G is None (Gemini unavail.) → ship D; if D also empty →    │
│                                last-known-good (stale)     │
└──────────────────────────────────────────────────────────┘
```

On conflict the parser wins (source of truth) but a CI warning is raised; only
when the parser yields nothing does Gemini's value actually ship. This unifies
the "review" and "backup" roles into a single comparison.

### Worked example (RockWell, today)

Parser yields empty hours for `rockwell-climbing`; Gemini reads
`Monday 4pm - 8pm … Sunday 4pm - 8pm` → `{mon..sun: [16:00–20:00]}`. Branch
"D empty, G non-empty" fires: ship Gemini's 4–8pm daily and record a divergence
so the parser gap is fixed.

## Components

### 1. `scraper/gemini_extract.py` (new, shared)

Generalizes the `vision_puffer.py` pattern for text input.

- **Interface:** `extract(text, *, schema, instructions, cache_key, prev=None) -> dict | None`
- Raw REST to `generativelanguage.googleapis.com` (no SDK), reusing the
  model-fallback chain. Text extraction is easy, so the chain is
  `gemini-2.5-flash → gemini-2.5-flash-lite → gemini-2.0-flash`.
- `generationConfig`: `responseMimeType: application/json`, a strict
  `responseSchema`, `temperature: 0`.
- Prompt rule (anti-hallucination, same as puffer): "Extract only what is
  present in the text. If a day/field is not listed, return closed/empty/null.
  Never guess."
- Returns `None` on: missing `GEMINI_API_KEY`, API error across all models,
  invalid JSON, or schema-validation failure. `None` means "Gemini unavailable"
  in the decision logic.
- **Caching:** keyed by `sha256(text)` via `cache_key`. Because GitHub Actions
  checks out fresh each run, the cache state must persist **inside the committed
  `data/hours.json`** — the same way puffer persists its cache key and passes it
  back via `prev` (a local sidecar would be lost between runs). We add a
  top-level `extract_meta` block: `source_id → {input_sha, divergence}`. On a
  run, compute `sha256(fetched_text)`; if it equals the stored `input_sha`, skip
  the Gemini call — the (deterministic) parser still runs and ships as before,
  and the previous `divergence` flag is carried forward for CI. If the hash
  differs, call Gemini, compare, decide, and update `input_sha` + `divergence`.
  The frontend ignores the unknown `extract_meta` key; the workflow already
  commits `hours.json`, so no extra `git add` is needed.

### 2. Per-source schemas & prompts

Each in-scope source defines a JSON schema mirroring its existing data shape and
a short prompt. No new data shapes are introduced.

| Source | Gemini output schema (mirrors existing) |
|---|---|
| RecWell hours | `{ "<facility>": { "mon".."sun": [ {open, close} ] } }` |
| Class schedule | `[ { date, weekday, events: [ {time, name} ] } ]` |
| Mullins ice | `[ { date, open, close } ]` |
| Alert → overrides | `{ overrides: { "<fid>": {start_date, closed_from, hours} }, holidays: [ {date, name} ] }` |

Times are canonical `HH:MM` (24h); dates are ISO `YYYY-MM-DD`.

### 3. Comparison / normalization (false-alarm avoidance)

Comparison runs on **normalized structured data only**:

- Intervals normalized to canonical `HH:MM` and compared **order-independently**
  per day.
- **Notes / free-text are excluded** from comparison — Gemini will phrase notes
  differently; that is not a real divergence.
- Schedule compares the **set** of `(date, time, name)` with name normalization
  (case-folded, whitespace-collapsed).
- Mullins compares the set of `(date, open, close)`.
- Alert overrides compare the structured `{start_date, closed_from, hours}` per
  facility and the holiday `{date, name}` set; the verbatim alert text is not
  compared.

"Empty" for hours means every day's interval list is empty. A source is only a
"backup" candidate when `D` is empty and `G` is non-empty.

### 4. Integration with `main.py` / `merge.py`

- The per-source runner calls the parser, then `gemini_extract.extract(...)`,
  applies the decision logic, and produces `(shipped_value, status, divergence?)`.
- `shipped_value` flows into the existing merge/serialize path exactly as today.
- When the backup branch ships `G`, the facility/source is still `ok` (it has a
  value); the divergence is recorded for CI, not surfaced to end users.
- When Gemini is `None` and the parser is also empty/suspect, the existing
  last-known-good `stale` path is used (reuse `merge.py._stale_from_previous`),
  and the frontend's existing "Data may be outdated" banner (`app.js:580`) shows.
- main.py accumulates a `divergences` list across sources for CI reporting.

## CI visibility

The current workflow (`.github/workflows/scrape.yml`) is green even when data
degrades and only commits on a diff. Changes:

1. main.py writes a divergence summary (source, field, parser value, Gemini
   value) to the GitHub Actions **job summary** and emits a `::warning::` per
   divergence.
2. Data is committed first (so last-good always ships), then a **final gate
   step** exits non-zero if any divergence or `stale`/`failed` status occurred,
   making the run visibly yellow/red so a human notices.

This converts "silent green with bad data" into a loud, reviewable signal.

## Error handling / fallback

- Missing `GEMINI_API_KEY` → `extract` returns `None`; pipeline behaves as
  today (parser-only), no crash. (Production already treats a missing key as
  "skip" per the puffer convention.)
- Gemini API failure/timeout across all models → `None`; parser value ships.
- Invalid/garbage fetched text (empty or below a minimum length / missing an
  expected anchor) → treat as a **fetch failure**, route to the existing
  `stale` path; do **not** feed garbage to Gemini (prevents a false closure
  from an empty page).

## Testing strategy

Tests mock the Gemini HTTP layer for determinism and offline CI:

- Each of the 5 decision branches (agree / disagree / empty-backup /
  genuinely-closed / Gemini-unavailable).
- Normalized comparison: order-independence, note exclusion, schedule-name
  normalization, no false positives on cosmetic differences.
- Caching: unchanged input hash skips the call and reuses the verdict.
- `gemini_extract` validation: malformed JSON, out-of-range/garbled values, and
  missing key all return `None`.
- **Golden regression test:** the colon-less RockWell fixture → parser empty +
  mocked Gemini `4pm–8pm daily` → asserts the backup ships `16:00–20:00` for
  mon–sun **and** a divergence is recorded.
- A separate, non-CI live test (opt-in) may hit the real API for spot-checks.

## Cost

Content-hash caching means ~0 calls on days a source is unchanged and ~1 call
for the daily-rolling schedule. Total a few calls/day at most — comfortably
within the free tier, consistent with current puffer usage.

## Open questions

None outstanding. Programs intentionally excluded (link harvesting, not text
parsing). Programs/Puffer revisit only if a future failure class warrants it.
