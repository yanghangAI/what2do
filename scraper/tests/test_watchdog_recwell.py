# scraper/tests/test_watchdog_recwell.py
from pathlib import Path

from scraper.scrape_recwell import _parse_schedule_line
from scraper.watchdog import decide, hours_empty, hours_equal, intervals_from_dict
from scraper.models import Interval, DAYS

FIXTURE = Path(__file__).parent / "fixtures" / "rockwell_no_colon.txt"


def _parse_section(text):
    """Mimic scrape_recwell's per-facility line parsing on a section's text."""
    hours = {d: [] for d in DAYS}
    for raw in text.splitlines():
        days, intervals = _parse_schedule_line(raw.strip())
        for d in days:
            hours[d].extend(intervals)
    return hours


def test_parser_yields_empty_on_colonless_rockwell():
    parsed = _parse_section(FIXTURE.read_text())
    assert hours_empty(parsed), "regression guard: colon-less format parses empty"


def test_watchdog_backfills_rockwell_from_gemini():
    parsed = _parse_section(FIXTURE.read_text())          # empty
    gemini = {d: [{"open": "16:00", "close": "20:00"}] for d in DAYS}
    dec = decide(
        "rockwell-climbing", parsed, gemini,
        is_empty=hours_empty, equals=hours_equal,
    )
    assert dec.used_backup is True
    assert dec.divergence is not None
    shipped = intervals_from_dict(dec.shipped)
    assert shipped["mon"] == [Interval("16:00", "20:00")]
    assert shipped["sun"] == [Interval("16:00", "20:00")]
