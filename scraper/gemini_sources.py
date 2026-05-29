"""Per-source Gemini schemas, prompts, and thin extract functions.

Each function takes the SAME fetched text the deterministic parser saw and
returns a dict shaped like that parser's output, or ``None`` if Gemini is
unavailable. Source-specific knowledge lives here; the generic REST call lives
in gemini_extract and the compare/decide logic in watchdog.
"""
from __future__ import annotations

from scraper import gemini_extract
from scraper.models import DAYS

_INTERVAL = {
    "type": "object",
    "properties": {"open": {"type": "string"}, "close": {"type": "string"}},
    "required": ["open", "close"],
}
HOURS_SCHEMA = {
    "type": "object",
    "properties": {d: {"type": "array", "items": _INTERVAL} for d in DAYS},
}
_HOURS_PROMPT = (
    "You are reading the weekly operating hours for a SINGLE UMass recreation "
    "facility. Return per-weekday open/close intervals using 24-hour HH:MM "
    "times (e.g. '4pm - 8pm' -> open '16:00', close '20:00'). A day with no "
    "listed hours is closed: return an empty array for it. Keys: "
    + ", ".join(DAYS) + "."
)


def gemini_facility_hours(section_text):
    """Extract one facility's weekly hours from its section text."""
    return gemini_extract.extract(
        section_text, schema=HOURS_SCHEMA, instructions=_HOURS_PROMPT,
    )
