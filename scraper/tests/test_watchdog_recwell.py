# scraper/tests/test_watchdog_recwell.py
from pathlib import Path

from scraper.scrape_recwell import _parse_schedule_line
from scraper.watchdog import decide, hours_empty, hours_equal
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


def test_parser_parses_colonless_rockwell_natively():
    """Root cause fixed: the colon-less 'Monday 4pm - 8pm' format now parses,
    so RockWell no longer needs a Gemini backfill."""
    parsed = _parse_section(FIXTURE.read_text())
    assert not hours_empty(parsed)
    for d in DAYS:
        assert parsed[d] == [Interval("16:00", "20:00")], d


def test_watchdog_agrees_when_parser_matches_gemini():
    """With the parser fixed, parser and Gemini agree on RockWell -> no
    divergence, no backfill (the source goes green)."""
    parsed = _parse_section(FIXTURE.read_text())          # now 4pm-8pm daily
    gemini = {d: [{"open": "16:00", "close": "20:00"}] for d in DAYS}
    dec = decide(
        "rockwell-climbing", parsed, gemini,
        is_empty=hours_empty, equals=hours_equal,
    )
    assert dec.used_backup is False
    assert dec.divergence is None
