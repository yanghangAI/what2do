from scraper.models import Facility, Interval, Location, HoursDoc


def test_interval_round_trip():
    i = Interval(open="09:00", close="17:00")
    assert i.to_dict() == {"open": "09:00", "close": "17:00"}
    assert Interval.from_dict({"open": "09:00", "close": "17:00"}) == i


def test_facility_to_dict_has_all_seven_days():
    f = Facility(
        id="x",
        name="X",
        category="swim",
        location=Location(label="loc", maps_url="https://maps"),
        source_url="https://src",
        hours={"mon": [Interval("09:00", "17:00")]},
        notes=[],
        scrape_status="ok",
        last_scraped="2026-05-13T14:00:00-04:00",
    )
    d = f.to_dict()
    for day in ("mon", "tue", "wed", "thu", "fri", "sat", "sun"):
        assert day in d["hours"]
    assert d["hours"]["mon"] == [{"open": "09:00", "close": "17:00"}]
    assert d["hours"]["tue"] == []


def test_hoursdoc_round_trip():
    doc = HoursDoc(
        last_updated="2026-05-13T14:00:00-04:00",
        timezone="America/New_York",
        facilities=[
            Facility(
                id="x", name="X", category="swim",
                location=Location(label="l", maps_url="https://m"),
                source_url="https://s",
                hours={}, notes=["closed Fri"],
                scrape_status="ok",
                last_scraped="2026-05-13T14:00:00-04:00",
            )
        ],
    )
    restored = HoursDoc.from_dict(doc.to_dict())
    assert restored == doc
