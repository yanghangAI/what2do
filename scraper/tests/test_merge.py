import json
from pathlib import Path
from scraper.merge import merge_results
from scraper.models import HoursDoc, Interval

PREV = Path(__file__).parent / "fixtures" / "previous_hours.json"
NOW = "2026-05-13T14:00:00-04:00"


def _make_result(fid: str, name: str, category: str) -> dict:
    return {
        "id": fid, "name": name, "category": category,
        "location_label": "loc", "maps_url": "https://maps",
        "source_url": "https://src",
        "hours": {"mon": [Interval("09:00", "17:00")], "tue": [], "wed": [], "thu": [],
                   "fri": [], "sat": [], "sun": []},
        "notes": [],
    }


def test_successful_results_become_ok_facilities():
    prev = HoursDoc.from_dict(json.loads(PREV.read_text()))
    results = [("curry-hicks-pool", _make_result("curry-hicks-pool", "Curry Hicks Pool", "swim"), None)]
    doc = merge_results(results, prev, now_iso=NOW)
    f = next(f for f in doc.facilities if f.id == "curry-hicks-pool")
    assert f.scrape_status == "ok"
    assert f.last_scraped == NOW
    assert doc.last_updated == NOW


def test_failed_scrape_keeps_previous_data_marked_stale():
    prev = HoursDoc.from_dict(json.loads(PREV.read_text()))
    results = [("curry-hicks-pool", None, RuntimeError("boom"))]
    doc = merge_results(results, prev, now_iso=NOW)
    f = next(f for f in doc.facilities if f.id == "curry-hicks-pool")
    assert f.scrape_status == "stale"
    assert f.last_scraped == "2026-05-10T08:00:00-04:00"
    assert f.hours["mon"] == [Interval("11:00", "14:00")]


def test_failed_scrape_with_no_prior_data_is_failed():
    results = [("new-facility", None, RuntimeError("boom"))]
    doc = merge_results(results, prev=None, now_iso=NOW)
    f = next(f for f in doc.facilities if f.id == "new-facility")
    assert f.scrape_status == "failed"
    assert all(v == [] for v in f.hours.values())


def test_last_updated_only_advances_when_any_succeeded():
    prev = HoursDoc.from_dict(json.loads(PREV.read_text()))
    results = [("curry-hicks-pool", None, RuntimeError("boom"))]
    doc = merge_results(results, prev, now_iso=NOW)
    assert doc.last_updated == "2026-05-10T08:00:00-04:00"
