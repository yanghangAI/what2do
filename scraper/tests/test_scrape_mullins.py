from pathlib import Path
from scraper.scrape_mullins import parse_mullins_html
from scraper.models import Interval

FIXTURE = Path(__file__).parent / "fixtures" / "mullins.html"


def test_returns_facility_record():
    result = parse_mullins_html(FIXTURE.read_text())
    assert result["id"] == "mullins-ice"
    assert result["category"] == "ice"
    assert set(result["hours"].keys()) == {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}


def test_finds_at_least_one_public_skate_slot():
    result = parse_mullins_html(FIXTURE.read_text())
    total_intervals = sum(len(v) for v in result["hours"].values())
    assert total_intervals >= 1, "Expected at least one Public Skate slot in the fixture"


def test_time_format_is_24h_hhmm():
    import re
    result = parse_mullins_html(FIXTURE.read_text())
    for intervals in result["hours"].values():
        for iv in intervals:
            assert re.fullmatch(r"\d{2}:\d{2}", iv.open)
            assert re.fullmatch(r"\d{2}:\d{2}", iv.close)


def test_parses_specific_events_from_week_fixture():
    """The committed fixture has 3 Public Skating events: Wed 12:10-1:50,
    Thu 18:30-19:20, Thu 19:30-20:20. This pins the parser against real DOM."""
    result = parse_mullins_html(FIXTURE.read_text())
    assert Interval("12:10", "13:50") in result["hours"]["wed"]
    assert Interval("18:30", "19:20") in result["hours"]["thu"]
    assert Interval("19:30", "20:20") in result["hours"]["thu"]


def test_ignores_grid_axis_labels():
    """Times like 12:00 AM, 1:00 AM appear as Kendo scheduler axis labels but are
    NOT events. The parser must only emit intervals from .k-event elements."""
    result = parse_mullins_html(FIXTURE.read_text())
    for intervals in result["hours"].values():
        for iv in intervals:
            assert iv != Interval("00:00", "01:00"), "Picked up grid axis label as event"
