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


def test_parse_closed_dates_from_notes_picks_up_dated_closures():
    from scraper.scrape_recwell import parse_closed_dates_from_notes
    notes = [
        "Please Note the Hicks Pool will be CLOSED on the following dates: "
        "Saturday, April 4, 2026; Saturday, April 11, 2026",
    ]
    cd = parse_closed_dates_from_notes(notes)
    assert {"date": "2026-04-04"} in cd
    assert {"date": "2026-04-11"} in cd
    assert len(cd) == 2


def test_parse_closed_dates_ignores_notes_without_closed_word():
    from scraper.scrape_recwell import parse_closed_dates_from_notes
    notes = ["Open from Saturday, April 4, 2026 onward."]
    assert parse_closed_dates_from_notes(notes) == []


def test_parse_closed_dates_handles_empty():
    from scraper.scrape_recwell import parse_closed_dates_from_notes
    assert parse_closed_dates_from_notes([]) == []


# --- root-cause parser fixes: colon-less days and '&' interval separator ---
from scraper.scrape_recwell import _parse_schedule_line


def test_parse_schedule_line_colonless_single_day():
    days, ivals = _parse_schedule_line("Monday 4pm - 8pm")
    assert days == ["mon"]
    assert ivals == [Interval("16:00", "20:00")]


def test_parse_schedule_line_ampersand_two_intervals():
    days, ivals = _parse_schedule_line(
        "Monday - Friday: 7:00am - 9:00am & 5:00pm - 7:30pm"
    )
    assert days == ["mon", "tue", "wed", "thu", "fri"]
    assert Interval("07:00", "09:00") in ivals
    assert Interval("17:00", "19:30") in ivals
    assert len(ivals) == 2


def test_parse_schedule_line_comma_still_works():
    days, ivals = _parse_schedule_line("Saturday: 11:00am - 1:00pm, 3:00pm - 5:00pm")
    assert days == ["sat"]
    assert ivals == [Interval("11:00", "13:00"), Interval("15:00", "17:00")]


def test_parse_schedule_line_closed_line_still_parses_days():
    days, ivals = _parse_schedule_line("Saturday & Sunday: CLOSED")
    assert set(days) == {"sat", "sun"}
    assert ivals == []


def test_parse_schedule_line_note_returns_empty():
    days, ivals = _parse_schedule_line(
        "Please note the pool will be CLOSED on the following dates:"
    )
    assert days == [] and ivals == []
