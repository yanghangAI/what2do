# what2do — Handoff

A static site at **https://yanghangai.github.io/what2do/** showing UMass Amherst recreation hours, classes, and registration links. Data is refreshed daily by a GitHub Action that scrapes upstream UMass pages and commits a new `data/hours.json`. The site itself is plain HTML/CSS/vanilla JS — no build step, no framework.

## How it works

```
┌─────────────────────────────┐         ┌─────────────────────────────┐
│ GitHub Action (daily 5am ET)│ scrape  │ UMass RecWell pages         │
│  python -m scraper.main     │────────▶│  · facilities/hours-operation│
└──────────────┬──────────────┘         │  · recwell.umass.edu/        │
               │ writes                  │  · /Program/GetProducts ...  │
               ▼                          │  · Mullins Finnly Connect   │
       data/hours.json                    └─────────────────────────────┘
               │
               │ GitHub Pages serves repo root
               ▼
       index.html + assets/* fetch hours.json and render
```

### Scrapers (`scraper/`)

| File | Source | Method | Notes |
|------|--------|--------|-------|
| `scrape_recwell.py` | `umass.edu/recwell/facilities/hours-operation` | `requests` + BS4 | Per-facility headings (Boyden, Curry Hicks, RockWell, Rec Center, Mullins Tennis). Section walker unwraps inline tags so phrases like `<u>CLOSED</u> until further notice.` stay on one line. |
| `scrape_mullins.py` | `mullinscenter.finnlyconnect.com/schedule/428` | Playwright (week view) | Reads `<div class="k-event">` `aria-label` directly. Adjacent sessions with <15-min gap are merged. |
| `scrape_programs.py` | `recwell.umass.edu/Program/GetProducts?...` | `requests` + BS4 | Lists climbing + group fitness programs (titles + URLs). No times. |
| `scrape_schedule.py` | `recwell.umass.edu/` | Playwright | Multi-day rolling class calendar (whatever the homepage widget renders). All event types kept; orientation filtered out at render-time only. |
| `scrape_alert.py` | `recwell.umass.edu/` | `requests` + BS4 | Two outputs: (a) full alert text for the banner, (b) parsed per-facility hour overrides with start dates. |
| `merge.py` | — | pure function | Combines new scrape results with previous JSON, applying per-facility stale/failed flags. |
| `main.py` | — | orchestrator | Runs all scrapers, calls `merge_results`, applies alert overrides if today ≥ start date (or facility is in the close-gap transition), writes JSON. |

### Alert override flow

The RecWell homepage carries a free-form `FACILITIES ALERT` banner — schedule changes, semester transitions, holiday closures. `scrape_alert.py` parses this into structured per-facility overrides:

```python
{
  "recreation-center": {"start_date": "2026-05-20", "closed_from": "2026-05-14", "hours": {...}},
  "boyden-pool":       {"start_date": "2026-05-20", "closed_from": "2026-05-14", "hours": {...}},
  ...
}
```

In `main.py`, for each facility with an override:
- If today ≥ `start_date` → replace scraped hours with the alert's announced hours (+ a note).
- Else if today ≥ `closed_from` and < `start_date` → mark facility as fully closed (+ transition note).
- Else → leave the scraped hours alone.

The banner itself is also shown verbatim at the top of the page. The frontend hides it once **every time interval mentioned in the alert exists somewhere in the scraped facility data** (i.e. the upstream `/hours-operation` page has caught up), or once today is past every "begin on `<date>`" mentioned.

### Frontend (`index.html`, `assets/`)

Pure HTML/CSS/JS. Cache-busted via `?v=N` query strings on `<link>`/`<script>` — bump `N` whenever you ship a meaningful asset change.

`app.js` builds the DOM from `data/hours.json`. Key sections:

- **Alert banner** — `renderAlert(text, facilities)` with auto-hide logic.
- **Open Now** — facilities currently open, with countdown.
- **Per-category facility cards** — swim, ice, climbing, fitness, tennis.
- **Upcoming Class Schedule** — date-grouped class list. Today's date gets accent color. Each class links to its program page (looked up by name in the programs index).
- **Classes & Programs** — borderless grid. Programs not appearing in the upcoming schedule fade and show a `⊘` icon.

Style: editorial sports broadsheet — Big Shoulders Display headlines, Karla body, JetBrains Mono numerals, cream paper palette with UMass maroon accent. No border-radius, heavy rules between sections. `prefers-color-scheme: dark` swap included.

## Repo layout

```
.github/workflows/scrape.yml        Daily cron at 5am ET (09:00 UTC)
scraper/
  main.py                           Orchestrator
  models.py                         Facility / Interval / HoursDoc + serialization
  scrape_*.py                       Per-source scrapers
  merge.py                          Stale-flag merging logic
  tests/                            pytest suite (~29 tests)
    fixtures/                       HTML snapshots so tests are offline-safe
data/hours.json                     Committed by the Action (and locally testable)
tests/fixtures/hours.sample.json    For opening index.html locally
index.html, assets/styles.css, assets/app.js
docs/superpowers/specs/             Design doc
docs/superpowers/plans/             Implementation plan
```

## Running locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r scraper/requirements.txt
playwright install chromium

# Run the scraper end-to-end
python -m scraper.main

# Serve the static site
python -m http.server 8000
# open http://localhost:8000/   (uses data/hours.json)
# or  http://localhost:8000/?fixture=1   (uses tests/fixtures/hours.sample.json)

# Tests
python -m pytest scraper/tests -q
```

## Common tasks

### Add a new facility (already on the RecWell hours page)
1. Add an entry to `FACILITIES` in `scrape_recwell.py` — id, name, category, regex matching its heading, location, maps URL.
2. If it's a new category, add it to `Category` Literal in `scraper/models.py` and to the section-order list in `assets/app.js` (`["swim", "ice", "climbing", "fitness", "tennis"]`).
3. Add a `<section data-category="...">` in `index.html`.
4. Re-run the scraper, commit, push.

### Add a new program category (e.g. nutrition, adventure)
1. Add an entry to `CATEGORIES` in `scrape_programs.py` with the classification UUID from `recwell.umass.edu/Program`.
2. Add a display label in `PROGRAM_GROUP_LABELS` in `app.js`.

### A scraper test breaks because the upstream page changed
1. Re-download the fixture: e.g. `curl -fsSL ... -o scraper/tests/fixtures/recwell.html`.
2. Run the relevant `print_*` helper or just inspect `parse_*` output to see what changed.
3. Adjust the scraper / fixture and update the asserted intervals if the structural assertions still hold.

### The Action commits but the site doesn't update
- GitHub Pages can lag a minute or two. Hard-refresh.
- Confirm the latest commit touched `index.html` / `assets/*` and that the cache-bust `?v=N` was bumped (otherwise the browser uses the cached JS/CSS).

### Need a token with workflow scope
`gh auth refresh -s workflow` works for OAuth tokens but not classic PATs. If you used a classic PAT, regenerate it at https://github.com/settings/tokens with the `workflow` scope checked.

## Quirks & gotchas

- **RecWell renames things.** "Boyden Pool" was renamed to "Boyden - Beginning Monday, March 30, 2026" mid-semester. The regex is loose (`r"Boyden"`) and relies on document-order first-match; if RecWell ever puts a different "Boyden" heading first, fix the regex.
- **Mullins Tennis** is a real facility but `CLOSED until further notice.` We keep its card so users see "this exists and is unavailable" instead of wondering.
- **Mullins ice schedule is JS-rendered** via Kendo scheduler. The scraper clicks the "Week" view button and parses `.k-event` aria-labels. If Finnly Connect redesigns, expect failure — fall back to scraping the static info page and linking out.
- **Programs page session times are JS-rendered too.** We don't scrape them — the "Sign up" link delegates that. The "no upcoming" badge on programs is computed from the homepage daily calendar (next ~5 days only).
- **GitHub Pages caches assets** — bump `?v=N` on `index.html`'s `<link>`/`<script>` refs after CSS/JS changes.
- **Data freshness** = the last successful Action run. The "Last updated N min ago" badge tells you when. If it says days, the Action is failing — check `Actions` tab.
- **Per-facility scrape failures don't take down the whole run** — failures keep the previous data with `scrape_status: "stale"` and the card gets a yellow staleness banner.
- **Time zones**: scraper uses `datetime.now(ZoneInfo("America/New_York"))`. Frontend uses `Intl.DateTimeFormat(..., { timeZone: "America/New_York" })`. Never `new Date()` for date math involving "today".

## Future work

- **Adventure / Intramural / Club Sports** — sibling categories on `recwell.umass.edu/`, would need their own program-list scraper.
- **Notification when something opens** — push API + service worker. Out of scope for current static-site setup.
- **iCal export** of the next 7 days of classes — easy add if anyone wants it.
- **Replace the Mullins hand-fallback fixture** if the Action ever can't reach Finnly. Currently the test fixture is the live capture; the scrape failure path keeps previous data.
- **Better alert parsing** if UMass changes the alert format on `recwell.umass.edu/`. The current parser is brittle around `Saturday–Sunday | CLOSED` (the day range and the "CLOSED" can be on separate lines — we join them heuristically).

## Contacts / links

- Repo: https://github.com/yanghangAI/what2do
- Live: https://yanghangai.github.io/what2do/
- Actions: https://github.com/yanghangAI/what2do/actions
- Design doc: `docs/superpowers/specs/2026-05-13-umass-hours-site-design.md`
- Implementation plan: `docs/superpowers/plans/2026-05-13-umass-hours-site.md`
