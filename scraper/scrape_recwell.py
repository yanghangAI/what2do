"""Scrape pool and climbing hours from the UMass RecWell facilities hours page."""
from __future__ import annotations
import re
from bs4 import BeautifulSoup, NavigableString, Tag
from scraper.models import Interval

SOURCE_URL = "https://www.umass.edu/recwell/facilities/hours-operation"

FACILITIES = [
    {
        "id": "boyden-pool",
        "name": "Boyden Pool",
        "category": "swim",
        "match": re.compile(r"Boyden", re.I),
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
        "match": re.compile(r"RockWell", re.I),
        "location_label": "Recreation Center, UMass Amherst",
        "maps_url": "https://www.google.com/maps/search/?api=1&query=UMass+Recreation+Center+Amherst",
    },
    {
        "id": "recreation-center",
        "name": "Recreation Center",
        "category": "fitness",
        "match": re.compile(r"^Recreation Center$", re.I),
        "location_label": "Recreation Center, UMass Amherst",
        "maps_url": "https://www.google.com/maps/search/?api=1&query=UMass+Recreation+Center+Amherst",
    },
    {
        "id": "mullins-tennis",
        "name": "Mullins Tennis & Pickleball Courts",
        "category": "tennis",
        "match": re.compile(r"Mullins\s+Tennis", re.I),
        "location_label": "Mullins Center, UMass Amherst",
        "maps_url": "https://www.google.com/maps/search/?api=1&query=Mullins+Center+UMass+Amherst",
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
    token = token.strip().lower().rstrip(":,").strip()
    # Normalize ampersand to comma-style handled by caller; here only single or range
    if "&" in token:
        parts = [p.strip() for p in token.split("&")]
        out = []
        for p in parts:
            out.extend(_expand_day_token(p))
        return out
    for sep in ("-", "–", "—"):
        if sep in token:
            a, b = [p.strip() for p in token.split(sep, 1)]
            if a in DAY_ALIASES and b in DAY_ALIASES:
                start = DAY_ORDER.index(DAY_ALIASES[a])
                end = DAY_ORDER.index(DAY_ALIASES[b])
                if end < start:
                    return []
                return DAY_ORDER[start : end + 1]
            return []
    if token in DAY_ALIASES:
        return [DAY_ALIASES[token]]
    return []


def _parse_schedule_line(line: str) -> tuple[list[str], list[Interval]]:
    """Parse a line like 'Monday-Friday: 11:00am - 12:30pm, 5:00pm - 8:00pm'."""
    if ":" not in line:
        return [], []
    # Split on first colon that's not within a time (i.e., first colon overall before any digit-colon-digit pattern)
    # Find first colon position that separates head from times
    # Heuristic: find the first colon that isn't immediately surrounded by digits.
    idx = -1
    for i, ch in enumerate(line):
        if ch == ":":
            left_digit = i > 0 and line[i - 1].isdigit()
            right_digit = i + 1 < len(line) and line[i + 1].isdigit()
            if not (left_digit and right_digit):
                idx = i
                break
    if idx == -1:
        return [], []
    head = line[:idx]
    rest = line[idx + 1 :]
    days = _expand_day_token(head)
    if not days:
        return [], []
    intervals: list[Interval] = []
    for chunk in re.split(r",", rest):
        iv = _parse_time_range(chunk)
        if iv:
            intervals.append(iv)
    return days, intervals


def _heading_tags() -> tuple[str, ...]:
    return ("h1", "h2", "h3", "h4")


def _section_text_after(soup: BeautifulSoup, regex: re.Pattern) -> str:
    """Return text content following the first heading matching `regex`,
    up to the next heading of equal or higher level (or any heading h1-h4)."""
    heading = None
    for tag in soup.find_all(_heading_tags()):
        if regex.search(tag.get_text(" ", strip=True) or ""):
            heading = tag
            break
    if heading is None:
        return ""
    pieces: list[str] = []
    node = heading
    while True:
        node = node.next_sibling
        while node is not None and isinstance(node, NavigableString) and not str(node).strip():
            node = node.next_sibling
        if node is None:
            # Climb up
            parent = heading.parent
            # Try to find following siblings of parent if heading is last child
            break
        if isinstance(node, Tag) and node.name in _heading_tags():
            break
        if isinstance(node, Tag):
            # Use <br> as the only line separator. Unwrap inline formatting
            # tags first so a phrase like "<u>CLOSED</u> until further notice."
            # is read as one line, not split where the <u> ends.
            from copy import copy as _copy
            local = _copy(node)
            for br in local.find_all("br"):
                br.replace_with("\n")
            for inline in local.find_all(["strong", "b", "em", "i", "u", "span", "a"]):
                inline.unwrap()
            local.smooth()  # merge adjacent NavigableStrings left by unwrap
            pieces.append(local.get_text("\n", strip=True))
        elif isinstance(node, NavigableString):
            s = str(node).strip()
            if s:
                pieces.append(s)
    return "\n".join(p for p in pieces if p)


_DATE_LINE_RE = re.compile(
    r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"jan(uary)?|feb(ruary)?|mar(ch)?|apr(il)?|may|jun(e)?|jul(y)?|"
    r"aug(ust)?|sep(tember)?|oct(ober)?|nov(ember)?|dec(ember)?)\b.*\b20\d{2}\b",
    re.I,
)


def _extract_notes(section_text: str) -> list[str]:
    """Pull human-readable notes (closures, exceptions) from a facility section.

    The page often presents a closure header followed by date lines, e.g.:
        Please Note the Hicks Pool will be CLOSED on the following dates:
        Saturday, April 4, 2026
        Saturday, April 11, 2026
    We pair the header with subsequent date-shaped lines into one note.
    Standalone date lines (no header above) are also kept so we never lose
    a closure date.
    """
    raw_lines = [
        ln.strip().strip("*").strip()
        for ln in section_text.splitlines()
        if ln.strip().strip("*").strip()
    ]
    # Drop lines that are pure schedule entries
    candidates: list[str] = []
    for line in raw_lines:
        _, ivals = _parse_schedule_line(line)
        if ivals:
            continue
        candidates.append(line)

    notes: list[str] = []
    i = 0
    while i < len(candidates):
        line = candidates[i]
        is_closure_header = bool(re.search(r"closed|closure", line, re.I))
        is_date = bool(_DATE_LINE_RE.search(line))
        if is_closure_header:
            dates: list[str] = []
            j = i + 1
            while j < len(candidates) and _DATE_LINE_RE.search(candidates[j]):
                dates.append(candidates[j])
                j += 1
            if dates:
                notes.append(line + " " + "; ".join(dates))
            else:
                notes.append(line)
            i = j
            continue
        if is_date:
            notes.append(line)
        i += 1
    return notes


_MONTHS_NUM = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
}
_DAY_DATE_RE = re.compile(
    r"(?:Mon|Tues?|Wed(?:nes)?|Thurs?|Fri|Sat(?:ur)?|Sun)(?:day)?,?\s+"
    r"(January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+(\d{1,2}),?\s+(20\d{2})",
    re.I,
)


def parse_closed_dates_from_notes(notes: list[str]) -> list[dict]:
    """Extract per-facility dated closures from human-readable notes.

    Matches patterns like:
        'Hicks Pool will be CLOSED on the following dates:
         Saturday, April 4, 2026; Saturday, April 11, 2026'
    Each note must contain a "closed" word AND one or more
    "<Weekday>, <Month> <Day>, <Year>" date references; we then map
    each date to ``{"date": ISO}``. The original note text remains in
    the notes list — this is purely a status-flip side channel.
    """
    out: list[dict] = []
    seen: set[str] = set()
    for note in notes:
        if not re.search(r"\bclosed?\b", note, re.I):
            continue
        for m in _DAY_DATE_RE.finditer(note):
            month = _MONTHS_NUM[m.group(1).lower()]
            iso = f"{m.group(3)}-{month:02d}-{int(m.group(2)):02d}"
            if iso in seen:
                continue
            seen.add(iso)
            out.append({"date": iso})
    return out


def scrape_recwell(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    results: list[dict] = []
    for fac in FACILITIES:
        text = _section_text_after(soup, fac["match"])
        hours: dict[str, list[Interval]] = {d: [] for d in DAY_ORDER}
        for raw in text.splitlines():
            line = raw.strip()
            days, intervals = _parse_schedule_line(line)
            for d in days:
                hours[d].extend(intervals)
        notes = _extract_notes(text)
        record = {
            "id": fac["id"],
            "name": fac["name"],
            "category": fac["category"],
            "location_label": fac["location_label"],
            "maps_url": fac["maps_url"],
            "source_url": SOURCE_URL,
            "hours": hours,
            "notes": notes,
        }
        closed = parse_closed_dates_from_notes(notes)
        if closed:
            record["closed_dates"] = closed
        results.append(record)
    return results
