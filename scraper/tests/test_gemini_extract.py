import json
import scraper.gemini_extract as gx

SCHEMA = {"type": "object", "properties": {"x": {"type": "string"}}}


def _fake_response(status, payload=None, text=""):
    class R:
        status_code = status
        def json(self):
            return payload
    r = R()
    r.text = text
    return r


def test_returns_parsed_json_on_200(monkeypatch):
    payload = {"candidates": [{"content": {"parts": [{"text": json.dumps({"x": "ok"})}]}}]}
    monkeypatch.setattr(gx.requests, "post", lambda *a, **k: _fake_response(200, payload))
    out = gx.extract("hello", schema=SCHEMA, instructions="do it", api_key="k")
    assert out == {"x": "ok"}


def test_returns_none_without_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    out = gx.extract("hello", schema=SCHEMA, instructions="do it")
    assert out is None


def test_returns_none_on_persistent_error(monkeypatch):
    monkeypatch.setattr(gx.requests, "post", lambda *a, **k: _fake_response(403, text="nope"))
    out = gx.extract("hello", schema=SCHEMA, instructions="do it", api_key="k", models=("m",))
    assert out is None


def test_returns_none_on_bad_json(monkeypatch):
    payload = {"candidates": [{"content": {"parts": [{"text": "not json"}]}}]}
    monkeypatch.setattr(gx.requests, "post", lambda *a, **k: _fake_response(200, payload))
    out = gx.extract("hello", schema=SCHEMA, instructions="do it", api_key="k")
    assert out is None


def test_falls_back_to_second_model_on_429_quota(monkeypatch):
    good = {"candidates": [{"content": {"parts": [{"text": json.dumps({"x": "ok"})}]}}]}
    calls = []

    def fake_post(url, **k):
        calls.append(url)
        if "flash-lite" in url:
            return _fake_response(200, good)
        return _fake_response(429, text='"limit": 0')

    monkeypatch.setattr(gx.requests, "post", fake_post)
    out = gx.extract("hi", schema=SCHEMA, instructions="x", api_key="k",
                     models=("gemini-2.5-flash", "gemini-2.5-flash-lite"))
    assert out == {"x": "ok"}
    assert any("flash-lite" in u for u in calls)
