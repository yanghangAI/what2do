from pathlib import Path
from scraper.scrape_alert import merge_alert_state, parse_alert_html

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


def test_merge_alert_state_carries_closed_from_when_dropped():
    # Current alert has start_date but no closed_from (UMass edited the
    # "close at 6pm on <date>" sentence out after that date passed).
    current = {
        "recreation-center": {"start_date": "2026-05-20", "closed_from": None, "hours": {}},
    }
    prev = {
        "recreation-center": {"start_date": "2026-05-20", "closed_from": "2026-05-14"},
    }
    resolved, new_state = merge_alert_state(current, prev)
    assert resolved["recreation-center"]["closed_from"] == "2026-05-14"
    assert new_state["recreation-center"] == {
        "start_date": "2026-05-20", "closed_from": "2026-05-14",
    }


def test_merge_alert_state_ignores_prev_when_start_date_changed():
    current = {"rec": {"start_date": "2026-09-01", "closed_from": None, "hours": {}}}
    prev = {"rec": {"start_date": "2026-05-20", "closed_from": "2026-05-14"}}
    resolved, _ = merge_alert_state(current, prev)
    assert resolved["rec"]["closed_from"] is None


def test_merge_alert_state_prefers_current_closed_from():
    current = {"rec": {"start_date": "2026-05-20", "closed_from": "2026-05-15", "hours": {}}}
    prev = {"rec": {"start_date": "2026-05-20", "closed_from": "2026-05-14"}}
    resolved, _ = merge_alert_state(current, prev)
    assert resolved["rec"]["closed_from"] == "2026-05-15"
