"""Scrape the FACILITIES ALERT banner from the RecWell homepage.

The umass.edu/recwell/ landing page hosts a free-form announcement banner
("Summer Hours starting May 20...", holiday closures, etc.) that is more
current than the structured hours-of-operation page. We surface it verbatim
as a notice at the top of the site so users see it even when our scraped
hours data hasn't caught up to a schedule change.
"""
from __future__ import annotations
import re
from datetime import date, timedelta

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


# ---------- Alert-to-overrides parsing ----------

from scraper.models import Interval

DAY_ORDER = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
_DAY_TOKEN = {
    "mon": "mon", "monday": "mon",
    "tue": "tue", "tues": "tue", "tuesday": "tue",
    "wed": "wed", "weds": "wed", "wednesday": "wed",
    "thu": "thu", "thurs": "thu", "thursday": "thu",
    "fri": "fri", "friday": "fri",
    "sat": "sat", "saturday": "sat",
    "sun": "sun", "sunday": "sun",
}
_MONTHS_NUM = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}

# Facility blocks in the alert keyed by their ID in our hours data.
# Each entry: (regex matching the facility's heading line, default-start-date-key).
FACILITY_BLOCKS = [
    ("recreation-center", re.compile(r"^Recreation Center\b", re.I), "general"),
    ("boyden-pool",       re.compile(r"^Boyden Pool\b", re.I), "general"),
    # Schedule heading reads either "Hicks Pool" or "Hicks Pool - will open ...";
    # exclude the announcement sentence "Hicks Pool will open for summer ...".
    ("curry-hicks-pool",  re.compile(r"^Hicks Pool(?!\s+will\b)", re.I), "hicks"),
    # Match the schedule heading "RockWell | Summer Hours:" — not the
    # announcement sentence "RockWell Summer Hours will begin on ...".
    ("rockwell-climbing", re.compile(r"^RockWell\s*\|", re.I), "rockwell"),
]

_TIME = r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)"
_RANGE_RE = re.compile(rf"{_TIME}\s*[-–]\s*{_TIME}", re.I)
_DAY_RANGE_RE = re.compile(
    r"(Monday|Mon|Tuesday|Tue|Tues|Wednesday|Wed|Thursday|Thu|Thurs|Friday|Fri|Saturday|Sat|Sunday|Sun)"
    r"\s*[-–&]\s*"
    r"(Monday|Mon|Tuesday|Tue|Tues|Wednesday|Wed|Thursday|Thu|Thurs|Friday|Fri|Saturday|Sat|Sunday|Sun)",
    re.I,
)
_SINGLE_DAY_RE = re.compile(
    r"\b(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b", re.I,
)


def _to_24h(h: str, m: str | None, ampm: str) -> str:
    hour = int(h)
    minute = int(m) if m else 0
    if ampm.lower() == "am":
        hour = 0 if hour == 12 else hour
    else:
        hour = 12 if hour == 12 else hour + 12
    return f"{hour:02d}:{minute:02d}"


def _expand_days(text: str) -> list[str]:
    """Pick out day tokens from a string like 'Monday-Friday' or 'Sat & Sun'."""
    m = _DAY_RANGE_RE.search(text)
    if m:
        a = _DAY_TOKEN[m.group(1).lower()]
        b = _DAY_TOKEN[m.group(2).lower()]
        i, j = DAY_ORDER.index(a), DAY_ORDER.index(b)
        if i <= j:
            return DAY_ORDER[i : j + 1]
        return [a, b]
    days = []
    for sm in _SINGLE_DAY_RE.finditer(text):
        days.append(_DAY_TOKEN[sm.group(1).lower()])
    return days


def _parse_intervals(text: str) -> list[Interval]:
    intervals: list[Interval] = []
    for m in _RANGE_RE.finditer(text):
        intervals.append(Interval(
            open=_to_24h(m.group(1), m.group(2), m.group(3)),
            close=_to_24h(m.group(4), m.group(5), m.group(6)),
        ))
    return intervals


def _find_semester_close_date(text: str) -> str | None:
    """Parse 'will close for the semester at ... on <Day>, <Month> <D>, <Year>'."""
    m = re.search(
        r"close for the semester[^.]{0,80}?on\s+\w+,?\s*"
        r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),\s+(20\d{2})",
        text, re.I,
    )
    if not m:
        return None
    return f"{m.group(3)}-{_MONTHS_NUM[m.group(1).lower()]:02d}-{int(m.group(2)):02d}"


def _find_start_dates(text: str) -> dict[str, str]:
    """Return {key: ISO date} for the alert's start-date phrases.

    'general' = the main "Summer Hours will begin on <date>" sentence.
    'rockwell', 'hicks' = facility-specific overrides if present, else fall
    back to general.
    """
    out: dict[str, str] = {}
    month_pat = (
        r"(January|February|March|April|May|June|July|August|September|"
        r"October|November|December)\s+(\d{1,2}),\s+(20\d{2})"
    )

    def _iso(m: re.Match) -> str:
        return f"{m.group(3)}-{_MONTHS_NUM[m.group(1).lower()]:02d}-{int(m.group(2)):02d}"

    specific = {
        "rockwell": re.compile(
            rf"RockWell[^.]{{0,80}}?begin\s+on\s+\w+,?\s*{month_pat}", re.I,
        ),
        "hicks": re.compile(
            rf"Hicks\s+Pool[^.]{{0,120}}?(?:open|begin)[^.]{{0,80}}?on\s+\w+,?\s*{month_pat}",
            re.I,
        ),
    }
    for key, pat in specific.items():
        m = pat.search(text)
        if m:
            out[key] = _iso(m)
    general_re = re.compile(rf"Summer Hours[^.]{{0,80}}?begin\s+on\s+\w+,?\s*{month_pat}", re.I)
    gm = general_re.search(text)
    if gm:
        out["general"] = _iso(gm)
        out.setdefault("rockwell", out["general"])
        out.setdefault("hicks", out["general"])
    return out


def _extract_block(lines: list[str], heading_re: re.Pattern) -> list[str]:
    """Lines belonging to a facility block: from the heading until the next
    facility heading or a blank line followed by another section heading."""
    start = None
    for i, ln in enumerate(lines):
        if heading_re.search(ln):
            start = i
            break
    if start is None:
        return []
    out = [lines[start]]
    for ln in lines[start + 1:]:
        if any(other.search(ln) for _, other, _ in FACILITY_BLOCKS if not other.search(lines[start])):
            # next facility starts (excluding our own heading)
            if any(other.search(ln) for fid, other, _ in FACILITY_BLOCKS if not heading_re.search(ln)):
                break
        if "Pools | Summer Hours" in ln and "Pools | Summer Hours" not in lines[start]:
            break
        out.append(ln)
        if len(out) > 8:
            break
    return out


def parse_alert_overrides(text: str) -> dict[str, dict]:
    """Parse alert text into per-facility hour overrides.

    Returns: {facility_id: {start_date: ISO, hours: {day: [Interval]}}}.
    Only includes facilities for which we successfully parsed at least one
    schedule line.
    """
    if not text:
        return {}
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    starts = _find_start_dates(text)
    semester_close = _find_semester_close_date(text)
    out: dict[str, dict] = {}
    for fid, heading_re, start_key in FACILITY_BLOCKS:
        block = _extract_block(lines, heading_re)
        if not block:
            continue
        hours: dict[str, list[Interval]] = {d: [] for d in DAY_ORDER}
        # Each line in the block (after the heading) may include a day pattern
        # and zero or more time ranges. CLOSED lines mean those days are empty.
        # "Saturday–Sunday |" + next line "CLOSED" -> handle by joining with following.
        joined: list[str] = []
        i = 0
        while i < len(block):
            line = block[i]
            # If the line ends with "|" or just has a day range without times
            # and the next line is a time/CLOSED token, merge them.
            if i + 1 < len(block) and (line.rstrip().endswith("|") or
                                        (_DAY_RANGE_RE.search(line) and not _RANGE_RE.search(line) and not re.search(r"closed", line, re.I))):
                joined.append(line + " " + block[i + 1])
                i += 2
            else:
                joined.append(line)
                i += 1
        for line in joined:
            days = _expand_days(line)
            if not days:
                continue
            intervals = _parse_intervals(line)
            is_closed = bool(re.search(r"\bclosed\b", line, re.I)) and not intervals
            if not intervals and not is_closed:
                continue
            for d in days:
                if intervals:
                    for iv in intervals:
                        if iv not in hours[d]:
                            hours[d].append(iv)
                # closed -> leave list empty
        # Only emit if we actually got SOME schedule info
        if any(hours[d] for d in DAY_ORDER) or any(
            re.search(r"closed", ln, re.I) for ln in joined if _expand_days(ln)
        ):
            out[fid] = {
                "start_date": starts.get(start_key) or starts.get("general"),
                "closed_from": semester_close,
                "hours": hours,
            }
    return out


def mask_pre_start_days(
    today_dt: date, override_hours: dict, start_iso: str,
) -> dict:
    """Empty out day-of-week slots whose next calendar occurrence falls
    before ``start_iso``. Slots at/after ``start_iso`` keep the override
    hours, so the frontend can still walk forward to show
    "opens <day-of-week>" for the first post-gap day.
    """
    start_d = date.fromisoformat(start_iso)
    out: dict[str, list] = {}
    today_idx = today_dt.weekday()  # Mon=0..Sun=6
    for i, d in enumerate(DAY_ORDER):
        delta = (i - today_idx) % 7
        occurs = today_dt + timedelta(days=delta)
        out[d] = [] if occurs < start_d else list(override_hours.get(d, []))
    return out


_HOLIDAY_RE = re.compile(
    r"(?:Mon|Tues?|Wed(?:nes)?|Thurs?|Fri|Sat(?:ur)?|Sun)(?:day)?,?\s+"
    r"(January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+(\d{1,2}),\s+(20\d{2})"
    r"\s*[-–]\s*([^\n]+)",
    re.I,
)


def parse_holidays(text: str | None) -> list[dict]:
    """Pull dated holiday closures from the alert.

    Matches lines like 'Monday, May 25, 2026 - Memorial Day'. Returns
    ``[{"date": ISO, "name": str}, ...]``. Limits the search to the
    region after a 'Holiday' header so unrelated dated lines (e.g. the
    semester-close announcement) don't get picked up.
    """
    if not text:
        return []
    lower = text.lower()
    idx = lower.find("holiday")
    region = text[idx:] if idx >= 0 else text
    out: list[dict] = []
    for m in _HOLIDAY_RE.finditer(region):
        month = _MONTHS_NUM[m.group(1).lower()]
        iso = f"{m.group(3)}-{month:02d}-{int(m.group(2)):02d}"
        name = m.group(4).strip().rstrip(".").strip()
        if iso not in [h["date"] for h in out]:
            out.append({"date": iso, "name": name})
    return out


def merge_alert_state(
    current_overrides: dict[str, dict],
    prev_state: dict[str, dict] | None,
) -> tuple[dict[str, dict], dict[str, dict]]:
    """Carry forward ``closed_from`` from a previous run when the current alert
    no longer mentions it.

    UMass tends to edit the semester-close sentence out of the alert banner
    once that date has passed, which makes ``closed_from`` unparseable during
    the transition gap between the close date and the announced summer-start
    date. As long as ``start_date`` for a given facility matches the previous
    run, we trust the previously-parsed ``closed_from``.

    Returns ``(resolved_overrides, new_state_to_persist)``.
    """
    prev_state = prev_state or {}
    resolved: dict[str, dict] = {}
    new_state: dict[str, dict] = {}
    for fid, ov in current_overrides.items():
        sd = ov.get("start_date")
        cf = ov.get("closed_from")
        prev = prev_state.get(fid) or {}
        if cf is None and sd and prev.get("start_date") == sd and prev.get("closed_from"):
            cf = prev["closed_from"]
        new_ov = dict(ov)
        new_ov["closed_from"] = cf
        resolved[fid] = new_ov
        if sd:
            new_state[fid] = {"start_date": sd, "closed_from": cf}
    return resolved, new_state
