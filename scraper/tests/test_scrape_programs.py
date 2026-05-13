from pathlib import Path
from scraper.scrape_programs import parse_programs_html

FIX_CLIMB = Path(__file__).parent / "fixtures" / "programs_climbing.html"
FIX_FIT = Path(__file__).parent / "fixtures" / "programs_fitness.html"


def test_climbing_excludes_orientation():
    items = parse_programs_html(FIX_CLIMB.read_text(), "climbing")
    names = [i["name"] for i in items]
    assert all("orientation" not in n.lower() for n in names), names
    assert "Boulder Brawl" in names
    assert "Intro to Climbing" in names


def test_fitness_strips_icon_and_price():
    items = parse_programs_html(FIX_FIT.read_text(), "fitness")
    names = [i["name"] for i in items]
    assert "Pilates 60" in names
    assert "Zumba 60" in names
    for n in names:
        assert "$" not in n
        assert not n.startswith("fitness_center")


def test_items_have_required_fields():
    items = parse_programs_html(FIX_CLIMB.read_text(), "climbing")
    for i in items:
        assert i["category"] == "climbing"
        assert i["signup_required"] is True
        assert i["url"].startswith("https://recwell.umass.edu")
        assert i["id"].startswith("climbing-")
