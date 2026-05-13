# UMass Activity Hours Site Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a GitHub Pages site that displays daily-updated operating hours for UMass Amherst swim, climbing, and ice skating facilities, with data scraped by a GitHub Action.

**Architecture:** Static site (vanilla HTML/CSS/JS) reads `data/hours.json`, which is regenerated daily by a Python scraper running as a GitHub Action. RecWell hours come from a static page via `requests`+`beautifulsoup4`; Mullins ice skating comes from a JS-rendered page via Playwright. Per-facility failure isolation preserves prior data with a stale flag.

**Tech Stack:** Python 3.11, `requests`, `beautifulsoup4`, `playwright`, `pytest`. Frontend: HTML5, CSS (no framework), vanilla JS (no bundler).

**Spec reference:** `docs/superpowers/specs/2026-05-13-umass-hours-site-design.md`

---

## File Structure

Files this plan creates:

```
.github/workflows/scrape.yml         # daily cron + manual trigger
.gitignore
README.md                            # short, how to run locally + deploy

scraper/
  __init__.py
  requirements.txt
  models.py                          # dataclasses + JSON serialization
  scrape_recwell.py                  # static HTML scraper (pools + climbing)
  scrape_mullins.py                  # Playwright scraper (ice skating)
  merge.py                           # combines new results with previous JSON
  main.py                            # orchestrator entrypoint

scraper/tests/
  __init__.py
  conftest.py
  fixtures/
    recwell.html                     # snapshot of live RecWell hours page
    mullins.html                     # snapshot of Playwright-rendered Mullins DOM
    previous_hours.json              # baseline JSON for merge tests
  test_models.py
  test_scrape_recwell.py
  test_scrape_mullins.py
  test_merge.py

data/
  hours.json                         # seeded with a minimal valid JSON

tests/fixtures/
  hours.sample.json                  # for local frontend dev

index.html
assets/
  styles.css
  app.js
```

**Responsibilities:**
- `models.py`: data types and (de)serialization only — no I/O, no scraping logic.
- `scrape_recwell.py` / `scrape_mullins.py`: each takes HTML/page → returns `Facility` records. No I/O for writing files.
- `merge.py`: pure function combining new scrape results with previous JSON, applying staleness rules.
- `main.py`: only orchestration: fetch sources, call scrapers, call merge, write file.
- `app.js`: fetch JSON, render cards, compute open/closed status. No state, no framework.

---

## Task 1: Repo scaffolding

**Files:**
- Create: `.gitignore`
- Create: `scraper/__init__.py` (empty)
- Create: `scraper/tests/__init__.py` (empty)
- Create: `scraper/requirements.txt`
- Create: `README.md`

- [ ] **Step 1: Create `.gitignore`**

```
__pycache__/
*.pyc
.pytest_cache/
.venv/
venv/
node_modules/
.DS_Store
```

- [ ] **Step 2: Create `scraper/requirements.txt`**

```
requests==2.32.3
beautifulsoup4==4.12.3
playwright==1.47.0
pytest==8.3.3
```

- [ ] **Step 3: Create empty package init files**

```bash
: > scraper/__init__.py
mkdir -p scraper/tests && : > scraper/tests/__init__.py
```

- [ ] **Step 4: Create minimal `README.md`**

```markdown
# UMass Activity Hours

Static site showing operating hours for UMass Amherst swim, climbing, and ice skating facilities. Data refreshed daily by a GitHub Action.

## Local development

Frontend only (uses `tests/fixtures/hours.sample.json`):
```
python -m http.server 8000
# open http://localhost:8000/?fixture=1
```

Run scraper:
```
cd scraper
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
python -m scraper.main
```

## Deploy

Push to `main`. GitHub Pages serves the repo root. The scrape workflow runs daily and commits `data/hours.json`.
```

- [ ] **Step 5: Commit**

```bash
git add .gitignore scraper/__init__.py scraper/tests/__init__.py scraper/requirements.txt README.md
git commit -m "chore: scaffold repo"
```

---

## Task 2: Data models

**Files:**
- Create: `scraper/models.py`
- Test: `scraper/tests/test_models.py`

- [ ] **Step 1: Write failing tests**

Create `scraper/tests/test_models.py`:

```python
from scraper.models import Facility, Interval, Location, HoursDoc


def test_interval_round_trip():
    i = Interval(open="09:00", close="17:00")
    assert i.to_dict() == {"open": "09:00", "close": "17:00"}
    assert Interval.from_dict({"open": "09:00", "close": "17:00"}) == i


def test_facility_to_dict_has_all_seven_days():
    f = Facility(
        id="x",
        name="X",
        category="swim",
        location=Location(label="loc", maps_url="https://maps"),
        source_url="https://src",
        hours={"mon": [Interval("09:00", "17:00")]},
        notes=[],
        scrape_status="ok",
        last_scraped="2026-05-13T14:00:00-04:00",
    )
    d = f.to_dict()
    for day in ("mon", "tue", "wed", "thu", "fri", "sat", "sun"):
        assert day in d["hours"]
    assert d["hours"]["mon"] == [{"open": "09:00", "close": "17:00"}]
    assert d["hours"]["tue"] == []


def test_hoursdoc_round_trip():
    doc = HoursDoc(
        last_updated="2026-05-13T14:00:00-04:00",
        timezone="America/New_York",
        facilities=[
            Facility(
                id="x", name="X", category="swim",
                location=Location(label="l", maps_url="https://m"),
                source_url="https://s",
                hours={}, notes=["closed Fri"],
                scrape_status="ok",
                last_scraped="2026-05-13T14:00:00-04:00",
            )
        ],
    )
    restored = HoursDoc.from_dict(doc.to_dict())
    assert restored == doc
```

- [ ] **Step 2: Run tests to confirm failure**

```bash
cd /home/hangyang_umass_edu/UmassActivity
python -m pytest scraper/tests/test_models.py -v
```

Expected: ImportError on `scraper.models`.

- [ ] **Step 3: Implement `scraper/models.py`**

```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
ScrapeStatus = Literal["ok", "stale", "failed"]
Category = Literal["swim", "climbing", "ice"]


@dataclass(frozen=True)
class Interval:
    open: str
    close: str

    def to_dict(self) -> dict:
        return {"open": self.open, "close": self.close}

    @classmethod
    def from_dict(cls, d: dict) -> "Interval":
        return cls(open=d["open"], close=d["close"])


@dataclass(frozen=True)
class Location:
    label: str
    maps_url: str

    def to_dict(self) -> dict:
        return {"label": self.label, "maps_url": self.maps_url}

    @classmethod
    def from_dict(cls, d: dict) -> "Location":
        return cls(label=d["label"], maps_url=d["maps_url"])


@dataclass
class Facility:
    id: str
    name: str
    category: Category
    location: Location
    source_url: str
    hours: dict[str, list[Interval]]
    notes: list[str]
    scrape_status: ScrapeStatus
    last_scraped: str

    def to_dict(self) -> dict:
        full_hours = {d: [i.to_dict() for i in self.hours.get(d, [])] for d in DAYS}
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "location": self.location.to_dict(),
            "source_url": self.source_url,
            "hours": full_hours,
            "notes": list(self.notes),
            "scrape_status": self.scrape_status,
            "last_scraped": self.last_scraped,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Facility":
        return cls(
            id=d["id"],
            name=d["name"],
            category=d["category"],
            location=Location.from_dict(d["location"]),
            source_url=d["source_url"],
            hours={day: [Interval.from_dict(i) for i in d["hours"].get(day, [])] for day in DAYS},
            notes=list(d.get("notes", [])),
            scrape_status=d["scrape_status"],
            last_scraped=d["last_scraped"],
        )


@dataclass
class HoursDoc:
    last_updated: str
    timezone: str
    facilities: list[Facility] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "last_updated": self.last_updated,
            "timezone": self.timezone,
            "facilities": [f.to_dict() for f in self.facilities],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "HoursDoc":
        return cls(
            last_updated=d["last_updated"],
            timezone=d["timezone"],
            facilities=[Facility.from_dict(f) for f in d.get("facilities", [])],
        )
```

- [ ] **Step 4: Run tests to verify pass**

```bash
python -m pytest scraper/tests/test_models.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add scraper/models.py scraper/tests/test_models.py
git commit -m "feat(scraper): data models for facility hours"
```

---

## Task 3: Capture RecWell HTML fixture

**Files:**
- Create: `scraper/tests/fixtures/recwell.html`

- [ ] **Step 1: Download the live page**

```bash
mkdir -p scraper/tests/fixtures
curl -fsSL -A "Mozilla/5.0" "https://www.umass.edu/recwell/facilities/hours-operation" -o scraper/tests/fixtures/recwell.html
```

- [ ] **Step 2: Sanity check the fixture**

```bash
grep -ic "Boyden Pool" scraper/tests/fixtures/recwell.html
grep -ic "Curry Hicks" scraper/tests/fixtures/recwell.html
grep -ic "RockWell" scraper/tests/fixtures/recwell.html
```

Expected: each count ≥ 1. If any returns 0, inspect the file — the headings may use slightly different casing. Do NOT continue until all three facilities are present in the fixture; if RecWell renamed something, update the design spec first.

- [ ] **Step 3: Commit**

```bash
git add scraper/tests/fixtures/recwell.html
git commit -m "test(scraper): add RecWell hours page fixture"
```

---

## Task 4: RecWell scraper

**Files:**
- Create: `scraper/scrape_recwell.py`
- Test: `scraper/tests/test_scrape_recwell.py`

The RecWell page presents each facility's hours under a heading whose text contains the facility name. Below each heading, day-of-week lines follow patterns like `Monday-Friday: 11:00am - 12:30pm` or `Monday: 11:00am - 2:00pm, 5:00pm - 7:00pm`. Notes (closures, exceptions) appear in italic or parenthetical text near the schedule.

- [ ] **Step 1: Write failing tests**

Create `scraper/tests/test_scrape_recwell.py`:

```python
from pathlib import Path
from scraper.scrape_recwell import scrape_recwell
from scraper.models import Interval

FIXTURE = Path(__file__).parent / "fixtures" / "recwell.html"


def test_scrape_returns_three_facilities():
    html = FIXTURE.read_text()
    results = scrape_recwell(html)
    ids = {f["id"] for f in results}
    assert ids == {"boyden-pool", "curry-hicks-pool", "rockwell-climbing"}


def test_curry_hicks_monday_hours():
    html = FIXTURE.read_text()
    results = {f["id"]: f for f in scrape_recwell(html)}
    curry = results["curry-hicks-pool"]
    mon = curry["hours"]["mon"]
    assert Interval("11:00", "14:00") in mon
    assert Interval("17:00", "19:00") in mon


def test_climbing_weekday_hours():
    html = FIXTURE.read_text()
    results = {f["id"]: f for f in scrape_recwell(html)}
    rockwell = results["rockwell-climbing"]
    assert Interval("12:00", "22:00") in rockwell["hours"]["mon"]
    assert Interval("12:00", "22:00") in rockwell["hours"]["thu"]
    assert Interval("12:00", "20:00") in rockwell["hours"]["fri"]


def test_all_seven_days_present_even_if_closed():
    html = FIXTURE.read_text()
    results = scrape_recwell(html)
    for f in results:
        assert set(f["hours"].keys()) == {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}
```

Note: if the live fixture has different specific hours (page changes), update the asserted times in the tests to match the fixture — the tests pin the scraper's behavior against THAT fixture, not against expected real-world hours.

- [ ] **Step 2: Run tests to confirm failure**

```bash
python -m pytest scraper/tests/test_scrape_recwell.py -v
```

Expected: ImportError on `scraper.scrape_recwell`.

- [ ] **Step 3: Implement the scraper**

Create `scraper/scrape_recwell.py`:

```python
"""Scrape pool and climbing hours from the UMass RecWell facilities hours page."""
from __future__ import annotations
import re
from bs4 import BeautifulSoup
from scraper.models import Interval

SOURCE_URL = "https://www.umass.edu/recwell/facilities/hours-operation"

FACILITIES = [
    {
        "id": "boyden-pool",
        "name": "Boyden Pool",
        "category": "swim",
        "match": re.compile(r"Boyden\s+Pool", re.I),
        "location_label": "Boyden Gymnasium, UMass Amherst",
        "maps_url": "https://www.google.com/maps/search/?api=1&query=Boyden+Gymnasium+UMass+Amherst",
    },
    {
        "id": "curry-hicks-pool",
        "name": "Curry Hicks Pool",
        "category": "swim",
        "match": re.compile(r"Curry\s*Hicks", re.I),
        "location_label": "Curry Hicks Cage, UMass Amherst",
        "maps_url": "https://www.google.com/maps/search/?api=1&query=Curry+Hicks+Cage+UMass+Amherst",
    },
    {
        "id": "rockwell-climbing",
        "name": "RockWell Climbing Gym",
        "category": "climbing",
        "match": re.compile(r"RockWell|Climbing", re.I),
        "location_label": "Recreation Center, UMass Amherst",
        "maps_url": "https://www.google.com/maps/search/?api=1&query=UMass+Recreation+Center+Amherst",
    },
]

DAY_ALIASES = {
    "monday": "mon", "mon": "mon",
    "tuesday": "tue", "tues": "tue", "tue": "tue",
    "wednesday": "wed", "weds": "wed", "wed": "wed",
    "thursday": "thu", "thurs": "thu", "thu": "thu",
    "friday": "fri", "fri": "fri",
    "saturday": "sat", "sat": "sat",
    "sunday": "sun", "sun": "sun",
}
DAY_ORDER = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

TIME_RE = re.compile(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)", re.I)


def _to_24h(hour: int, minute: int, ampm: str) -> str:
    ampm = ampm.lower()
    if ampm == "am":
        hour = 0 if hour == 12 else hour
    else:
        hour = hour if hour == 12 else hour + 12
    return f"{hour:02d}:{minute:02d}"


def _parse_time_range(text: str) -> Interval | None:
    matches = TIME_RE.findall(text)
    if len(matches) < 2:
        return None
    h1, m1, ap1 = matches[0]
    h2, m2, ap2 = matches[1]
    return Interval(
        open=_to_24h(int(h1), int(m1 or 0), ap1),
        close=_to_24h(int(h2), int(m2 or 0), ap2),
    )


def _expand_day_token(token: str) -> list[str]:
    token = token.strip().lower().rstrip(":,")
    if "-" in token or "–" in token:
        sep = "-" if "-" in token else "–"
        a, b = [p.strip() for p in token.split(sep, 1)]
        if a in DAY_ALIASES and b in DAY_ALIASES:
            start = DAY_ORDER.index(DAY_ALIASES[a])
            end = DAY_ORDER.index(DAY_ALIASES[b])
            return DAY_ORDER[start : end + 1]
    if token in DAY_ALIASES:
        return [DAY_ALIASES[token]]
    return []


def _parse_schedule_line(line: str) -> tuple[list[str], list[Interval]]:
    """Parse a line like 'Monday-Friday: 11:00am - 12:30pm, 5:00pm - 8:00pm'."""
    if ":" not in line:
        return [], []
    head, rest = line.split(":", 1)
    days = _expand_day_token(head)
    if not days:
        return [], []
    intervals: list[Interval] = []
    for chunk in re.split(r",", rest):
        iv = _parse_time_range(chunk)
        if iv:
            intervals.append(iv)
    return days, intervals


def _section_text_after(soup: BeautifulSoup, regex: re.Pattern, max_chars: int = 1500) -> str:
    """Return the text following the first heading matching `regex`, up to next heading."""
    heading = soup.find(lambda tag: tag.name in ("h1", "h2", "h3", "h4", "strong", "b") and regex.search(tag.get_text(" ", strip=True) or ""))
    if not heading:
        return ""
    pieces: list[str] = []
    for sib in heading.next_elements:
        if sib is heading:
            continue
        if getattr(sib, "name", None) in ("h1", "h2", "h3", "h4") and sib is not heading:
            break
        if hasattr(sib, "get_text"):
            continue
        text = str(sib).strip()
        if text:
            pieces.append(text)
        if sum(len(p) for p in pieces) > max_chars:
            break
    # Fallback: walk next siblings as full elements
    if not pieces:
        node = heading.find_next()
        while node and getattr(node, "name", None) not in ("h1", "h2", "h3", "h4"):
            pieces.append(node.get_text(" ", strip=True))
            node = node.find_next_sibling()
    return "\n".join(p for p in pieces if p)


def _extract_notes(section_text: str) -> list[str]:
    notes: list[str] = []
    for line in section_text.splitlines():
        stripped = line.strip().strip("()")
        if not stripped:
            continue
        if re.search(r"closed", stripped, re.I) and not _parse_schedule_line(stripped)[1]:
            notes.append(stripped)
    return notes


def scrape_recwell(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    results: list[dict] = []
    for fac in FACILITIES:
        text = _section_text_after(soup, fac["match"])
        hours: dict[str, list[Interval]] = {d: [] for d in DAY_ORDER}
        for line in text.splitlines():
            days, intervals = _parse_schedule_line(line)
            for d in days:
                hours[d].extend(intervals)
        results.append({
            "id": fac["id"],
            "name": fac["name"],
            "category": fac["category"],
            "location_label": fac["location_label"],
            "maps_url": fac["maps_url"],
            "source_url": SOURCE_URL,
            "hours": hours,
            "notes": _extract_notes(text),
        })
    return results
```

- [ ] **Step 4: Run tests; iterate against the fixture**

```bash
python -m pytest scraper/tests/test_scrape_recwell.py -v
```

If a test fails because the fixture has different specific hours than asserted, **first** print what the scraper extracted:

```bash
python -c "from pathlib import Path; from scraper.scrape_recwell import scrape_recwell; import json; print(json.dumps(scrape_recwell(Path('scraper/tests/fixtures/recwell.html').read_text()), default=lambda o: o.__dict__, indent=2))"
```

Then update the test's specific `Interval(...)` assertions to match what the live page now says. The structural assertions (three facilities, all seven day keys present) must still pass without modification.

Expected final: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add scraper/scrape_recwell.py scraper/tests/test_scrape_recwell.py
git commit -m "feat(scraper): RecWell pools and climbing scraper"
```

---

## Task 5: Capture Mullins rendered DOM fixture

**Files:**
- Create: `scraper/tests/fixtures/mullins.html`
- Create: `scraper/capture_mullins_fixture.py` (developer helper, not used in production)

- [ ] **Step 1: Install Playwright browsers locally**

```bash
cd /home/hangyang_umass_edu/UmassActivity
python -m venv .venv && source .venv/bin/activate
pip install -r scraper/requirements.txt
playwright install chromium
```

- [ ] **Step 2: Write the fixture-capture helper**

Create `scraper/capture_mullins_fixture.py`:

```python
"""Developer helper: render the Mullins public-skate schedule and save its DOM.

Run when the page changes:
    python -m scraper.capture_mullins_fixture
"""
from pathlib import Path
from playwright.sync_api import sync_playwright

URL = "https://mullinscenter.finnlyconnect.com/schedule/428"
OUT = Path(__file__).parent / "tests" / "fixtures" / "mullins.html"


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(URL, wait_until="networkidle", timeout=60_000)
        try:
            page.wait_for_selector("text=Public Skate", timeout=30_000)
        except Exception:
            pass
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(page.content())
        print(f"wrote {OUT}")
        browser.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run the helper**

```bash
python -m scraper.capture_mullins_fixture
```

Expected: prints `wrote .../mullins.html`. If the page errors out, retry once. If Playwright cannot reach the host from this environment, save a minimal hand-crafted fixture that contains at least one `Public Skate` event with a visible date and time so downstream tests can run; document that in a comment at the top of the fixture.

- [ ] **Step 4: Sanity check**

```bash
grep -ic "public skate" scraper/tests/fixtures/mullins.html
```

Expected: ≥ 1.

- [ ] **Step 5: Commit**

```bash
git add scraper/capture_mullins_fixture.py scraper/tests/fixtures/mullins.html
git commit -m "test(scraper): add Mullins schedule fixture and capture helper"
```

---

## Task 6: Mullins scraper

**Files:**
- Create: `scraper/scrape_mullins.py`
- Test: `scraper/tests/test_scrape_mullins.py`

The Finnly Connect calendar lists events with date headers and time ranges. The scraper has two pieces: a small parser that extracts public-skate intervals from rendered HTML (testable from the fixture), and a thin Playwright wrapper that loads the live page and feeds its content into the parser.

- [ ] **Step 1: Write failing tests for the parser**

Create `scraper/tests/test_scrape_mullins.py`:

```python
from pathlib import Path
from scraper.scrape_mullins import parse_mullins_html

FIXTURE = Path(__file__).parent / "fixtures" / "mullins.html"


def test_returns_facility_record():
    result = parse_mullins_html(FIXTURE.read_text())
    assert result["id"] == "mullins-ice"
    assert result["category"] == "ice"
    assert set(result["hours"].keys()) == {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}


def test_finds_at_least_one_public_skate_slot():
    result = parse_mullins_html(FIXTURE.read_text())
    total_intervals = sum(len(v) for v in result["hours"].values())
    assert total_intervals >= 1, "Expected at least one Public Skate slot in the fixture"


def test_time_format_is_24h_hhmm():
    import re
    result = parse_mullins_html(FIXTURE.read_text())
    for intervals in result["hours"].values():
        for iv in intervals:
            assert re.fullmatch(r"\d{2}:\d{2}", iv.open)
            assert re.fullmatch(r"\d{2}:\d{2}", iv.close)
```

- [ ] **Step 2: Run tests to confirm failure**

```bash
python -m pytest scraper/tests/test_scrape_mullins.py -v
```

Expected: ImportError on `scraper.scrape_mullins`.

- [ ] **Step 3: Implement parser + Playwright fetcher**

Create `scraper/scrape_mullins.py`:

```python
"""Scrape public-skate hours from the Mullins Community Ice Center schedule.

The schedule is JS-rendered by Finnly Connect, so live scraping requires Playwright.
The parser itself works on rendered HTML and is unit-tested against a fixture.
"""
from __future__ import annotations
import re
from datetime import datetime
from bs4 import BeautifulSoup
from scraper.models import Interval

SOURCE_URL = "https://www.mullinscenter.com/mullins-community-ice-center/public-skating"
SCHEDULE_URL = "https://mullinscenter.finnlyconnect.com/schedule/428"

DAY_ORDER = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
TIME_RE = re.compile(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)", re.I)


def _to_24h(hour: int, minute: int, ampm: str) -> str:
    ampm = ampm.lower()
    if ampm == "am":
        hour = 0 if hour == 12 else hour
    else:
        hour = hour if hour == 12 else hour + 12
    return f"{hour:02d}:{minute:02d}"


def _parse_time_range(text: str) -> Interval | None:
    matches = TIME_RE.findall(text)
    if len(matches) < 2:
        return None
    h1, m1, ap1 = matches[0]
    h2, m2, ap2 = matches[1]
    return Interval(
        open=_to_24h(int(h1), int(m1 or 0), ap1),
        close=_to_24h(int(h2), int(m2 or 0), ap2),
    )


def _weekday_from_date_text(text: str) -> str | None:
    """Find an ISO-ish date or weekday name in text and return mon/tue/.../sun."""
    weekday_re = re.compile(r"\b(mon|tue|wed|thu|fri|sat|sun)[a-z]*\b", re.I)
    m = weekday_re.search(text)
    if m:
        return m.group(1).lower()[:3]
    date_re = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")
    m = date_re.search(text)
    if m:
        try:
            d = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            return DAY_ORDER[d.weekday()]
        except ValueError:
            return None
    return None


def parse_mullins_html(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    hours: dict[str, list[Interval]] = {d: [] for d in DAY_ORDER}

    # Look for any element whose text mentions "Public Skate" and extract a time range
    # from the same element or its parents/siblings. Group by weekday found in
    # the same containing "day" block.
    for node in soup.find_all(string=re.compile(r"public\s*skate", re.I)):
        container = node
        for _ in range(6):  # walk up a bit to find the enclosing day block
            if container is None or not hasattr(container, "parent"):
                break
            container = container.parent
            if container is None:
                break
            block_text = container.get_text(" ", strip=True)
            iv = _parse_time_range(block_text)
            day = _weekday_from_date_text(block_text)
            if iv and day:
                if iv not in hours[day]:
                    hours[day].append(iv)
                break

    return {
        "id": "mullins-ice",
        "name": "Mullins Community Ice Rink — Public Skate",
        "category": "ice",
        "location_label": "Mullins Center, UMass Amherst",
        "maps_url": "https://www.google.com/maps/search/?api=1&query=Mullins+Center+UMass+Amherst",
        "source_url": SOURCE_URL,
        "hours": hours,
        "notes": ["Schedule changes weekly — see source link for the latest week."],
    }


def fetch_mullins_html(timeout_ms: int = 60_000) -> str:
    """Render the live Finnly Connect schedule and return its HTML."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.goto(SCHEDULE_URL, wait_until="networkidle", timeout=timeout_ms)
            try:
                page.wait_for_selector("text=Public Skate", timeout=30_000)
            except Exception:
                pass
            return page.content()
        finally:
            browser.close()


def scrape_mullins() -> dict:
    return parse_mullins_html(fetch_mullins_html())
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest scraper/tests/test_scrape_mullins.py -v
```

Expected: 3 passed. If the parser finds zero slots in the fixture, debug by printing the soup's text and adjusting the container-walk depth or the weekday-detection heuristic. The structural shape (id, category, all 7 day keys, 24h time format) must pass before moving on.

- [ ] **Step 5: Commit**

```bash
git add scraper/scrape_mullins.py scraper/tests/test_scrape_mullins.py
git commit -m "feat(scraper): Mullins public-skate scraper"
```

---

## Task 7: Merge module

**Files:**
- Create: `scraper/merge.py`
- Create: `scraper/tests/fixtures/previous_hours.json`
- Test: `scraper/tests/test_merge.py`

`merge` is a pure function: given a list of `(facility_id, result_or_error)` tuples and the previous `HoursDoc` (or None), produce a new `HoursDoc` applying the staleness rules from the spec.

- [ ] **Step 1: Create previous-hours fixture**

Create `scraper/tests/fixtures/previous_hours.json`:

```json
{
  "last_updated": "2026-05-10T08:00:00-04:00",
  "timezone": "America/New_York",
  "facilities": [
    {
      "id": "curry-hicks-pool",
      "name": "Curry Hicks Pool",
      "category": "swim",
      "location": {"label": "Curry Hicks Cage, UMass Amherst", "maps_url": "https://maps"},
      "source_url": "https://www.umass.edu/recwell/facilities/hours-operation",
      "hours": {
        "mon": [{"open": "11:00", "close": "14:00"}],
        "tue": [], "wed": [], "thu": [], "fri": [], "sat": [], "sun": []
      },
      "notes": [],
      "scrape_status": "ok",
      "last_scraped": "2026-05-10T08:00:00-04:00"
    }
  ]
}
```

- [ ] **Step 2: Write failing tests**

Create `scraper/tests/test_merge.py`:

```python
import json
from pathlib import Path
from scraper.merge import merge_results
from scraper.models import HoursDoc, Interval

PREV = Path(__file__).parent / "fixtures" / "previous_hours.json"
NOW = "2026-05-13T14:00:00-04:00"


def _make_result(fid: str, name: str, category: str) -> dict:
    return {
        "id": fid, "name": name, "category": category,
        "location_label": "loc", "maps_url": "https://maps",
        "source_url": "https://src",
        "hours": {"mon": [Interval("09:00", "17:00")], "tue": [], "wed": [], "thu": [],
                   "fri": [], "sat": [], "sun": []},
        "notes": [],
    }


def test_successful_results_become_ok_facilities():
    prev = HoursDoc.from_dict(json.loads(PREV.read_text()))
    results = [("curry-hicks-pool", _make_result("curry-hicks-pool", "Curry Hicks Pool", "swim"), None)]
    doc = merge_results(results, prev, now_iso=NOW)
    f = next(f for f in doc.facilities if f.id == "curry-hicks-pool")
    assert f.scrape_status == "ok"
    assert f.last_scraped == NOW
    assert doc.last_updated == NOW


def test_failed_scrape_keeps_previous_data_marked_stale():
    prev = HoursDoc.from_dict(json.loads(PREV.read_text()))
    results = [("curry-hicks-pool", None, RuntimeError("boom"))]
    doc = merge_results(results, prev, now_iso=NOW)
    f = next(f for f in doc.facilities if f.id == "curry-hicks-pool")
    assert f.scrape_status == "stale"
    assert f.last_scraped == "2026-05-10T08:00:00-04:00"
    assert f.hours["mon"] == [Interval("11:00", "14:00")]


def test_failed_scrape_with_no_prior_data_is_failed():
    results = [("new-facility", None, RuntimeError("boom"))]
    doc = merge_results(results, prev=None, now_iso=NOW)
    f = next(f for f in doc.facilities if f.id == "new-facility")
    assert f.scrape_status == "failed"
    assert all(v == [] for v in f.hours.values())


def test_last_updated_only_advances_when_any_succeeded():
    prev = HoursDoc.from_dict(json.loads(PREV.read_text()))
    results = [("curry-hicks-pool", None, RuntimeError("boom"))]
    doc = merge_results(results, prev, now_iso=NOW)
    assert doc.last_updated == "2026-05-10T08:00:00-04:00"
```

- [ ] **Step 3: Run tests to confirm failure**

```bash
python -m pytest scraper/tests/test_merge.py -v
```

Expected: ImportError on `scraper.merge`.

- [ ] **Step 4: Implement `merge.py`**

Create `scraper/merge.py`:

```python
"""Combine per-facility scrape results with the previous JSON, applying staleness rules."""
from __future__ import annotations
from typing import Iterable
from scraper.models import Facility, HoursDoc, Interval, Location, DAYS

TIMEZONE = "America/New_York"


def _facility_from_result(result: dict, now_iso: str) -> Facility:
    hours: dict[str, list[Interval]] = {}
    for d in DAYS:
        hours[d] = list(result["hours"].get(d, []))
    return Facility(
        id=result["id"],
        name=result["name"],
        category=result["category"],
        location=Location(label=result["location_label"], maps_url=result["maps_url"]),
        source_url=result["source_url"],
        hours=hours,
        notes=list(result.get("notes", [])),
        scrape_status="ok",
        last_scraped=now_iso,
    )


def _stale_from_previous(prev_facility: Facility) -> Facility:
    return Facility(
        id=prev_facility.id,
        name=prev_facility.name,
        category=prev_facility.category,
        location=prev_facility.location,
        source_url=prev_facility.source_url,
        hours={d: list(prev_facility.hours.get(d, [])) for d in DAYS},
        notes=list(prev_facility.notes),
        scrape_status="stale",
        last_scraped=prev_facility.last_scraped,
    )


def _failed_placeholder(facility_id: str, now_iso: str) -> Facility:
    return Facility(
        id=facility_id,
        name=facility_id,
        category="swim",
        location=Location(label="", maps_url=""),
        source_url="",
        hours={d: [] for d in DAYS},
        notes=[],
        scrape_status="failed",
        last_scraped=now_iso,
    )


def merge_results(
    results: Iterable[tuple[str, dict | None, Exception | None]],
    prev: HoursDoc | None,
    now_iso: str,
) -> HoursDoc:
    prev_by_id: dict[str, Facility] = {}
    if prev is not None:
        prev_by_id = {f.id: f for f in prev.facilities}

    facilities: list[Facility] = []
    any_success = False

    for facility_id, result, error in results:
        if error is None and result is not None:
            facilities.append(_facility_from_result(result, now_iso))
            any_success = True
        elif facility_id in prev_by_id:
            facilities.append(_stale_from_previous(prev_by_id[facility_id]))
        else:
            facilities.append(_failed_placeholder(facility_id, now_iso))

    last_updated = now_iso if any_success else (prev.last_updated if prev else now_iso)
    return HoursDoc(last_updated=last_updated, timezone=TIMEZONE, facilities=facilities)
```

- [ ] **Step 5: Run tests**

```bash
python -m pytest scraper/tests/test_merge.py -v
```

Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add scraper/merge.py scraper/tests/test_merge.py scraper/tests/fixtures/previous_hours.json
git commit -m "feat(scraper): merge results with previous JSON and stale-flag failures"
```

---

## Task 8: Orchestrator (`main.py`)

**Files:**
- Create: `scraper/main.py`
- Create: `data/hours.json` (seed)

- [ ] **Step 1: Seed `data/hours.json`**

```bash
mkdir -p data
cat > data/hours.json <<'EOF'
{
  "last_updated": "1970-01-01T00:00:00-04:00",
  "timezone": "America/New_York",
  "facilities": []
}
EOF
```

- [ ] **Step 2: Implement `main.py`**

Create `scraper/main.py`:

```python
"""Entry point: run all scrapers, merge with previous JSON, write data/hours.json."""
from __future__ import annotations
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from scraper.merge import merge_results
from scraper.models import HoursDoc
from scraper.scrape_recwell import SOURCE_URL as RECWELL_URL, scrape_recwell
from scraper.scrape_mullins import scrape_mullins

OUT_PATH = Path(__file__).resolve().parent.parent / "data" / "hours.json"
TZ = ZoneInfo("America/New_York")


def _load_previous() -> HoursDoc | None:
    if not OUT_PATH.exists():
        return None
    try:
        return HoursDoc.from_dict(json.loads(OUT_PATH.read_text()))
    except Exception:
        return None


def _fetch_recwell_html() -> str:
    r = requests.get(RECWELL_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    r.raise_for_status()
    return r.text


def _run_recwell() -> list[tuple[str, dict | None, Exception | None]]:
    try:
        html = _fetch_recwell_html()
        records = scrape_recwell(html)
        return [(r["id"], r, None) for r in records]
    except Exception as e:
        print(f"recwell scrape failed: {e}", file=sys.stderr)
        # Mark all three RecWell facilities as failed
        return [
            ("boyden-pool", None, e),
            ("curry-hicks-pool", None, e),
            ("rockwell-climbing", None, e),
        ]


def _run_mullins() -> tuple[str, dict | None, Exception | None]:
    try:
        return ("mullins-ice", scrape_mullins(), None)
    except Exception as e:
        print(f"mullins scrape failed: {e}", file=sys.stderr)
        return ("mullins-ice", None, e)


def main() -> int:
    now_iso = datetime.now(TZ).isoformat(timespec="seconds")
    prev = _load_previous()

    results: list[tuple[str, dict | None, Exception | None]] = []
    results.extend(_run_recwell())
    results.append(_run_mullins())

    doc = merge_results(results, prev, now_iso=now_iso)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(doc.to_dict(), indent=2) + "\n")
    print(f"wrote {OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Run end-to-end locally**

```bash
cd /home/hangyang_umass_edu/UmassActivity
source .venv/bin/activate
python -m scraper.main
```

Expected: prints `wrote .../data/hours.json` and the file contains four facilities. If Mullins scraping fails (network restrictions in this environment), the file should still contain three RecWell facilities marked `ok` and `mullins-ice` marked `failed` (or `stale` if a previous run succeeded).

- [ ] **Step 4: Inspect the output**

```bash
python -m json.tool data/hours.json | head -40
```

Verify: `last_updated` is today, `facilities` has 4 entries, each entry has all 7 day keys in `hours`.

- [ ] **Step 5: Commit**

```bash
git add scraper/main.py data/hours.json
git commit -m "feat(scraper): orchestrator entrypoint and seed data"
```

---

## Task 9: Frontend sample fixture

**Files:**
- Create: `tests/fixtures/hours.sample.json`

- [ ] **Step 1: Write the fixture**

```bash
mkdir -p tests/fixtures
cat > tests/fixtures/hours.sample.json <<'EOF'
{
  "last_updated": "2026-05-13T14:00:00-04:00",
  "timezone": "America/New_York",
  "facilities": [
    {
      "id": "curry-hicks-pool",
      "name": "Curry Hicks Pool",
      "category": "swim",
      "location": {"label": "Curry Hicks Cage, UMass Amherst", "maps_url": "https://www.google.com/maps/search/?api=1&query=Curry+Hicks+Cage+UMass+Amherst"},
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
    },
    {
      "id": "boyden-pool",
      "name": "Boyden Pool",
      "category": "swim",
      "location": {"label": "Boyden Gymnasium, UMass Amherst", "maps_url": "https://www.google.com/maps/search/?api=1&query=Boyden+Gymnasium+UMass+Amherst"},
      "source_url": "https://www.umass.edu/recwell/facilities/hours-operation",
      "hours": {
        "mon": [{"open": "11:00", "close": "12:30"}],
        "tue": [{"open": "11:00", "close": "12:30"}, {"open": "17:30", "close": "20:00"}],
        "wed": [{"open": "11:00", "close": "12:30"}],
        "thu": [{"open": "11:00", "close": "12:30"}, {"open": "17:30", "close": "20:00"}],
        "fri": [{"open": "11:00", "close": "12:30"}],
        "sat": [], "sun": []
      },
      "notes": [],
      "scrape_status": "ok",
      "last_scraped": "2026-05-13T14:00:00-04:00"
    },
    {
      "id": "rockwell-climbing",
      "name": "RockWell Climbing Gym",
      "category": "climbing",
      "location": {"label": "Recreation Center, UMass Amherst", "maps_url": "https://www.google.com/maps/search/?api=1&query=UMass+Recreation+Center+Amherst"},
      "source_url": "https://www.umass.edu/recwell/facilities/hours-operation",
      "hours": {
        "mon": [{"open": "12:00", "close": "22:00"}],
        "tue": [{"open": "12:00", "close": "22:00"}],
        "wed": [{"open": "12:00", "close": "22:00"}],
        "thu": [{"open": "12:00", "close": "22:00"}],
        "fri": [{"open": "12:00", "close": "20:00"}],
        "sat": [{"open": "12:00", "close": "20:00"}],
        "sun": [{"open": "12:00", "close": "20:00"}]
      },
      "notes": ["Climbers must be 18+", "One-time orientation required"],
      "scrape_status": "ok",
      "last_scraped": "2026-05-13T14:00:00-04:00"
    },
    {
      "id": "mullins-ice",
      "name": "Mullins Community Ice Rink — Public Skate",
      "category": "ice",
      "location": {"label": "Mullins Center, UMass Amherst", "maps_url": "https://www.google.com/maps/search/?api=1&query=Mullins+Center+UMass+Amherst"},
      "source_url": "https://www.mullinscenter.com/mullins-community-ice-center/public-skating",
      "hours": {
        "mon": [], "tue": [], "wed": [{"open": "13:00", "close": "14:50"}],
        "thu": [], "fri": [{"open": "13:00", "close": "14:50"}],
        "sat": [{"open": "13:00", "close": "14:50"}],
        "sun": [{"open": "13:00", "close": "14:50"}]
      },
      "notes": ["Schedule changes weekly — see source link for the latest week."],
      "scrape_status": "stale",
      "last_scraped": "2026-05-11T08:00:00-04:00"
    }
  ]
}
EOF
```

- [ ] **Step 2: Commit**

```bash
git add tests/fixtures/hours.sample.json
git commit -m "test(frontend): sample hours fixture for local dev"
```

---

## Task 10: Frontend HTML + CSS

**Files:**
- Create: `index.html`
- Create: `assets/styles.css`

- [ ] **Step 1: Write `index.html`**

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>UMass Activity Hours</title>
<link rel="stylesheet" href="assets/styles.css">
</head>
<body>
<header>
  <h1>UMass Activity Hours</h1>
  <p class="subtitle">Swim · Climbing · Ice Skating</p>
  <p id="updated" class="updated">Loading…</p>
</header>

<main id="app">
  <section data-category="swim">
    <h2>Swim</h2>
    <div class="cards" data-cards-for="swim"></div>
  </section>
  <section data-category="climbing">
    <h2>Climbing</h2>
    <div class="cards" data-cards-for="climbing"></div>
  </section>
  <section data-category="ice">
    <h2>Ice Skating</h2>
    <div class="cards" data-cards-for="ice"></div>
  </section>
</main>

<footer>
  <p>Data scraped daily from official UMass sources. Not affiliated with UMass.</p>
</footer>

<script src="assets/app.js"></script>
</body>
</html>
```

- [ ] **Step 2: Write `assets/styles.css`**

```css
:root {
  --bg: #ffffff;
  --fg: #111827;
  --muted: #6b7280;
  --card-bg: #f9fafb;
  --border: #e5e7eb;
  --accent: #1d4ed8;
  --ok: #15803d;
  --closed: #b91c1c;
  --warn-bg: #fef3c7;
  --warn-fg: #92400e;
}

@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0b1220;
    --fg: #e5e7eb;
    --muted: #9ca3af;
    --card-bg: #111827;
    --border: #1f2937;
    --accent: #60a5fa;
    --ok: #4ade80;
    --closed: #f87171;
    --warn-bg: #422006;
    --warn-fg: #fcd34d;
  }
}

* { box-sizing: border-box; }

body {
  margin: 0;
  background: var(--bg);
  color: var(--fg);
  font: 16px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
}

header, main, footer {
  max-width: 960px;
  margin: 0 auto;
  padding: 1.5rem 1rem;
}

header h1 { margin: 0 0 0.25rem; font-size: 1.75rem; }
.subtitle { margin: 0; color: var(--muted); }
.updated { margin: 0.5rem 0 0; color: var(--muted); font-size: 0.9rem; }

main section { margin-bottom: 2rem; }
main section h2 { font-size: 1.25rem; margin: 0 0 0.75rem; }

.cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 1rem;
}

.card {
  background: var(--card-bg);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 1rem;
}

.card h3 { margin: 0 0 0.5rem; font-size: 1.1rem; }

.status {
  font-weight: 600;
  margin: 0.25rem 0 0.75rem;
}
.status.open { color: var(--ok); }
.status.closed { color: var(--closed); }

.stale-banner {
  background: var(--warn-bg);
  color: var(--warn-fg);
  padding: 0.5rem 0.75rem;
  border-radius: 6px;
  font-size: 0.85rem;
  margin: 0 0 0.75rem;
}

table.week {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.9rem;
  margin: 0.5rem 0 0.75rem;
}
table.week th, table.week td {
  text-align: left;
  padding: 0.25rem 0.5rem;
  border-bottom: 1px solid var(--border);
}
table.week tr.today td { font-weight: 600; }

.meta { font-size: 0.85rem; color: var(--muted); margin: 0.5rem 0 0; }
.meta a { color: var(--accent); }

ul.notes { padding-left: 1.25rem; margin: 0.5rem 0; font-size: 0.9rem; }

footer {
  color: var(--muted);
  font-size: 0.85rem;
  text-align: center;
}
```

- [ ] **Step 3: Commit**

```bash
git add index.html assets/styles.css
git commit -m "feat(frontend): page shell and styles"
```

---

## Task 11: Frontend JS

**Files:**
- Create: `assets/app.js`

- [ ] **Step 1: Write `assets/app.js`**

```javascript
(function () {
  "use strict";

  var TZ = "America/New_York";
  var DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
  var DAY_LABELS = {
    mon: "Mon", tue: "Tue", wed: "Wed", thu: "Thu", fri: "Fri", sat: "Sat", sun: "Sun",
  };
  var DAY_FULL = {
    mon: "Monday", tue: "Tuesday", wed: "Wednesday",
    thu: "Thursday", fri: "Friday", sat: "Saturday", sun: "Sunday",
  };

  function dataUrl() {
    var params = new URLSearchParams(location.search);
    if (params.get("fixture") === "1") return "tests/fixtures/hours.sample.json";
    return "data/hours.json";
  }

  function nowInTz() {
    var parts = new Intl.DateTimeFormat("en-US", {
      timeZone: TZ, hour12: false,
      weekday: "short", hour: "2-digit", minute: "2-digit",
    }).formatToParts(new Date());
    var lookup = {};
    parts.forEach(function (p) { lookup[p.type] = p.value; });
    var weekdayMap = { Mon: "mon", Tue: "tue", Wed: "wed", Thu: "thu", Fri: "fri", Sat: "sat", Sun: "sun" };
    var hour = parseInt(lookup.hour, 10);
    if (hour === 24) hour = 0;
    var minute = parseInt(lookup.minute, 10);
    return {
      day: weekdayMap[lookup.weekday],
      minutes: hour * 60 + minute,
    };
  }

  function toMinutes(hhmm) {
    var bits = hhmm.split(":");
    return parseInt(bits[0], 10) * 60 + parseInt(bits[1], 10);
  }

  function formatTime(hhmm) {
    var bits = hhmm.split(":");
    var h = parseInt(bits[0], 10);
    var m = parseInt(bits[1], 10);
    var suffix = h >= 12 ? "PM" : "AM";
    var h12 = ((h + 11) % 12) + 1;
    return h12 + ":" + (m < 10 ? "0" + m : m) + " " + suffix;
  }

  function nextDay(d) {
    return DAYS[(DAYS.indexOf(d) + 1) % 7];
  }

  function computeStatus(hours, now) {
    var today = hours[now.day] || [];
    for (var i = 0; i < today.length; i++) {
      var iv = today[i];
      if (now.minutes >= toMinutes(iv.open) && now.minutes < toMinutes(iv.close)) {
        return { open: true, until: iv.close };
      }
    }
    // Find next opening today
    for (var j = 0; j < today.length; j++) {
      var iv2 = today[j];
      if (toMinutes(iv2.open) > now.minutes) {
        return { open: false, nextDay: now.day, nextTime: iv2.open, isToday: true };
      }
    }
    // Walk forward up to 7 days
    var d = now.day;
    for (var k = 0; k < 7; k++) {
      d = nextDay(d);
      var slots = hours[d] || [];
      if (slots.length > 0) {
        return { open: false, nextDay: d, nextTime: slots[0].open, isToday: false };
      }
    }
    return { open: false, nextDay: null, nextTime: null, isToday: false };
  }

  function formatRelative(iso) {
    var then = new Date(iso).getTime();
    var diffMs = Date.now() - then;
    if (isNaN(diffMs)) return iso;
    var mins = Math.floor(diffMs / 60000);
    if (mins < 60) return mins + " min ago";
    var hrs = Math.floor(mins / 60);
    if (hrs < 24) return hrs + " hr ago";
    var days = Math.floor(hrs / 24);
    return days + " day" + (days === 1 ? "" : "s") + " ago";
  }

  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (k) {
        if (k === "class") node.className = attrs[k];
        else if (k === "html") node.innerHTML = attrs[k];
        else node.setAttribute(k, attrs[k]);
      });
    }
    (children || []).forEach(function (c) {
      if (c == null) return;
      node.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
    });
    return node;
  }

  function renderStatus(facility, now) {
    var s = computeStatus(facility.hours, now);
    if (s.open) {
      return el("p", { class: "status open" }, ["OPEN until " + formatTime(s.until)]);
    }
    if (!s.nextDay) {
      return el("p", { class: "status closed" }, ["CLOSED"]);
    }
    var when = s.isToday ? "today" : DAY_FULL[s.nextDay];
    return el("p", { class: "status closed" }, ["CLOSED — opens " + when + " at " + formatTime(s.nextTime)]);
  }

  function renderWeekTable(facility, now) {
    var tbody = el("tbody", {}, DAYS.map(function (d) {
      var slots = facility.hours[d] || [];
      var label = slots.length === 0
        ? "Closed"
        : slots.map(function (iv) { return formatTime(iv.open) + " – " + formatTime(iv.close); }).join(", ");
      return el("tr", d === now.day ? { class: "today" } : {}, [
        el("th", {}, [DAY_LABELS[d]]),
        el("td", {}, [label]),
      ]);
    }));
    return el("table", { class: "week" }, [tbody]);
  }

  function renderCard(facility, now) {
    var children = [el("h3", {}, [facility.name])];
    if (facility.scrape_status !== "ok") {
      children.push(el("p", { class: "stale-banner" }, [
        "Data may be outdated — last refreshed " + formatRelative(facility.last_scraped),
      ]));
    }
    children.push(renderStatus(facility, now));
    children.push(renderWeekTable(facility, now));
    if (facility.notes && facility.notes.length) {
      var ul = el("ul", { class: "notes" }, facility.notes.map(function (n) {
        return el("li", {}, [n]);
      }));
      children.push(ul);
    }
    var meta = el("p", { class: "meta" }, []);
    if (facility.location && facility.location.maps_url) {
      meta.appendChild(el("a", { href: facility.location.maps_url, target: "_blank", rel: "noopener" }, [
        facility.location.label || "Map",
      ]));
      meta.appendChild(document.createTextNode(" · "));
    }
    if (facility.source_url) {
      meta.appendChild(el("a", { href: facility.source_url, target: "_blank", rel: "noopener" }, ["Source"]));
    }
    children.push(meta);
    return el("article", { class: "card" }, children);
  }

  function render(doc) {
    var now = nowInTz();
    document.getElementById("updated").textContent =
      "Last updated " + formatRelative(doc.last_updated);
    ["swim", "climbing", "ice"].forEach(function (cat) {
      var container = document.querySelector('[data-cards-for="' + cat + '"]');
      container.innerHTML = "";
      doc.facilities
        .filter(function (f) { return f.category === cat; })
        .forEach(function (f) { container.appendChild(renderCard(f, now)); });
    });
  }

  function showError(message) {
    document.getElementById("updated").textContent = message;
  }

  fetch(dataUrl(), { cache: "no-cache" })
    .then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    })
    .then(render)
    .catch(function (e) { showError("Failed to load hours: " + e.message); });
})();
```

- [ ] **Step 2: Serve and visually check**

```bash
cd /home/hangyang_umass_edu/UmassActivity
python -m http.server 8000 &
SERVER_PID=$!
sleep 1
curl -fsS "http://localhost:8000/?fixture=1" -o /tmp/page.html
curl -fsS "http://localhost:8000/tests/fixtures/hours.sample.json" -o /tmp/data.json
kill $SERVER_PID
grep -c "UMass Activity Hours" /tmp/page.html
python -m json.tool /tmp/data.json > /dev/null && echo "JSON OK"
```

Expected: `1` for the grep, `JSON OK` printed. Note: this only validates the page and fixture load — actual visual rendering requires opening `http://localhost:8000/?fixture=1` in a real browser. If the user has a browser available, ask them to confirm.

- [ ] **Step 3: Commit**

```bash
git add assets/app.js
git commit -m "feat(frontend): render facility cards with live open/closed status"
```

---

## Task 12: GitHub Actions workflow

**Files:**
- Create: `.github/workflows/scrape.yml`

- [ ] **Step 1: Write the workflow**

```yaml
name: Scrape hours

on:
  schedule:
    - cron: "0 12 * * *"  # 12:00 UTC ≈ 08:00 ET
  workflow_dispatch:

permissions:
  contents: write

jobs:
  scrape:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: "pip"
          cache-dependency-path: scraper/requirements.txt

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r scraper/requirements.txt
          playwright install --with-deps chromium

      - name: Run scraper
        run: python -m scraper.main

      - name: Commit if changed
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          if [ -n "$(git status --porcelain data/hours.json)" ]; then
            git add data/hours.json
            git commit -m "chore(data): refresh hours [skip ci]"
            git push
          else
            echo "No changes."
          fi
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/scrape.yml
git commit -m "ci: daily scrape workflow"
```

---

## Task 13: Run full test suite and verify

- [ ] **Step 1: Run all scraper tests**

```bash
cd /home/hangyang_umass_edu/UmassActivity
source .venv/bin/activate
python -m pytest scraper/tests -v
```

Expected: all tests pass.

- [ ] **Step 2: Run end-to-end scrape and inspect output**

```bash
python -m scraper.main
python -m json.tool data/hours.json | head -60
```

Expected: 4 facilities, valid JSON, `last_updated` is today. Mullins may be `failed` or `stale` if Playwright cannot reach the host from this network — that is acceptable; it must work in GitHub Actions.

- [ ] **Step 3: Spot-check the frontend with real data**

```bash
python -m http.server 8000 &
SERVER_PID=$!
sleep 1
curl -fsS "http://localhost:8000/" -o /tmp/real.html
grep -c "UMass Activity Hours" /tmp/real.html
kill $SERVER_PID
```

Expected: `1`. Visual verification still requires a real browser.

- [ ] **Step 4: Commit any test/output adjustments if made**

```bash
git status
# If anything is uncommitted, decide whether it belongs in a fix commit
```

---

## Task 14: Deploy notes

This task does NOT touch code. It is a checklist for the human deploying the site.

- [ ] **Step 1: Create GitHub repo and push**

```bash
gh repo create umass-activity-hours --public --source=. --remote=origin --push
```

- [ ] **Step 2: Enable GitHub Pages**

In repo Settings → Pages, set Source = "Deploy from a branch", Branch = `main`, Folder = `/ (root)`.

- [ ] **Step 3: Trigger the scrape workflow manually once**

In repo Actions tab → "Scrape hours" → "Run workflow". After it succeeds, `data/hours.json` should be updated.

- [ ] **Step 4: Verify the live site**

Open `https://<your-username>.github.io/umass-activity-hours/` and confirm cards render and "Last updated" reflects the workflow run.

---

## Self-Review Notes

- All four facilities from the spec (Boyden, Curry Hicks, RockWell, Mullins) have a scraper path, a test, and a render path.
- Failure modes match the spec: per-facility `ok`/`stale`/`failed`, `last_updated` only advances on success.
- Time format is consistent: 24h `HH:MM` strings throughout, formatted to 12h in the UI.
- All seven day keys are guaranteed at the data-model layer (`Facility.to_dict`), at the merge layer (`merge_results`), and at the scraper layer (initialized with `{d: [] for d in DAY_ORDER}`).
- Test fixtures are committed so scraper tests don't need network access.
- Frontend has a fixture-mode URL param so it can be developed without running the scraper.
- The GitHub Action installs Playwright with `--with-deps`, which is required on `ubuntu-latest`.
