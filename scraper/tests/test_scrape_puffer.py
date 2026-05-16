from pathlib import Path

from scraper.scrape_puffer import parse_puffer_html

FIXTURE = Path(__file__).parent / "fixtures" / "puffer.html"


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
