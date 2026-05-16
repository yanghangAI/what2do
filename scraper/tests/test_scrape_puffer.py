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


def test_ocr_parse_text_extracts_per_beach_numbers():
    from scraper.ocr_puffer import parse_ocr_text
    sample = (
        "Puffer's Pond Water Quality Test\n"
        "Date: 08/26/2025\n"
        "North Beach   45 MPN/100ml\n"
        "South Beach   210 MPN/100ml\n"
        "Standard: 235 MPN/100ml single sample\n"
    )
    r = parse_ocr_text(sample)
    assert r["north"] == 45.0
    assert r["south"] == 210.0


def test_ocr_parse_text_returns_none_when_no_match():
    from scraper.ocr_puffer import parse_ocr_text
    assert parse_ocr_text("Lorem ipsum no beaches here") is None


def test_parse_latest_report_picks_most_recent():
    r = parse_latest_report(ARCHIVE_FIXTURE.read_text())
    assert r is not None
    assert r["date"] == "2025-08-26"
    assert "ADID=18329" in r["url"]
    assert "08-26-2025" in r["title"]
