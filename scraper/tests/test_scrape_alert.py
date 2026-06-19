from pathlib import Path
from datetime import date

from scraper.scrape_alert import (
    mask_pre_start_days,
    merge_alert_state,
    parse_alert_html,
    parse_alert_overrides,
    parse_holidays,
)

FIXTURE = Path(__file__).parent / "fixtures" / "recwell_homepage.html"


def test_extracts_alert_with_summer_hours():
    text = parse_alert_html(FIXTURE.read_text())
    assert text is not None
    assert text.startswith("FACILITIES ALERT")
    assert "Summer Hours" in text
    assert "Memorial Day" in text
    assert "Boyden Pool" in text
    assert "RockWell" in text


def test_extracts_alert_when_old_memorial_day_text_is_gone():
    html = """
    <div>
      <p>Check out our new <a>YouTube Channel!</a></p>
      <h4><u>FACILITIES ALERT:</u> Summer Hours - Check below for updated hours.</h4>
      <p>
        All RecWell Facilities will be closed on the following Holidays:<br>
        Friday, June 19, 2026 – Juneteenth<br>
        Friday, July 3, 2026 – Independence Day (observed)<br>
        <strong>Recreation Center | Summer Hours:</strong><br>
        Monday–Friday | 7:00am–7:00pm<br>
      </p>
    </div>
    """
    text = parse_alert_html(html)
    assert text is not None
    assert "Juneteenth" in text
    assert {"date": "2026-06-19", "name": "Juneteenth"} in parse_holidays(text)


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


def test_mask_pre_start_keeps_days_at_or_after_start():
    # Today Sat 2026-05-16, start Wed 2026-05-20.
    today = date(2026, 5, 16)
    override = {d: [{"open": "11:00", "close": "13:00"}] for d in
                ["mon", "tue", "wed", "thu", "fri"]}
    override["sat"] = []
    override["sun"] = []
    masked = mask_pre_start_days(today, override, "2026-05-20")
    # Sat (today), Sun (May 17), Mon (May 18), Tue (May 19) are all before
    # start → empty. Wed (May 20), Thu, Fri are at/after start → keep.
    assert masked["sat"] == []
    assert masked["sun"] == []
    assert masked["mon"] == []
    assert masked["tue"] == []
    assert masked["wed"] == [{"open": "11:00", "close": "13:00"}]
    assert masked["thu"] == [{"open": "11:00", "close": "13:00"}]
    assert masked["fri"] == [{"open": "11:00", "close": "13:00"}]


def test_mask_pre_start_when_no_day_reaches_start_yet():
    # Today Sat 2026-05-16, start Tue 2026-05-26 — no day-of-week in the
    # next 7 days reaches start, so everything is masked.
    today = date(2026, 5, 16)
    override = {d: [{"open": "16:00", "close": "20:00"}] for d in
                ["mon","tue","wed","thu","fri","sat","sun"]}
    masked = mask_pre_start_days(today, override, "2026-05-26")
    assert all(masked[d] == [] for d in masked)


def test_parse_alert_overrides_extracts_hicks_specific_start_date():
    text = (
        "FACILITIES ALERT:\n"
        "Hicks Pool will open for summer hours on Thursday, May 21, 2026, due to electrical work.\n"
        "Summer Hours for the Recreation Center and Boyden Pool will begin on Wednesday, May 20, 2026.\n"
        "Pools | Summer Hours:\n"
        "Boyden Pool\n"
        "Monday - Friday | 11:00am - 1:00pm\n"
        "Hicks Pool - will open Thursday, May 21, 2026 for the summer - delay due to electrical work.\n"
        "Monday - Friday | 7:00am - 9:00am & 5:00pm - 7:30pm\n"
    )
    ov = parse_alert_overrides(text)
    # Hicks block matched the schedule heading (with dash), not the announcement.
    assert ov["curry-hicks-pool"]["start_date"] == "2026-05-21"
    assert [(i.open, i.close) for i in ov["curry-hicks-pool"]["hours"]["mon"]] == [
        ("07:00", "09:00"), ("17:00", "19:30"),
    ]
    # Boyden falls back to general start_date.
    assert ov["boyden-pool"]["start_date"] == "2026-05-20"


def test_parse_alert_overrides_extracts_rockwell_schedule():
    text = (
        "FACILITIES ALERT:\n"
        "Summer Hours will begin on Wednesday, May 20, 2026.\n"
        "RockWell Summer Hours will begin on Tuesday, May 26, 2026\n"
        "Recreation Center | Summer Hours:\n"
        "Monday-Friday | 7:00am - 7:00pm\n"
        "Saturday-Sunday | CLOSED\n"
        "RockWell | Summer Hours:\n"
        "Monday - Friday | 4:00pm - 8:00pm\n"
        "Saturday & Sunday | 4:00pm - 8:00pm\n"
    )
    ov = parse_alert_overrides(text)
    rw = ov["rockwell-climbing"]
    assert rw["start_date"] == "2026-05-26"
    # 16:00-20:00 every day
    assert all(
        [(i.open, i.close) for i in rw["hours"][d]] == [("16:00", "20:00")]
        for d in ["mon","tue","wed","thu","fri","sat","sun"]
    )


def test_parse_holidays_extracts_dated_closures():
    text = (
        "FACILITIES ALERT:\n"
        "Summer Hours will begin on Wednesday, May 20, 2026.\n"
        "All RecWell Facilities will be closed on the following Holidays:\n"
        "Monday, May 25, 2026 - Memorial Day\n"
        "Friday, June 19, 2026 - Juneteenth\n"
        "Friday, July 3, 2026 - Independence Day (observed)\n"
    )
    hs = parse_holidays(text)
    assert {"date": "2026-05-25", "name": "Memorial Day"} in hs
    assert {"date": "2026-06-19", "name": "Juneteenth"} in hs
    assert {"date": "2026-07-03", "name": "Independence Day (observed)"} in hs
    assert len(hs) == 3


def test_parse_holidays_ignores_non_holiday_dates():
    text = (
        "FACILITIES ALERT:\n"
        "Summer Hours will begin on Wednesday, May 20, 2026.\n"
        "Hicks Pool opens Thursday, May 21, 2026.\n"
        # No 'Holiday' header — should return empty
    )
    assert parse_holidays(text) == []


def test_parse_holidays_handles_empty_input():
    assert parse_holidays(None) == []
    assert parse_holidays("") == []
