from scraper.scrape_schedule import parse_schedule_text

SAMPLE = """\
Wed, May 13 2026
3:00 PM 15 minute Climbing Orientation Offered Every Hour
4:00 PM Slow Flow Yoga 60
4:00 PM Barre 45
4:15 PM Rhythm Ride 45
5:00 PM Sculpt 60
Thu, May 14 2026
7:30 AM Power Yoga 60
8:15 AM Pilates 60
"""


def test_groups_by_date_and_filters_orientation():
    days = parse_schedule_text(SAMPLE)
    assert len(days) == 2
    wed = days[0]
    assert wed["date"] == "2026-05-13"
    assert wed["weekday"] == "Wed"
    names = [e["name"] for e in wed["events"]]
    assert "Slow Flow Yoga 60" in names
    assert "Barre 45" in names
    assert all("orientation" not in n.lower() for n in names)
    thu = days[1]
    assert thu["date"] == "2026-05-14"
    assert thu["events"][0]["name"] == "Power Yoga 60"
    assert thu["events"][0]["time"] == "07:30"


def test_events_sorted_within_day():
    days = parse_schedule_text(SAMPLE)
    wed = days[0]
    times = [e["time"] for e in wed["events"]]
    assert times == sorted(times)


def test_24h_time_conversion():
    days = parse_schedule_text(SAMPLE)
    wed = days[0]
    times = {e["name"]: e["time"] for e in wed["events"]}
    assert times["Slow Flow Yoga 60"] == "16:00"
    assert times["Sculpt 60"] == "17:00"
