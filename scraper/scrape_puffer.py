"""Scrape the Puffer's Pond water quality status from the Town of Amherst page.

Source: https://www.amherstma.gov/1316/Puffers-Pond

The page exposes a colored status line ("Swimming is allowed/closed at
Puffer's Pond.") followed by a detail sentence and a "Updated <date>"
footer. Testing runs weekly during the swim season (Memorial Day–Labor
Day); outside that window the page shows the stale last-result.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass

import requests
from bs4 import BeautifulSoup

SOURCE_URL = "https://www.amherstma.gov/1316/Puffers-Pond"
REPORT_URL = "https://www.amherstma.gov/Archive.aspx?AMID=234"
ARCHIVE_URL = "https://www.amherstma.gov/Archive.aspx?AMID=234"
ARCHIVE_LINK_RE = re.compile(
    r"Puffer.{0,3}s?\s*Pond[^<]{0,80}?(\d{2})-(\d{2})-(\d{4})",
    re.I,
)

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}


@dataclass
class PufferStatus:
    status: str           # "allowed" | "closed" | "unknown"
    headline: str         # short status sentence
    detail: str           # supporting sentence(s)
    last_updated: str | None  # ISO date (page "Updated <date>")
    beaches: dict[str, str]   # {"north": ..., "south": ...} each "ok" | "closed" | "unknown"
    report_url: str           # archive index URL
    latest_report: dict | None = None  # {"date": ISO, "url": ..., "title": ...}

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "headline": self.headline,
            "detail": self.detail,
            "last_updated": self.last_updated,
            "beaches": self.beaches,
            "report_url": self.report_url,
            "latest_report": self.latest_report,
        }


def _parse_updated_date(text: str) -> str | None:
    m = re.search(
        r"Updated\s+(January|February|March|April|May|June|July|August|"
        r"September|October|November|December)\s+(\d{1,2}),?\s+(20\d{2})",
        text, re.I,
    )
    if not m:
        return None
    return f"{m.group(3)}-{_MONTHS[m.group(1).lower()]:02d}-{int(m.group(2)):02d}"


def _beach_status(beach: str, headline: str, detail: str) -> str:
    """Derive ok/closed/unknown for one beach from the headline+detail text."""
    text = f"{headline} {detail}".lower()
    name = beach.lower()
    if re.search(rf"both\s+(north|south)\s+beach\s+and\s+(north|south)\s+beach\s+meet", text):
        return "ok"
    if re.search(rf"both\s+beaches\s+(meet|are\s+(open|safe))", text):
        return "ok"
    # Per-beach closure language: "<name> Beach is closed", "<name> Beach exceeds"
    near = re.search(rf"{name}\s+beach[^.]{{0,80}}", text)
    if near:
        snippet = near.group(0)
        if re.search(r"\b(closed|not\s+safe|exceeds|posted|advisory)\b", snippet):
            return "closed"
        if re.search(r"\b(open|allowed|safe|meets?\s+state)\b", snippet):
            return "ok"
    # Fall back to overall headline
    if re.search(r"\b(closed|not\s+allowed|advisory|exceeds)\b", headline.lower()):
        return "closed"
    if re.search(r"\b(allowed|open)\b", headline.lower()):
        return "ok"
    return "unknown"


def parse_puffer_html(html: str) -> PufferStatus | None:
    soup = BeautifulSoup(html, "html.parser")
    # Find the heading "water quality testing:" (case-insensitive)
    heading = soup.find(
        lambda tag: tag.name in ("h1", "h2", "h3", "h4")
        and "water quality testing" in tag.get_text(strip=True).lower()
    )
    if heading is None:
        return None
    # The next two <p> siblings hold the status and the updated-date line.
    paragraphs: list = []
    sib = heading.find_next_sibling()
    while sib and len(paragraphs) < 4:
        if getattr(sib, "name", None) == "p":
            paragraphs.append(sib)
        sib = sib.find_next_sibling()
    if not paragraphs:
        return None
    # First paragraph: split into headline (first sentence) + detail (rest)
    first_text = paragraphs[0].get_text(" ", strip=True)
    first_text = re.sub(r"\s+", " ", first_text).strip()
    parts = re.split(r"(?<=[.!?])\s+", first_text, maxsplit=1)
    headline = parts[0].strip() if parts else first_text
    detail = parts[1].strip() if len(parts) > 1 else ""

    overall = "unknown"
    hl_lower = headline.lower()
    if re.search(r"\b(closed|not\s+allowed|advisory)\b", hl_lower):
        overall = "closed"
    elif re.search(r"\b(allowed|open)\b", hl_lower):
        overall = "allowed"

    # Second paragraph (or any subsequent) likely has the "Updated ..." date
    last_updated = None
    for p in paragraphs[1:]:
        last_updated = _parse_updated_date(p.get_text(" ", strip=True))
        if last_updated:
            break
    if not last_updated:
        # Sometimes the updated date is in the first paragraph
        last_updated = _parse_updated_date(first_text)

    beaches = {
        "north": _beach_status("North", headline, detail),
        "south": _beach_status("South", headline, detail),
    }
    return PufferStatus(
        status=overall,
        headline=headline,
        detail=detail,
        last_updated=last_updated,
        beaches=beaches,
        report_url=REPORT_URL,
    )


def parse_latest_report(html: str) -> dict | None:
    """Find the most-recent test entry in the archive index page."""
    soup = BeautifulSoup(html, "html.parser")
    best = None
    for a in soup.find_all("a", href=True):
        title = a.get_text(" ", strip=True)
        if "puffer" not in title.lower():
            continue
        m = ARCHIVE_LINK_RE.search(title)
        if not m:
            continue
        mm, dd, yyyy = m.group(1), m.group(2), m.group(3)
        iso = f"{yyyy}-{mm}-{dd}"
        href = a["href"]
        if not href.startswith("http"):
            href = "https://www.amherstma.gov/" + href.lstrip("/")
        cand = {"date": iso, "url": href, "title": title}
        if best is None or cand["date"] > best["date"]:
            best = cand
    return best


def fetch_puffer(prev: dict | None = None) -> PufferStatus | None:
    """Fetch Puffer's Pond status.

    ``prev`` is the previous run's ``water_quality`` dict; when the new
    report URL matches the one we OCR'd last time we reuse those
    readings rather than re-calling Gemini. Costs zero on idle days
    (the common case off-season, when the same PDF sits for months).
    """
    r = requests.get(SOURCE_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    r.raise_for_status()
    status = parse_puffer_html(r.text)
    if status is None:
        return None
    try:
        idx = requests.get(ARCHIVE_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
        idx.raise_for_status()
        status.latest_report = parse_latest_report(idx.text)
    except Exception:
        pass
    if not (status.latest_report and status.latest_report.get("url")):
        return status
    import sys
    new_url = status.latest_report["url"]
    prev_report = (prev or {}).get("latest_report") or {}
    if prev_report.get("url") == new_url and prev_report.get("readings"):
        status.latest_report["readings"] = prev_report["readings"]
        print("puffer vision: cached (PDF unchanged)", file=sys.stderr)
        return status
    try:
        from scraper.vision_puffer import extract_readings
        pdf = requests.get(
            new_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=60,
        )
        pdf.raise_for_status()
        readings = extract_readings(pdf.content)
        if readings:
            status.latest_report["readings"] = readings
            print(f"puffer vision OK: {readings}", file=sys.stderr)
        else:
            key_set = bool(os.environ.get("GEMINI_API_KEY"))
            print(
                f"puffer vision: no readings (GEMINI_API_KEY set={key_set})",
                file=sys.stderr,
            )
    except Exception as e:
        print(f"puffer vision error: {type(e).__name__}: {e}", file=sys.stderr)
    return status
