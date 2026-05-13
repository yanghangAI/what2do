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
