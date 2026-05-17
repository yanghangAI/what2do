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


def _parse_event(event_el) -> tuple[Interval, date | None] | None:
    aria = event_el.get("aria-label", "") or ""
    text = event_el.get_text(" ", strip=True)
    if not PUBLIC_SKATE_TEXT_RE.search(text):
        return None
    rm = ARIA_RANGE_RE.search(aria)
    if not rm:
        return None
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
    return interval, event_date


def _merge_close_dated(events: list[dict], gap_threshold_min: int = 15) -> list[dict]:
    if not events:
        return events
    by_date: dict[str, list[Interval]] = {}
    for ev in events:
        by_date.setdefault(ev["date"], []).append(Interval(ev["open"], ev["close"]))
    out: list[dict] = []
    for d in sorted(by_date):
        ivs = sorted(by_date[d], key=lambda iv: iv.open)
        merged = _merge_close_intervals(ivs, gap_threshold_min)
        for iv in merged:
            out.append({"date": d, "open": iv.open, "close": iv.close})
    return out


def parse_mullins_html(html: str, today: date | None = None) -> dict:
    """Parse Finnly Connect week-view HTML into a list of dated events.

    Returns a facility record with an ``events`` list of
    ``{date, open, close}`` rather than a weekday-keyed ``hours`` dict
    — the Mullins schedule changes week-to-week, so day-of-week labels
    would conflate "this Sat" with "next Sat" once the Finnly view
    rolls over to the following week. ``hours`` is emitted as empty
    for backward compatibility with the frontend's fallback path.
    """
    from datetime import datetime
    if today is None:
        today = datetime.now(TZ).date()
    soup = BeautifulSoup(html, "html.parser")
    raw: list[dict] = []
    for event_el in soup.find_all(class_="k-event"):
        parsed = _parse_event(event_el)
        if parsed is None:
            continue
        interval, event_date = parsed
        if event_date is None or event_date < today:
            continue
        raw.append({
            "date": event_date.isoformat(),
            "open": interval.open,
            "close": interval.close,
        })
    events = _merge_close_dated(raw, gap_threshold_min=15)

    return {
        "id": "mullins-ice",
        "name": "Mullins Community Ice Rink — Public Skate",
        "category": "ice",
        "location_label": "Mullins Center, UMass Amherst",
        "maps_url": "https://www.google.com/maps/search/?api=1&query=Mullins+Center+UMass+Amherst",
        "source_url": SOURCE_URL,
        "hours": {d: [] for d in DAY_ORDER},
        "events": events,
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
