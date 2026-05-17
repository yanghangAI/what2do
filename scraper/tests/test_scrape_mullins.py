from datetime import date
from pathlib import Path
from scraper.scrape_mullins import parse_mullins_html
from scraper.models import Interval

FIXTURE = Path(__file__).parent / "fixtures" / "mullins.html"
# Fixture has events on Wed 2026-05-13 and Thu 2026-05-14. Anchor "today"
# before those dates so the past-event filter doesn't drop them.
TODAY = date(2026, 5, 12)


def _parse(html):
    return parse_mullins_html(html, today=TODAY)


def test_returns_facility_record():
    result = _parse(FIXTURE.read_text())
    assert result["id"] == "mullins-ice"
    assert result["category"] == "ice"
    # New dated-events model — hours is always emitted as empty for
    # frontend backward compat; real schedule lives under "events".
    assert "events" in result
    assert all(v == [] for v in result["hours"].values())


def test_finds_at_least_one_public_skate_slot():
    result = _parse(FIXTURE.read_text())
    assert len(result["events"]) >= 1


def test_time_format_is_24h_hhmm():
    import re
    result = _parse(FIXTURE.read_text())
    for ev in result["events"]:
        assert re.fullmatch(r"\d{2}:\d{2}", ev["open"])
        assert re.fullmatch(r"\d{2}:\d{2}", ev["close"])


def test_parses_specific_events_from_week_fixture():
    """Fixture has 3 Public Skating events: Wed 12:10-1:50 (May 13),
    Thu 18:30-19:20 + 19:30-20:20 (May 14). The two Thu events have a
    10-min gap so they merge into one 18:30-20:20 interval."""
    result = _parse(FIXTURE.read_text())
    evs = result["events"]
    assert {"date": "2026-05-13", "open": "12:10", "close": "13:50"} in evs
    assert {"date": "2026-05-14", "open": "18:30", "close": "20:20"} in evs


def test_ignores_grid_axis_labels():
    """Kendo grid axis labels like 12:00 AM, 1:00 AM are not events."""
    result = _parse(FIXTURE.read_text())
    for ev in result["events"]:
        assert not (ev["open"] == "00:00" and ev["close"] == "01:00")


def test_merges_close_intervals():
    """6:30-7:20 + 7:30-8:20 (10-min gap) should collapse to 6:30-8:20."""
    result = _parse(FIXTURE.read_text())
    thu_events = [e for e in result["events"] if e["date"] == "2026-05-14"]
    # Expect one merged interval rather than two.
    assert {"date": "2026-05-14", "open": "18:30", "close": "20:20"} in thu_events
    assert {"date": "2026-05-14", "open": "18:30", "close": "19:20"} not in thu_events


def test_does_not_merge_far_intervals():
    from scraper.scrape_mullins import _merge_close_intervals
    a = Interval("09:00", "10:00")
    b = Interval("11:00", "12:00")  # 60-min gap
    assert _merge_close_intervals([a, b], 15) == [a, b]


def test_drops_events_whose_date_has_passed():
    """Events on dates before `today` should not be returned."""
    result = parse_mullins_html(FIXTURE.read_text(), today=date(2026, 5, 15))
    # Wed May 13 and Thu May 14 are both before today.
    assert result["events"] == []
