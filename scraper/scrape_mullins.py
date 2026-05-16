"""Scrape public-skate hours from the Mullins Community Ice Center schedule.

The schedule is JS-rendered by Finnly Connect using a Kendo scheduler. Each event
appears as `<div class="k-event">` with an `aria-label` like:
    "12:10 PM - 1:50 PM on Wednesday, May 13, 2026 at 12:10 PM to 1:50 PM"
and inner text containing the event title (e.g. "Public Skating").

`fetch_mullins_html` renders the page in Playwright and switches to Week view so
all events for the current week are present. `parse_mullins_html` extracts events
from rendered HTML and is unit-tested against a fixture.
"""
from __future__ import annotations
import re
from datetime import date
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup
from scraper.models import Interval

TZ = ZoneInfo("America/New_York")

SOURCE_URL = "https://www.mullinscenter.com/mullins-community-ice-center/public-skating"
SCHEDULE_URL = "https://mullinscenter.finnlyconnect.com/schedule/428"

DAY_ORDER = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
WEEKDAY_TO_KEY = {
    "monday": "mon", "tuesday": "tue", "wednesday": "wed",
    "thursday": "thu", "friday": "fri", "saturday": "sat", "sunday": "sun",
}

# Matches "12:10 PM - 1:50 PM" anywhere in the aria-label
ARIA_RANGE_RE = re.compile(
    r"(\d{1,2}):(\d{2})\s*(AM|PM)\s*[-–]\s*(\d{1,2}):(\d{2})\s*(AM|PM)",
    re.I,
)
# Matches the weekday name immediately following "on "
ARIA_WEEKDAY_RE = re.compile(
    r"\bon\s+(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b",
    re.I,
)
PUBLIC_SKATE_TEXT_RE = re.compile(r"public\s*skat", re.I)

# Matches the date portion of the aria-label, e.g. "May 13, 2026"
ARIA_DATE_RE = re.compile(
    r"(January|February|March|April|May|June|July|August|"
    r"September|October|November|December)\s+(\d{1,2}),\s*(20\d{2})",
    re.I,
)
_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}


def _to_24h(hour: int, minute: int, ampm: str) -> str:
    ampm = ampm.lower()
    if ampm == "am":
        hour = 0 if hour == 12 else hour
    else:
        hour = hour if hour == 12 else hour + 12
    return f"{hour:02d}:{minute:02d}"


def _to_minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _merge_close_intervals(intervals: list[Interval], gap_threshold_min: int) -> list[Interval]:
    """Merge sorted intervals whose start follows the previous close by < threshold."""
    if not intervals:
        return intervals
    merged = [intervals[0]]
    for iv in intervals[1:]:
        last = merged[-1]
        gap = _to_minutes(iv.open) - _to_minutes(last.close)
        if 0 <= gap < gap_threshold_min:
            merged[-1] = Interval(open=last.open, close=iv.close)
        else:
            merged.append(iv)
    return merged


def _parse_event(event_el) -> tuple[str, Interval, date | None] | None:
    aria = event_el.get("aria-label", "") or ""
    text = event_el.get_text(" ", strip=True)
    if not PUBLIC_SKATE_TEXT_RE.search(text):
        return None
    rm = ARIA_RANGE_RE.search(aria)
    dm = ARIA_WEEKDAY_RE.search(aria)
    if not rm or not dm:
        return None
    day = WEEKDAY_TO_KEY[dm.group(1).lower()]
    interval = Interval(
        open=_to_24h(int(rm.group(1)), int(rm.group(2)), rm.group(3)),
        close=_to_24h(int(rm.group(4)), int(rm.group(5)), rm.group(6)),
    )
    event_date: date | None = None
    datem = ARIA_DATE_RE.search(aria)
    if datem:
        event_date = date(
            int(datem.group(3)),
            _MONTHS[datem.group(1).lower()],
            int(datem.group(2)),
        )
    return day, interval, event_date


def parse_mullins_html(html: str, today: date | None = None) -> dict:
    """Parse Finnly Connect week-view HTML into a hours-by-weekday dict.

    Events with a calendar date earlier than ``today`` are skipped so a
    past Wednesday in the current week stops being rendered as "every
    Wednesday" by the frontend. ``today`` defaults to today in
    America/New_York.
    """
    from datetime import datetime
    if today is None:
        today = datetime.now(TZ).date()
    soup = BeautifulSoup(html, "html.parser")
    hours: dict[str, list[Interval]] = {d: [] for d in DAY_ORDER}

    for event_el in soup.find_all(class_="k-event"):
        parsed = _parse_event(event_el)
        if parsed is None:
            continue
        day, interval, event_date = parsed
        # Drop events whose date has already passed this week — the
        # Finnly week view shows the full calendar week, including days
        # earlier in the week that have already happened.
        if event_date is not None and event_date < today:
            continue
        if interval not in hours[day]:
            hours[day].append(interval)

    for day in DAY_ORDER:
        hours[day].sort(key=lambda iv: iv.open)
        hours[day] = _merge_close_intervals(hours[day], gap_threshold_min=15)

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
    """Render the live Finnly Connect schedule in Week view and return its HTML."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.goto(SCHEDULE_URL, wait_until="networkidle", timeout=timeout_ms)
            try:
                page.locator("text=Week").first.click(timeout=10_000)
            except Exception:
                pass
            page.wait_for_timeout(3000)
            return page.content()
        finally:
            browser.close()


def scrape_mullins() -> dict:
    return parse_mullins_html(fetch_mullins_html())
