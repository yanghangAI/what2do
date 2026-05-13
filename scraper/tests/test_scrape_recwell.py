from pathlib import Path
from scraper.scrape_recwell import scrape_recwell
from scraper.models import Interval

FIXTURE = Path(__file__).parent / "fixtures" / "recwell.html"


def test_scrape_returns_all_configured_facilities():
    html = FIXTURE.read_text()
    results = scrape_recwell(html)
    ids = {f["id"] for f in results}
    assert {"boyden-pool", "curry-hicks-pool", "rockwell-climbing", "recreation-center"} <= ids


def test_recreation_center_has_hours():
    html = FIXTURE.read_text()
    results = {f["id"]: f for f in scrape_recwell(html)}
    rec = results["recreation-center"]
    total = sum(len(v) for v in rec["hours"].values())
    assert total >= 5, "Recreation Center should have hours on at least 5 days"


def test_curry_hicks_monday_hours():
    html = FIXTURE.read_text()
    results = {f["id"]: f for f in scrape_recwell(html)}
    curry = results["curry-hicks-pool"]
    mon = curry["hours"]["mon"]
    assert Interval("11:00", "14:00") in mon
    assert Interval("17:00", "19:00") in mon


def test_climbing_weekday_hours():
    html = FIXTURE.read_text()
    results = {f["id"]: f for f in scrape_recwell(html)}
    rockwell = results["rockwell-climbing"]
    assert Interval("12:00", "22:00") in rockwell["hours"]["mon"]
    assert Interval("12:00", "22:00") in rockwell["hours"]["thu"]
    assert Interval("12:00", "20:00") in rockwell["hours"]["fri"]


def test_all_seven_days_present_even_if_closed():
    html = FIXTURE.read_text()
    results = scrape_recwell(html)
    for f in results:
        assert set(f["hours"].keys()) == {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}


def test_curry_hicks_closure_note_includes_dates():
    html = FIXTURE.read_text()
    results = {f["id"]: f for f in scrape_recwell(html)}
    notes = results["curry-hicks-pool"]["notes"]
    assert any("April 4" in n and "April 11" in n for n in notes), \
        f"Expected closure dates merged into a single note; got {notes!r}"
