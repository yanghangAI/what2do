# UMass Activity Hours Site — Design

**Date:** 2026-05-13
**Status:** Approved, ready for implementation plan

## Goal

A GitHub Pages site that displays current operating hours for three categories of UMass Amherst recreation facilities — **swimming**, **ice skating**, and **climbing** — with daily auto-updates scraped from official sources.

## Scope

### Facilities covered
- **Swim**: Curry Hicks Pool, Boyden Pool (both at UMass RecWell)
- **Climbing**: RockWell Climbing Gym (UMass RecWell)
- **Ice Skating**: Mullins Community Ice Rink (public skate sessions)

### Each facility displays
- Current open/closed status (computed live in `America/New_York`)
- 7-day weekly schedule table
- Location with Google Maps link
- Notes / special closures
- Link to the official source page
- Per-facility staleness banner if its data could not be refreshed

### Out of scope
- Member-only / login-gated info
- Reservation / booking
- Push notifications
- Mobile app

## Architecture

Decoupled scraper + static site, both in one repo. No backend, no database.

```
repo/
├── .github/workflows/scrape.yml   # daily cron + manual trigger
├── scraper/
│   ├── scrape_recwell.py          # static HTML → pools + climbing
│   ├── scrape_mullins.py          # Playwright → ice skating
│   ├── merge.py                   # merges new results with previous JSON
│   └── main.py                    # orchestrates, writes data/hours.json
├── scraper/tests/
│   ├── fixtures/                  # saved HTML snapshots
│   ├── test_scrape_recwell.py
│   ├── test_scrape_mullins.py
│   └── test_merge.py
├── data/
│   └── hours.json                 # committed by the Action
├── tests/fixtures/hours.sample.json  # for opening site locally
├── index.html
├── assets/styles.css
└── assets/app.js
```

**Rationale:** scraper and site are independent. The Action commits `data/hours.json` back to `main`; GitHub Pages serves the static files directly. No API keys, no secrets, no infrastructure beyond the repo itself.

**Language:** Python for the scraper (mature `requests` + `beautifulsoup4`, well-supported `playwright` package, easy GitHub Actions integration). Vanilla HTML/CSS/JS for the frontend (no build step).

## Data contract: `data/hours.json`

```json
{
  "last_updated": "2026-05-13T14:00:00-04:00",
  "timezone": "America/New_York",
  "facilities": [
    {
      "id": "curry-hicks-pool",
      "name": "Curry Hicks Pool",
      "category": "swim",
      "location": {
        "label": "Curry Hicks Cage, UMass Amherst",
        "maps_url": "https://www.google.com/maps/search/?api=1&query=Curry+Hicks+Cage+UMass+Amherst"
      },
      "source_url": "https://www.umass.edu/recwell/facilities/hours-operation",
      "hours": {
        "mon": [{"open": "11:00", "close": "14:00"}, {"open": "17:00", "close": "19:00"}],
        "tue": [{"open": "09:00", "close": "12:00"}],
        "wed": [{"open": "07:00", "close": "14:00"}, {"open": "17:00", "close": "19:00"}],
        "thu": [{"open": "09:00", "close": "12:00"}],
        "fri": [{"open": "07:00", "close": "09:00"}, {"open": "10:30", "close": "18:00"}],
        "sat": [{"open": "11:00", "close": "19:30"}],
        "sun": [{"open": "11:00", "close": "17:00"}]
      },
      "notes": ["Closed April 4 and April 11, 2026"],
      "scrape_status": "ok",
      "last_scraped": "2026-05-13T14:00:00-04:00"
    }
  ]
}
```

**Field rules:**
- Times are 24-hour `HH:MM` strings in the facility's local timezone (always `America/New_York`).
- `hours` keys are always all seven of `mon`-`sun`; an empty list means closed that day.
- `scrape_status`:
  - `ok` — fresh data from this run
  - `stale` — this run's scrape failed; keeping previous values
  - `failed` — scrape failed and no previous values exist
- `last_scraped` is per-facility; advances only when that facility's scrape succeeded.
- Top-level `last_updated` advances when at least one facility succeeded.

## Scraping

### RecWell (pools + climbing)
- Source: `https://www.umass.edu/recwell/facilities/hours-operation`
- Method: `requests.get` + `BeautifulSoup`
- Strategy: locate facility headings by exact text match ("Boyden Pool", "Curry Hicks Pool", "RockWell Climbing Gym") and parse the day/time text block following each heading into the `hours` structure.
- Notes (e.g., "Closed April 4 and April 11, 2026") are extracted as separate string entries from italicized / parenthetical text near the schedule.

### Mullins (ice skating)
- Source: `https://mullinscenter.finnlyconnect.com/schedule/428` (Public Skate calendar)
- Method: Playwright (headless Chromium) — page is JS-rendered.
- Strategy: load page, `wait_for_selector` on the schedule grid, extract all "Public Skate" events for the visible week as `{day, open, close}` records, group by weekday.
- The Playwright browser is installed in the GitHub Action via the `microsoft/playwright-github-action`-style setup step.

### Failure isolation
Each scraper runs in its own `try/except`. On exception:
- Log the error to the Action log.
- Reuse that facility's previous `hours` and `notes` from the existing `data/hours.json`.
- Set its `scrape_status` to `stale` (or `failed` if no previous entry).
- Leave `last_scraped` unchanged.

The Action only commits when `data/hours.json` content actually differs from `HEAD`.

## Frontend

### Page layout
Single static page (`index.html`):
- Header: title + global "Last updated N hours ago" badge.
- Three sections: **Swim**, **Climbing**, **Ice Skating**.
- Each section contains one card per facility.

### Card contents
- Facility name
- Big status line: `OPEN until 7:00 PM` (green) or `CLOSED — opens tomorrow at 11:00 AM` (red)
- 7-day mini-table (today highlighted)
- Location label + Google Maps link
- Notes list (if any)
- "Source" link
- Yellow banner if `scrape_status !== "ok"`: "Data may be outdated — last refreshed YYYY-MM-DD"

### Status computation (client-side)
- Read `now` in `America/New_York` regardless of viewer's locale (use `Intl.DateTimeFormat` with the `timeZone` option).
- Find today's intervals; if `now` is inside one, status is OPEN until that interval's `close`.
- Otherwise find the next future interval (today or rolling to next day, wrapping the week) and report `CLOSED — opens <weekday> at <time>`.

### Styling
- Plain CSS, system font stack.
- Auto dark/light via `prefers-color-scheme`.
- No frameworks, no bundler, no external CSS libraries.

## GitHub Actions workflow

`.github/workflows/scrape.yml`:
- Triggers: `schedule` (daily at 12:00 UTC ≈ 08:00 ET), plus `workflow_dispatch`.
- Steps: checkout → setup Python → `pip install -r scraper/requirements.txt` → `playwright install chromium` → `python -m scraper.main` → commit & push if `data/hours.json` changed.
- Commits authored by `github-actions[bot]`.
- Permissions: `contents: write`.

## Testing

### Scraper unit tests
- `scraper/tests/fixtures/recwell.html` — committed snapshot of the live page; refreshed manually when scraper drifts.
- `scraper/tests/fixtures/mullins.html` — committed snapshot of the Playwright-rendered DOM.
- Each scraper has tests asserting it produces the expected `{hours, notes}` for its fixture.
- `test_merge.py` covers failure isolation: one scraper failing keeps the other's data fresh, marks the failed one `stale`, preserves previous values.

### Frontend
- `tests/fixtures/hours.sample.json` allows `index.html` to be opened locally (`python -m http.server`) without running the scraper.
- No automated frontend test suite — manual visual check is sufficient for a one-page static site at this scope.

## Open questions resolved during brainstorming

- **Source URLs**: confirmed by research (see Scraping section).
- **Scrape cadence**: daily.
- **Failure mode**: keep last good data + stale banner.
- **Mullins JS rendering**: handled via Playwright in the Action.
- **Number of pools shown**: both Curry Hicks and Boyden.

## Explicit non-goals

- No framework / bundler / CSS library.
- No auto-open-issue on scrape failure.
- No login-gated content.
- No mobile-app or PWA features beyond responsive CSS.
