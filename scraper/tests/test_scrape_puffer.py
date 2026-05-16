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


def test_ocr_parse_text_extracts_geomeans_with_digit_fixes():
    from scraper.ocr_puffer import parse_ocr_text
    # Simulates an OCR pass with common letter/digit confusions and
    # noisy table cells around the typewritten geomean line.
    sample = (
        "Results Amherst WWTP Laboratory Use Only\n"
        "South Beach Geometric Mean of 5 most recent samples:\n"
        "Analysis | Analysis 4S.54\n"
        "\n"
        "North Beach Geometric Mean of 5 most recent samples:\n"
        "Norn ean| garbage | [4.3 |\n"
    )
    r = parse_ocr_text(sample)
    assert r["south"] == 45.54
    assert r["north"] == 4.3


def test_ocr_parse_skips_integer_only_junk_near_label():
    """When the only nearby number is an integer (e.g. '17' from a date
    column or '100' from 'MPN/100ml'), don't claim it as a reading."""
    from scraper.ocr_puffer import parse_ocr_text
    sample = (
        "North Beach Geometric Mean of 5 most recent samples:\n"
        "SmthPeal deslas| OT pee er SOS 4a 17 MPN/100\n"
    )
    r = parse_ocr_text(sample)
    assert r is None


def test_ocr_parse_returns_none_when_no_geomean_label():
    from scraper.ocr_puffer import parse_ocr_text
    assert parse_ocr_text("Lorem ipsum no beaches here") is None


def test_parse_latest_report_picks_most_recent():
    r = parse_latest_report(ARCHIVE_FIXTURE.read_text())
    assert r is not None
    assert r["date"] == "2025-08-26"
    assert "ADID=18329" in r["url"]
    assert "08-26-2025" in r["title"]
