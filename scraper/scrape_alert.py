"""Scrape the FACILITIES ALERT banner from the RecWell homepage.

The umass.edu/recwell/ landing page hosts a free-form announcement banner
("Summer Hours starting May 20...", holiday closures, etc.) that is more
current than the structured hours-of-operation page. We surface it verbatim
as a notice at the top of the site so users see it even when our scraped
hours data hasn't caught up to a schedule change.
"""
from __future__ import annotations
import re
import requests
from bs4 import BeautifulSoup

ALERT_URL = "https://www.umass.edu/recwell/"
ALERT_HEADING_RE = re.compile(r"FACILITIES\s+ALERT", re.I)
# Stop merging once we hit clearly unrelated content
STOP_AFTER_TOKENS = (
    "Check out our new",
    "YouTube Channel",
    "Schedules and Calendars",
    "View Hours of Operation",
    "Group Fitness Schedule",
)


def parse_alert_html(html: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    node = soup.find(string=ALERT_HEADING_RE)
    if node is None:
        return None
    # Walk up until we find an ancestor that has BOTH the holiday list and
    # per-facility hours — the headline-only h2 doesn't qualify.
    container = node
    for _ in range(15):
        container = container.parent
        if container is None:
            return None
        text = container.get_text("\n", strip=True)
        if "Memorial Day" in text and "Boyden" in text:
            break
    else:
        return None

    # Slice from "FACILITIES ALERT" onward; trim trailing chrome.
    full = container.get_text("\n", strip=True)
    start = full.find("FACILITIES ALERT")
    if start == -1:
        return None
    body = full[start:]
    for token in STOP_AFTER_TOKENS:
        idx = body.find(token, len("FACILITIES ALERT:"))
        if idx > 0:
            body = body[:idx].rstrip()

    # Normalize: collapse runs of blank lines, strip trailing whitespace
    lines = [ln.strip() for ln in body.splitlines()]
    cleaned: list[str] = []
    for ln in lines:
        if not ln:
            if cleaned and cleaned[-1] != "":
                cleaned.append("")
            continue
        cleaned.append(ln)
    while cleaned and cleaned[-1] == "":
        cleaned.pop()
    text = "\n".join(cleaned).strip()
    return text or None


def fetch_alert() -> str | None:
    r = requests.get(ALERT_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    r.raise_for_status()
    return parse_alert_html(r.text)
