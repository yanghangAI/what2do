from pathlib import Path

from scraper.scrape_puffer import parse_latest_report, parse_puffer_html

FIXTURE = Path(__file__).parent / "fixtures" / "puffer.html"
ARCHIVE_FIXTURE = Path(__file__).parent / "fixtures" / "puffer_archive.html"


def test_parses_live_status_from_fixture():
    r = parse_puffer_html(FIXTURE.read_text())
    assert r is not None
    assert r.status == "allowed"
    assert "Swimming is allowed" in r.headline
    assert "South Beach" in r.detail and "North Beach" in r.detail
    assert r.last_updated == "2025-08-27"
    assert r.beaches == {"north": "ok", "south": "ok"}


def test_closed_status_synthetic():
    html = (
        "<html><body>"
        "<h2>water quality testing:</h2>"
        "<p><strong>Swimming is closed at Puffer's Pond. "
        "South Beach exceeds state bacteria standards.</strong></p>"
        "<p>Updated July 9, 2026.</p>"
        "</body></html>"
    )
    r = parse_puffer_html(html)
    assert r.status == "closed"
    assert r.last_updated == "2026-07-09"
    assert r.beaches["south"] == "closed"
    # North beach not explicitly mentioned; falls back to overall "closed"
    assert r.beaches["north"] == "closed"


def test_returns_none_when_heading_absent():
    assert parse_puffer_html("<html><body><h1>not the right page</h1></body></html>") is None


def test_vision_normalize_keeps_valid_numbers():
    from scraper.vision_puffer import _normalize
    r = _normalize({
        "south_sample": 141.4, "north_sample": 9.8,
        "south_geomean": 95.58, "north_geomean": 49.17,
        "test_date": "2025-08-26",
    })
    assert r["south_sample"] == 141.4 and r["north_sample"] == 9.8
    assert r["south_geomean"] == 95.58 and r["north_geomean"] == 49.17
    assert r["test_date"] == "2025-08-26"


def test_vision_normalize_drops_out_of_range_values():
    from scraper.vision_puffer import _normalize
    r = _normalize({
        "south_sample": -1, "north_sample": 999999,
        "south_geomean": None, "north_geomean": None, "test_date": None,
    })
    assert r is None


def test_vision_normalize_keeps_partial_results():
    from scraper.vision_puffer import _normalize
    r = _normalize({
        "south_sample": 141.4, "north_sample": None,
        "south_geomean": None, "north_geomean": None, "test_date": None,
    })
    assert r["south_sample"] == 141.4 and r["north_sample"] is None


def test_parse_latest_report_picks_most_recent():
    r = parse_latest_report(ARCHIVE_FIXTURE.read_text())
    assert r is not None
    assert r["date"] == "2025-08-26"
    assert "ADID=18329" in r["url"]
    assert "08-26-2025" in r["title"]
