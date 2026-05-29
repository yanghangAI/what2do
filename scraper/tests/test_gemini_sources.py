import scraper.gemini_sources as gs


def test_gemini_facility_hours_passes_through_extract(monkeypatch):
    captured = {}

    def fake_extract(text, *, schema, instructions, **kw):
        captured["schema"] = schema
        captured["text"] = text
        return {"mon": [{"open": "16:00", "close": "20:00"}]}

    monkeypatch.setattr(gs.gemini_extract, "extract", fake_extract)
    out = gs.gemini_facility_hours("Monday 4pm - 8pm")
    assert out == {"mon": [{"open": "16:00", "close": "20:00"}]}
    assert captured["text"] == "Monday 4pm - 8pm"
    assert "mon" in captured["schema"]["properties"]


def test_gemini_facility_hours_returns_none_when_extract_none(monkeypatch):
    monkeypatch.setattr(gs.gemini_extract, "extract", lambda *a, **k: None)
    assert gs.gemini_facility_hours("whatever") is None
