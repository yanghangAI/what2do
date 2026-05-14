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
    Thu 18:30-19:20, Thu 19:30-20:20. The two Thu events have a 10-min gap
    so they get merged into one 18:30-20:20 interval."""
    result = parse_mullins_html(FIXTURE.read_text())
    assert Interval("12:10", "13:50") in result["hours"]["wed"]
    assert Interval("18:30", "20:20") in result["hours"]["thu"]


def test_ignores_grid_axis_labels():
    """Times like 12:00 AM, 1:00 AM appear as Kendo scheduler axis labels but are
    NOT events. The parser must only emit intervals from .k-event elements."""
    result = parse_mullins_html(FIXTURE.read_text())
    for intervals in result["hours"].values():
        for iv in intervals:
            assert iv != Interval("00:00", "01:00"), "Picked up grid axis label as event"


def test_merges_close_intervals():
    """6:30-7:20 + 7:30-8:20 (10-min gap) should collapse to 6:30-8:20."""
    result = parse_mullins_html(FIXTURE.read_text())
    thu = result["hours"]["thu"]
    assert Interval("18:30", "20:20") in thu
    # The two original intervals should be gone
    assert Interval("18:30", "19:20") not in thu
    assert Interval("19:30", "20:20") not in thu


def test_does_not_merge_far_intervals():
    from scraper.scrape_mullins import _merge_close_intervals
    a = Interval("09:00", "10:00")
    b = Interval("11:00", "12:00")  # 60-min gap
    assert _merge_close_intervals([a, b], 15) == [a, b]
