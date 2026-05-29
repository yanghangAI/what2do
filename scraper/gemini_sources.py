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


_SCHEDULE_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "date": {"type": "string"},
            "weekday": {"type": "string"},
            "events": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"time": {"type": "string"}, "name": {"type": "string"}},
                    "required": ["time", "name"],
                },
            },
        },
        "required": ["date", "weekday", "events"],
    },
}
_SCHEDULE_PROMPT = (
    "You are reading the UMass RecWell daily 'Upcoming Classes' widget. Return a "
    "list of days, each with an ISO date (YYYY-MM-DD), a 3-letter weekday "
    "(Mon..Sun), and its events. Each event has a 24-hour HH:MM time and the "
    "class name exactly as shown. Keep every event, including orientations."
)


def gemini_schedule(text):
    return gemini_extract.extract(
        text, schema=_SCHEDULE_SCHEMA, instructions=_SCHEDULE_PROMPT,
    )


_MULLINS_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "date": {"type": "string"},
            "open": {"type": "string"},
            "close": {"type": "string"},
        },
        "required": ["date", "open", "close"],
    },
}
_MULLINS_PROMPT = (
    "You are reading the Mullins Community Ice Center weekly schedule. Return "
    "only PUBLIC SKATING sessions as a list of {date (YYYY-MM-DD), open, close} "
    "using 24-hour HH:MM times. Ignore non-public-skate events."
)


def gemini_mullins(text):
    return gemini_extract.extract(
        text, schema=_MULLINS_SCHEMA, instructions=_MULLINS_PROMPT,
    )
