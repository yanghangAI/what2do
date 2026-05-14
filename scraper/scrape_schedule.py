"""Scrape the public daily-rolling class schedule from recwell.umass.edu/.

The homepage renders a multi-day "Upcoming Classes" widget. After Playwright
finishes hydrating, the rendered text contains date headers (e.g.
"Wed, May 13 2026") followed by event lines ("4:00 PM Slow Flow Yoga 60").
We parse that into a flat list grouped by date.

We do NOT filter any event names here — orientation and other entries are
kept in the data so the frontend can cross-reference programs with sessions.
The frontend handles display-time filtering.
"""
from __future__ import annotations
import re
from datetime import datetime

HOME_URL = "https://recwell.umass.edu/"

_DATE_RE = re.compile(
    r"^\s*(Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*,\s+"
    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+"
    r"(\d{1,2})\s+(20\d{2})\s*$",
    re.I,
)
_EVENT_RE = re.compile(
    r"^\s*(\d{1,2}):(\d{2})\s*(AM|PM)\s+(.+?)\s*$",
    re.I,
)
MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _to_iso_date(month_abbrev: str, day: int, year: int) -> str:
    m = MONTHS[month_abbrev[:3].lower()]
    return f"{year:04d}-{m:02d}-{day:02d}"


def _to_24h(hour: int, minute: int, ampm: str) -> str:
    ampm = ampm.lower()
    if ampm == "am":
        hour = 0 if hour == 12 else hour
    else:
        hour = hour if hour == 12 else hour + 12
    return f"{hour:02d}:{minute:02d}"


def parse_schedule_text(body_text: str) -> list[dict]:
    """Parse the visible text of recwell.umass.edu/ into a schedule.

    Returns a list of {date, weekday, events: [{time, name}]} sorted by date,
    with excluded entries filtered out and within-day events sorted by time.
    """
    by_date: dict[str, dict] = {}
    current: str | None = None
    current_weekday: str | None = None
    for raw in body_text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        dm = _DATE_RE.match(line)
        if dm:
            weekday, month, day, year = dm.group(1), dm.group(2), int(dm.group(3)), int(dm.group(4))
            current = _to_iso_date(month, day, year)
            current_weekday = weekday[:3].title()
            by_date.setdefault(current, {"date": current, "weekday": current_weekday, "events": []})
            continue
        if current is None:
            continue
        em = _EVENT_RE.match(line)
        if not em:
            continue
        name = em.group(4).strip()
        time_24 = _to_24h(int(em.group(1)), int(em.group(2)), em.group(3))
        by_date[current]["events"].append({"time": time_24, "name": name})

    out = []
    for date in sorted(by_date.keys()):
        day = by_date[date]
        day["events"].sort(key=lambda e: e["time"])
        out.append(day)
    return out


def fetch_schedule(timeout_ms: int = 60_000) -> list[dict]:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.goto(HOME_URL, wait_until="networkidle", timeout=timeout_ms)
            page.wait_for_timeout(4000)
            text = page.inner_text("body")
        finally:
            browser.close()
    return parse_schedule_text(text)
