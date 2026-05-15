from pathlib import Path
from scraper.scrape_alert import parse_alert_html

FIXTURE = Path(__file__).parent / "fixtures" / "recwell_homepage.html"


def test_extracts_alert_with_summer_hours():
    text = parse_alert_html(FIXTURE.read_text())
    assert text is not None
    assert text.startswith("FACILITIES ALERT")
    assert "Summer Hours" in text
    assert "Memorial Day" in text
    assert "Boyden Pool" in text
    assert "RockWell" in text


def test_excludes_unrelated_chrome():
    text = parse_alert_html(FIXTURE.read_text())
    assert "YouTube" not in text
    assert "View Hours of Operation" not in text


def test_returns_none_when_no_alert():
    text = parse_alert_html("<html><body><h1>nothing here</h1></body></html>")
    assert text is None
