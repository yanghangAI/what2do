from pathlib import Path
from scraper.scrape_mullins import parse_mullins_html

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
