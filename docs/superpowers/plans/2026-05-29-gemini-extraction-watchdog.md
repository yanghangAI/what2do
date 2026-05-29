# Gemini Extraction Watchdog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Gemini-based safety net around the deterministic scrapers so a parser that silently produces wrong or empty data is caught (review) and, when it yields nothing, backfilled (backup) — without making the LLM the unreviewed source of truth.

**Architecture:** Deterministic parsers stay primary and auto-ship. A new generic Gemini REST helper (`gemini_extract.py`) and a generic compare/decide layer (`watchdog.py`) wrap each in-scope source. Per run, parser output `D` and Gemini output `G` are compared; the parser wins on conflict (with a CI warning), Gemini's value ships only when the parser is empty, and last-known-good `stale` covers a Gemini outage. Source-specific schemas/prompts live in `gemini_sources.py`. Caching state lives in `data/hours.json` under `extract_meta`.

**Tech Stack:** Python 3.11, `requests`, `pytest`, BeautifulSoup (existing), Gemini REST API (`generativelanguage.googleapis.com`, same as `vision_puffer.py`).

**Spec:** `docs/superpowers/specs/2026-05-29-gemini-extraction-watchdog-design.md`

**Conventions:**
- Run tests with the project venv: `.venv/bin/python -m pytest <path> -v`.
- Tests are plain pytest functions in `scraper/tests/test_*.py`; fixtures in `scraper/tests/fixtures/`.
- Existing scrapers (`scrape_recwell.py`, `scrape_schedule.py`, `scrape_mullins.py`, `scrape_alert.py`) and `models.py`/`merge.py` are **not** modified except where a task says "Modify".
- Every commit message ends with the repo trailer:
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
- In-scope sources: RecWell facility hours, class schedule, Mullins ice, alert→overrides. Programs and Puffer are out of scope.

---

## File Structure

| File | Responsibility | Status |
|---|---|---|
| `scraper/gemini_extract.py` | Generic Gemini REST call: text+schema+prompt → dict or `None`. No source knowledge. | Create |
| `scraper/watchdog.py` | Generic compare/decide (`decide`, `Decision`, `Divergence`), per-type normalizers (hours/schedule/mullins/overrides), `content_hash`, `run_source` caching wrapper, divergence report formatting. | Create |
| `scraper/gemini_sources.py` | Per-source Gemini schemas + prompts + thin extract functions (`gemini_facility_hours`, `gemini_schedule`, `gemini_mullins`, `gemini_overrides`). | Create |
| `scraper/main.py` | Wire each in-scope source through `run_source`; collect divergences; persist `extract_meta`; emit CI report. | Modify |
| `.github/workflows/scrape.yml` | Add a gate step that fails the run when divergences/stale occurred (after commit). | Modify |
| `.gitignore` | Ignore the local pytest scratch only; `extract_meta` lives inside committed `hours.json`. | Modify (if needed) |
| `scraper/tests/test_gemini_extract.py` | Tests for the REST helper (mock `requests.post`). | Create |
| `scraper/tests/test_watchdog.py` | Tests for decide/normalizers/run_source/report. | Create |
| `scraper/tests/test_gemini_sources.py` | Tests for source extract functions (mock `gemini_extract.extract`). | Create |
| `scraper/tests/test_watchdog_recwell.py` | Golden RockWell colon-less regression. | Create |
| `scraper/tests/fixtures/rockwell_no_colon.txt` | RockWell section text in the colon-less format. | Create |

Milestone: after **Task 7**, the RecWell hours watchdog is live and the RockWell bug class is guarded end-to-end. Tasks 8–10 replicate the pattern for the other three sources; Task 11 adds CI visibility.

---

### Task 1: Generic Gemini REST helper

**Files:**
- Create: `scraper/gemini_extract.py`
- Test: `scraper/tests/test_gemini_extract.py`

- [ ] **Step 1: Write the failing tests**

```python
# scraper/tests/test_gemini_extract.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest scraper/tests/test_gemini_extract.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scraper.gemini_extract'`.

- [ ] **Step 3: Write the implementation**

```python
# scraper/gemini_extract.py
"""Generic Gemini REST extractor: (text, JSON schema, instructions) -> dict | None.

Mirrors the proven vision_puffer.py pattern but for text inputs. Returns
``None`` on any failure (missing key, API error, invalid JSON) — callers
treat ``None`` as "Gemini unavailable" and fall back to the deterministic
parser / last-known-good.
"""
from __future__ import annotations

import json
import os
import time

import requests

MODEL_CANDIDATES = ("gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.0-flash")
_URL_TMPL = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)
ANTI_HALLUCINATION = (
    "Extract only what is explicitly present in the text. If a day or field is "
    "not listed, return it as closed/empty/null. Never guess or invent values."
)


def extract(text, *, schema, instructions, api_key=None, models=MODEL_CANDIDATES):
    api_key = api_key or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None
    prompt = f"{instructions}\n\n{ANTI_HALLUCINATION}\n\nTEXT:\n{text}"
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": schema,
            "temperature": 0.0,
        },
    }
    payload = None
    for model in models:
        url = _URL_TMPL.format(model=model) + f"?key={api_key}"
        for attempt in (1, 2):
            r = requests.post(url, json=body, timeout=60)
            if r.status_code == 200:
                payload = r.json()
                break
            if r.status_code == 429 and '"limit": 0' in r.text:
                break  # model not free-tier eligible — try next
            if r.status_code not in (429, 500, 502, 503, 504):
                break  # non-retryable
            time.sleep(2 ** attempt)
        if payload is not None:
            break
    if payload is None:
        return None
    try:
        out_text = payload["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(out_text)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError):
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest scraper/tests/test_gemini_extract.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add scraper/gemini_extract.py scraper/tests/test_gemini_extract.py
git commit -m "feat(scraper): generic Gemini REST extractor"
```

---

### Task 2: Decision logic (the 5 branches)

**Files:**
- Create: `scraper/watchdog.py`
- Test: `scraper/tests/test_watchdog.py`

- [ ] **Step 1: Write the failing tests**

```python
# scraper/tests/test_watchdog.py
from scraper.watchdog import decide, Decision, Divergence, content_hash


# Trivial value model for testing decide(): a list; "empty" == [].
def _is_empty(v):
    return not v


def _equals(a, b):
    return sorted(a) == sorted(b)


def test_agree_ships_parser_no_divergence():
    d = decide("src", ["a"], ["a"], is_empty=_is_empty, equals=_equals)
    assert d.shipped == ["a"]
    assert d.used_backup is False
    assert d.divergence is None


def test_disagree_ships_parser_with_divergence():
    d = decide("src", ["a"], ["b"], is_empty=_is_empty, equals=_equals)
    assert d.shipped == ["a"]
    assert d.used_backup is False
    assert isinstance(d.divergence, Divergence)
    assert d.divergence.source == "src"


def test_parser_empty_gemini_found_uses_backup():
    d = decide("src", [], ["b"], is_empty=_is_empty, equals=_equals)
    assert d.shipped == ["b"]
    assert d.used_backup is True
    assert isinstance(d.divergence, Divergence)


def test_both_empty_ships_parser_no_divergence():
    d = decide("src", [], [], is_empty=_is_empty, equals=_equals)
    assert d.shipped == []
    assert d.used_backup is False
    assert d.divergence is None


def test_gemini_unavailable_ships_parser_no_divergence():
    d = decide("src", ["a"], None, is_empty=_is_empty, equals=_equals)
    assert d.shipped == ["a"]
    assert d.used_backup is False
    assert d.divergence is None


def test_content_hash_is_stable_and_input_sensitive():
    assert content_hash("abc") == content_hash("abc")
    assert content_hash("abc") != content_hash("abd")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest scraper/tests/test_watchdog.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scraper.watchdog'`.

- [ ] **Step 3: Write the implementation**

```python
# scraper/watchdog.py
"""Compare deterministic parser output with Gemini output and decide what ships.

The parser is the source of truth: it wins on conflict (and we flag a
divergence). Gemini's value ships only when the parser produced nothing.
``decide`` is generic over a value type via injected ``is_empty``/``equals``.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Callable


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class Divergence:
    source: str
    detail: str
    parser: object
    gemini: object


@dataclass
class Decision:
    shipped: object
    used_backup: bool
    divergence: "Divergence | None"


def decide(
    source: str,
    parser_value,
    gemini_value,
    *,
    is_empty: Callable[[object], bool],
    equals: Callable[[object, object], bool],
) -> Decision:
    # Gemini unavailable (None) — parser ships; upstream handles stale if empty.
    if gemini_value is None:
        return Decision(parser_value, False, None)
    if not is_empty(parser_value):
        if equals(parser_value, gemini_value):
            return Decision(parser_value, False, None)
        return Decision(
            parser_value,
            False,
            Divergence(source, "parser and gemini disagree", parser_value, gemini_value),
        )
    # parser empty
    if not is_empty(gemini_value):
        return Decision(
            gemini_value,
            True,
            Divergence(source, "parser empty; gemini found data", parser_value, gemini_value),
        )
    return Decision(parser_value, False, None)  # both empty → genuinely closed
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest scraper/tests/test_watchdog.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add scraper/watchdog.py scraper/tests/test_watchdog.py
git commit -m "feat(watchdog): generic compare/decide core"
```

---

### Task 3: Hours normalizers and equality

**Files:**
- Modify: `scraper/watchdog.py` (append)
- Test: `scraper/tests/test_watchdog.py` (append)

- [ ] **Step 1: Write the failing tests (append to test_watchdog.py)**

```python
# --- hours helpers ---
from scraper.models import Interval
from scraper.watchdog import (
    normalize_hours, hours_equal, hours_empty, intervals_from_dict,
)

_EMPTY = {d: [] for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}


def test_hours_equal_interval_vs_dict_order_independent():
    parser = dict(_EMPTY, mon=[Interval("16:00", "20:00")])
    gemini = dict(_EMPTY, mon=[{"open": "16:00", "close": "20:00"}])
    assert hours_equal(parser, gemini)


def test_hours_equal_detects_real_difference():
    parser = dict(_EMPTY, mon=[Interval("16:00", "20:00")])
    gemini = dict(_EMPTY, mon=[{"open": "16:00", "close": "18:00"}])
    assert not hours_equal(parser, gemini)


def test_hours_empty_true_for_all_closed():
    assert hours_empty(_EMPTY)
    assert not hours_empty(dict(_EMPTY, fri=[Interval("16:00", "20:00")]))


def test_intervals_from_dict_converts_to_interval_objects():
    out = intervals_from_dict({"mon": [{"open": "16:00", "close": "20:00"}]})
    assert out["mon"] == [Interval("16:00", "20:00")]
    assert out["sun"] == []
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest scraper/tests/test_watchdog.py -v`
Expected: FAIL — `ImportError: cannot import name 'normalize_hours'`.

- [ ] **Step 3: Implement (append to scraper/watchdog.py)**

```python
from scraper.models import DAYS, Interval


def _pair(iv):
    if isinstance(iv, dict):
        return (iv["open"], iv["close"])
    return (iv.open, iv.close)


def normalize_hours(hours: dict) -> dict:
    """{day: [Interval|{open,close}]} -> {day: sorted list of (open, close)}."""
    return {d: sorted({_pair(i) for i in hours.get(d, [])}) for d in DAYS}


def hours_equal(a: dict, b: dict) -> bool:
    return normalize_hours(a) == normalize_hours(b)


def hours_empty(hours: dict) -> bool:
    return all(len(hours.get(d, [])) == 0 for d in DAYS)


def intervals_from_dict(hours: dict) -> dict:
    """Gemini hours dict ({day:[{open,close}]}) -> {day:[Interval]} for all 7 days."""
    return {
        d: [Interval(open=i["open"], close=i["close"]) for i in hours.get(d, [])]
        for d in DAYS
    }
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest scraper/tests/test_watchdog.py -v`
Expected: PASS (10 passed).

- [ ] **Step 5: Commit**

```bash
git add scraper/watchdog.py scraper/tests/test_watchdog.py
git commit -m "feat(watchdog): hours normalize/equal/empty helpers"
```

---

### Task 4: Caching wrapper `run_source`

**Files:**
- Modify: `scraper/watchdog.py` (append)
- Test: `scraper/tests/test_watchdog.py` (append)

`run_source` skips the Gemini call when the fetched text hash matches the
previous run's stored hash (persisted in `extract_meta`), carrying the prior
divergence flag forward.

- [ ] **Step 1: Write the failing tests (append)**

```python
# --- run_source caching ---
from scraper.watchdog import run_source


def test_run_source_calls_gemini_when_hash_differs():
    calls = []

    def fake_gemini(text):
        calls.append(text)
        return ["a"]

    dec, meta, cached = run_source(
        "src", parser_value=["a"], fetched_text="T1", prev_meta=None,
        gemini_fn=fake_gemini, is_empty=lambda v: not v, equals=lambda a, b: a == b,
    )
    assert cached is False
    assert calls == ["T1"]
    assert dec.divergence is None
    assert meta["divergence"] is False
    assert meta["input_sha"] == content_hash("T1")


def test_run_source_skips_gemini_when_hash_matches():
    calls = []

    def fake_gemini(text):
        calls.append(text)
        return ["a"]

    prev = {"input_sha": content_hash("T1"), "divergence": True}
    dec, meta, cached = run_source(
        "src", parser_value=["a"], fetched_text="T1", prev_meta=prev,
        gemini_fn=fake_gemini, is_empty=lambda v: not v, equals=lambda a, b: a == b,
    )
    assert cached is True
    assert calls == []                      # Gemini NOT called
    assert dec.shipped == ["a"]
    assert meta["divergence"] is True        # carried forward
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest scraper/tests/test_watchdog.py -v`
Expected: FAIL — `ImportError: cannot import name 'run_source'`.

- [ ] **Step 3: Implement (append to scraper/watchdog.py)**

```python
def run_source(
    source, *, parser_value, fetched_text, prev_meta, gemini_fn, is_empty, equals,
):
    """Run the watchdog for one source with content-hash caching.

    Returns ``(Decision, new_meta, cached)``. ``new_meta`` is
    ``{"input_sha": str, "divergence": bool}`` for persistence in extract_meta.
    When the input hash matches ``prev_meta``, skips the Gemini call and ships
    the parser value, carrying the previous divergence flag forward.
    """
    h = content_hash(fetched_text)
    if prev_meta and prev_meta.get("input_sha") == h:
        return (
            Decision(parser_value, False, None),
            {"input_sha": h, "divergence": bool(prev_meta.get("divergence", False))},
            True,
        )
    gemini_value = gemini_fn(fetched_text)
    dec = decide(source, parser_value, gemini_value, is_empty=is_empty, equals=equals)
    meta = {"input_sha": h, "divergence": dec.divergence is not None}
    return dec, meta, False
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest scraper/tests/test_watchdog.py -v`
Expected: PASS (12 passed).

- [ ] **Step 5: Commit**

```bash
git add scraper/watchdog.py scraper/tests/test_watchdog.py
git commit -m "feat(watchdog): content-hash caching wrapper run_source"
```

---

### Task 5: Source extract — per-facility hours

**Files:**
- Create: `scraper/gemini_sources.py`
- Test: `scraper/tests/test_gemini_sources.py`

- [ ] **Step 1: Write the failing tests**

```python
# scraper/tests/test_gemini_sources.py
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
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest scraper/tests/test_gemini_sources.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scraper.gemini_sources'`.

- [ ] **Step 3: Implement**

```python
# scraper/gemini_sources.py
"""Per-source Gemini schemas, prompts, and thin extract functions.

Each function takes the SAME fetched text the deterministic parser saw and
returns a dict shaped like that parser's output, or ``None`` if Gemini is
unavailable. Source-specific knowledge lives here; the generic REST call lives
in gemini_extract and the compare/decide logic in watchdog.
"""
from __future__ import annotations

from scraper import gemini_extract
from scraper.models import DAYS

_INTERVAL = {
    "type": "object",
    "properties": {"open": {"type": "string"}, "close": {"type": "string"}},
    "required": ["open", "close"],
}
HOURS_SCHEMA = {
    "type": "object",
    "properties": {d: {"type": "array", "items": _INTERVAL} for d in DAYS},
}
_HOURS_PROMPT = (
    "You are reading the weekly operating hours for a SINGLE UMass recreation "
    "facility. Return per-weekday open/close intervals using 24-hour HH:MM "
    "times (e.g. '4pm - 8pm' -> open '16:00', close '20:00'). A day with no "
    "listed hours is closed: return an empty array for it. Keys: "
    + ", ".join(DAYS) + "."
)


def gemini_facility_hours(section_text):
    """Extract one facility's weekly hours from its section text."""
    return gemini_extract.extract(
        section_text, schema=HOURS_SCHEMA, instructions=_HOURS_PROMPT,
    )
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest scraper/tests/test_gemini_sources.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add scraper/gemini_sources.py scraper/tests/test_gemini_sources.py
git commit -m "feat(gemini-sources): per-facility hours extractor"
```

---

### Task 6: Golden RockWell regression

**Files:**
- Create: `scraper/tests/fixtures/rockwell_no_colon.txt`
- Test: `scraper/tests/test_watchdog_recwell.py`

This proves the end-to-end fix: the deterministic parser yields empty hours on
the colon-less RockWell format, Gemini (mocked) returns 4–8pm daily, and the
watchdog ships the backup and records a divergence.

- [ ] **Step 1: Create the fixture**

`scraper/tests/fixtures/rockwell_no_colon.txt`:

```
Monday 4pm - 8pm
Tuesday 4pm - 8pm
Wednesday 4pm - 8pm
Thursday 4pm - 8pm
Friday 4pm - 8pm
Saturday 4pm - 8pm
Sunday 4pm - 8pm
```

- [ ] **Step 2: Write the failing test**

```python
# scraper/tests/test_watchdog_recwell.py
from pathlib import Path

from scraper.scrape_recwell import _parse_schedule_line
from scraper.watchdog import decide, hours_empty, hours_equal, intervals_from_dict
from scraper.models import Interval, DAYS

FIXTURE = Path(__file__).parent / "fixtures" / "rockwell_no_colon.txt"


def _parse_section(text):
    """Mimic scrape_recwell's per-facility line parsing on a section's text."""
    hours = {d: [] for d in DAYS}
    for raw in text.splitlines():
        days, intervals = _parse_schedule_line(raw.strip())
        for d in days:
            hours[d].extend(intervals)
    return hours


def test_parser_yields_empty_on_colonless_rockwell():
    parsed = _parse_section(FIXTURE.read_text())
    assert hours_empty(parsed), "regression guard: colon-less format parses empty"


def test_watchdog_backfills_rockwell_from_gemini():
    parsed = _parse_section(FIXTURE.read_text())          # empty
    gemini = {d: [{"open": "16:00", "close": "20:00"}] for d in DAYS}
    dec = decide(
        "rockwell-climbing", parsed, gemini,
        is_empty=hours_empty, equals=hours_equal,
    )
    assert dec.used_backup is True
    assert dec.divergence is not None
    shipped = intervals_from_dict(dec.shipped)
    assert shipped["mon"] == [Interval("16:00", "20:00")]
    assert shipped["sun"] == [Interval("16:00", "20:00")]
```

- [ ] **Step 3: Run to verify the parser-empty guard fails appropriately**

Run: `.venv/bin/python -m pytest scraper/tests/test_watchdog_recwell.py -v`
Expected: PASS (both tests). `test_parser_yields_empty_on_colonless_rockwell` documents the parser gap; `test_watchdog_backfills...` proves the watchdog covers it. (No production code changes — this task asserts the existing parser behavior and the Task 2–3 watchdog logic compose correctly.)

- [ ] **Step 4: Commit**

```bash
git add scraper/tests/fixtures/rockwell_no_colon.txt scraper/tests/test_watchdog_recwell.py
git commit -m "test(watchdog): golden RockWell colon-less backfill regression"
```

---

### Task 7: Wire RecWell hours into main.py

**Files:**
- Modify: `scraper/main.py`
- Test: `scraper/tests/test_watchdog.py` (append — exercises the wiring helper)

The RecWell facilities are produced by `_run_recwell()` then merged. We add a
watchdog pass over the merged RecWell facilities, using each facility's section
text from the live HTML. To keep it testable, put the per-facility loop in a
helper `apply_hours_watchdog` in `watchdog.py`.

- [ ] **Step 1: Write the failing test (append to test_watchdog.py)**

```python
# --- apply_hours_watchdog ---
from scraper.watchdog import apply_hours_watchdog
from scraper.models import Interval as _I

def _fac(fid, hours):
    # minimal stand-in matching the attributes apply_hours_watchdog touches
    class F:
        pass
    f = F()
    f.id = fid
    f.hours = hours
    f.scrape_status = "ok"
    return f


def test_apply_hours_watchdog_backfills_empty_facility():
    empty = {d: [] for d in ("mon","tue","wed","thu","fri","sat","sun")}
    fac = _fac("rockwell-climbing", dict(empty))
    section_texts = {"rockwell-climbing": "Monday 4pm - 8pm"}
    gemini = {d: [{"open": "16:00", "close": "20:00"}] for d in
              ("mon","tue","wed","thu","fri","sat","sun")}

    divs, meta = apply_hours_watchdog(
        [fac], section_texts, prev_meta={},
        gemini_fn=lambda text: gemini,
    )
    assert fac.hours["mon"] == [_I("16:00", "20:00")]   # backfilled in place
    assert len(divs) == 1 and divs[0].source == "rockwell-climbing"
    assert meta["rockwell-climbing"]["divergence"] is True


def test_apply_hours_watchdog_leaves_matching_facility_untouched():
    hours = {d: [] for d in ("mon","tue","wed","thu","fri","sat","sun")}
    hours["mon"] = [_I("16:00", "20:00")]
    fac = _fac("x", dict(hours))
    section_texts = {"x": "Monday 4pm - 8pm"}
    gemini = {d: [] for d in ("mon","tue","wed","thu","fri","sat","sun")}
    gemini["mon"] = [{"open": "16:00", "close": "20:00"}]

    divs, meta = apply_hours_watchdog(
        [fac], section_texts, prev_meta={}, gemini_fn=lambda text: gemini,
    )
    assert fac.hours["mon"] == [_I("16:00", "20:00")]
    assert divs == []
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest scraper/tests/test_watchdog.py -v`
Expected: FAIL — `ImportError: cannot import name 'apply_hours_watchdog'`.

- [ ] **Step 3: Implement `apply_hours_watchdog` (append to scraper/watchdog.py)**

```python
def apply_hours_watchdog(facilities, section_texts, prev_meta, gemini_fn):
    """Run the hours watchdog over RecWell facilities, mutating hours in place.

    ``facilities``    : list of Facility objects (have .id, .hours).
    ``section_texts`` : {facility_id: section_text from the live page}.
    ``prev_meta``     : {facility_id: {input_sha, divergence}} from extract_meta.
    ``gemini_fn``     : section_text -> hours dict | None.

    Returns ``(divergences, new_meta)``.
    """
    divergences = []
    new_meta = {}
    for fac in facilities:
        text = section_texts.get(fac.id)
        if not text:
            continue  # no section to compare against; leave parser value as-is
        dec, meta, _cached = run_source(
            fac.id, parser_value=fac.hours, fetched_text=text,
            prev_meta=prev_meta.get(fac.id), gemini_fn=gemini_fn,
            is_empty=hours_empty, equals=hours_equal,
        )
        if dec.used_backup:
            fac.hours = intervals_from_dict(dec.shipped)
        if dec.divergence is not None:
            divergences.append(dec.divergence)
        new_meta[fac.id] = meta
    return divergences, new_meta
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest scraper/tests/test_watchdog.py -v`
Expected: PASS (14 passed).

- [ ] **Step 5: Wire into main.py**

Modify `scraper/main.py`. The RecWell HTML is currently fetched inside
`_run_recwell()` and discarded. Refactor so `main()` has the HTML, then run the
watchdog after `merge_results`.

Replace the body of `_run_recwell` (lines ~45-57) so it returns the HTML too:

```python
def _run_recwell() -> tuple[list[tuple[str, dict | None, Exception | None]], str | None]:
    try:
        html = _fetch_recwell_html()
        records = scrape_recwell(html)
        return [(r["id"], r, None) for r in records], html
    except Exception as e:
        print(f"recwell scrape failed: {e}", file=sys.stderr)
        return [
            ("boyden-pool", None, e),
            ("curry-hicks-pool", None, e),
            ("rockwell-climbing", None, e),
        ], None
```

In `main()`, update the call site (line ~73) and add the watchdog pass after
`doc = merge_results(...)` (line ~76). Add these imports at the top with the
other scraper imports:

```python
from bs4 import BeautifulSoup
from scraper import gemini_sources
from scraper.scrape_recwell import FACILITIES as RECWELL_FACILITIES, _section_text_after
from scraper.watchdog import apply_hours_watchdog
```

Replace:

```python
    results: list[tuple[str, dict | None, Exception | None]] = []
    results.extend(_run_recwell())
    results.append(_run_mullins())

    doc = merge_results(results, prev, now_iso=now_iso)
```

with:

```python
    results: list[tuple[str, dict | None, Exception | None]] = []
    recwell_results, recwell_html = _run_recwell()
    results.extend(recwell_results)
    results.append(_run_mullins())

    doc = merge_results(results, prev, now_iso=now_iso)

    divergences = []
    extract_meta = {}
    if recwell_html:
        soup = BeautifulSoup(recwell_html, "html.parser")
        section_texts = {
            fac["id"]: _section_text_after(soup, fac["match"])
            for fac in RECWELL_FACILITIES
        }
        divs, meta = apply_hours_watchdog(
            doc.facilities, section_texts,
            prev_meta=prev_raw.get("extract_meta") or {},
            gemini_fn=gemini_sources.gemini_facility_hours,
        )
        divergences.extend(divs)
        extract_meta.update(meta)
```

**Required ordering change:** in current code `prev_raw` is loaded at line ~79,
*after* `merge_results`. Move the `prev_raw` load block (the `try/except` that
sets `prev_raw`) to **immediately after `prev = _load_previous()`** (line ~70),
so every watchdog block below can read `prev_raw.get("extract_meta")`. Then near
the serialization (line ~185), add:

```python
    out["extract_meta"] = {**(prev_raw.get("extract_meta") or {}), **extract_meta}
```

(Full CI emission of `divergences` is wired in Task 11; for now they are
collected.)

- [ ] **Step 6: Run the full suite + a syntax/import smoke**

Run: `.venv/bin/python -m pytest scraper/tests/ -v`
Expected: PASS (all existing + new).

Run: `.venv/bin/python -c "import scraper.main"`
Expected: no error (imports resolve).

- [ ] **Step 7: Commit**

```bash
git add scraper/main.py scraper/watchdog.py scraper/tests/test_watchdog.py
git commit -m "feat(main): wire RecWell hours watchdog with extract_meta caching"
```

---

### Task 8: Schedule watchdog

**Files:**
- Modify: `scraper/watchdog.py`, `scraper/gemini_sources.py`, `scraper/main.py`
- Test: `scraper/tests/test_watchdog.py`, `scraper/tests/test_gemini_sources.py`

- [ ] **Step 1: Write failing tests**

Append to `scraper/tests/test_watchdog.py`:

```python
# --- schedule helpers ---
from scraper.watchdog import schedule_equal, schedule_empty

_SCHED_A = [{"date": "2026-05-30", "weekday": "Sat",
             "events": [{"time": "12:00", "name": "Club Ballroom Dance"}]}]


def test_schedule_equal_normalizes_name_whitespace_case():
    b = [{"date": "2026-05-30", "weekday": "Sat",
          "events": [{"time": "12:00", "name": "  club   BALLROOM dance "}]}]
    assert schedule_equal(_SCHED_A, b)


def test_schedule_equal_detects_missing_event():
    b = [{"date": "2026-05-30", "weekday": "Sat", "events": []}]
    assert not schedule_equal(_SCHED_A, b)


def test_schedule_empty():
    assert schedule_empty([])
    assert schedule_empty([{"date": "x", "weekday": "y", "events": []}])
    assert not schedule_empty(_SCHED_A)
```

Append to `scraper/tests/test_gemini_sources.py`:

```python
def test_gemini_schedule_passthrough(monkeypatch):
    monkeypatch.setattr(gs.gemini_extract, "extract",
                        lambda *a, **k: [{"date": "2026-05-30", "weekday": "Sat",
                                          "events": [{"time": "12:00", "name": "X"}]}])
    out = gs.gemini_schedule("Sat, May 30 2026\n12:00 PM X")
    assert out[0]["events"][0]["name"] == "X"
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest scraper/tests/test_watchdog.py scraper/tests/test_gemini_sources.py -v`
Expected: FAIL — `ImportError: cannot import name 'schedule_equal'` / `gemini_schedule`.

- [ ] **Step 3: Implement schedule helpers (append to scraper/watchdog.py)**

```python
def _schedule_key(days):
    out = set()
    for day in days or []:
        for e in day.get("events", []):
            name = " ".join(str(e.get("name", "")).split()).lower()
            out.add((day.get("date"), e.get("time"), name))
    return out


def schedule_equal(a, b) -> bool:
    return _schedule_key(a) == _schedule_key(b)


def schedule_empty(days) -> bool:
    return len(_schedule_key(days)) == 0
```

Implement the schedule extractor (append to scraper/gemini_sources.py):

```python
_SCHEDULE_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "date": {"type": "string"},
            "weekday": {"type": "string"},
            "events": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"time": {"type": "string"}, "name": {"type": "string"}},
                    "required": ["time", "name"],
                },
            },
        },
        "required": ["date", "weekday", "events"],
    },
}
_SCHEDULE_PROMPT = (
    "You are reading the UMass RecWell daily 'Upcoming Classes' widget. Return a "
    "list of days, each with an ISO date (YYYY-MM-DD), a 3-letter weekday "
    "(Mon..Sun), and its events. Each event has a 24-hour HH:MM time and the "
    "class name exactly as shown. Keep every event, including orientations."
)


def gemini_schedule(text):
    return gemini_extract.extract(
        text, schema=_SCHEDULE_SCHEMA, instructions=_SCHEDULE_PROMPT,
    )
```

- [ ] **Step 4: Wire into main.py**

`scrape_schedule.fetch_schedule()` currently fetches+parses internally. Split so
`main()` holds the rendered text. Add import:

```python
from scraper.scrape_schedule import fetch_schedule_text, parse_schedule_text
from scraper.watchdog import run_source, schedule_empty, schedule_equal
```

Add to `scrape_schedule.py` a thin text-fetcher (Modify) so both parser and
Gemini see the same text:

```python
def fetch_schedule_text(timeout_ms: int = 60_000) -> str:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.goto(HOME_URL, wait_until="networkidle", timeout=timeout_ms)
            page.wait_for_timeout(4000)
            return page.inner_text("body")
        finally:
            browser.close()
```

and refactor `fetch_schedule` to `return parse_schedule_text(fetch_schedule_text(timeout_ms))`.

In `main()`, replace the schedule block (lines ~90-94):

```python
    try:
        schedule_text = fetch_schedule_text()
        schedule = parse_schedule_text(schedule_text)
        dec, meta, _ = run_source(
            "schedule", parser_value=schedule, fetched_text=schedule_text,
            prev_meta=(prev_raw.get("extract_meta") or {}).get("schedule"),
            gemini_fn=gemini_sources.gemini_schedule,
            is_empty=schedule_empty, equals=schedule_equal,
        )
        if dec.used_backup:
            schedule = dec.shipped
        if dec.divergence is not None:
            divergences.append(dec.divergence)
        extract_meta["schedule"] = meta
    except Exception as e:
        print(f"schedule scrape failed: {e}", file=sys.stderr)
        schedule = prev_raw.get("schedule", [])
```

- [ ] **Step 5: Run to verify pass + smoke**

Run: `.venv/bin/python -m pytest scraper/tests/ -v`
Expected: PASS.
Run: `.venv/bin/python -c "import scraper.main"`
Expected: no error.

- [ ] **Step 6: Commit**

```bash
git add scraper/watchdog.py scraper/gemini_sources.py scraper/scrape_schedule.py scraper/main.py scraper/tests/test_watchdog.py scraper/tests/test_gemini_sources.py
git commit -m "feat(watchdog): schedule cross-check + backup"
```

---

### Task 9: Mullins ice watchdog

**Files:**
- Modify: `scraper/watchdog.py`, `scraper/gemini_sources.py`, `scraper/main.py`
- Test: `scraper/tests/test_watchdog.py`, `scraper/tests/test_gemini_sources.py`

- [ ] **Step 1: Write failing tests**

Append to `scraper/tests/test_watchdog.py`:

```python
from scraper.watchdog import mullins_equal, mullins_empty

_EV = [{"date": "2026-05-30", "open": "12:10", "close": "13:50"}]


def test_mullins_equal_order_independent():
    b = [{"date": "2026-05-30", "open": "12:10", "close": "13:50"}]
    assert mullins_equal(_EV, b)


def test_mullins_equal_detects_difference():
    b = [{"date": "2026-05-30", "open": "12:10", "close": "14:00"}]
    assert not mullins_equal(_EV, b)


def test_mullins_empty():
    assert mullins_empty([])
    assert not mullins_empty(_EV)
```

Append to `scraper/tests/test_gemini_sources.py`:

```python
def test_gemini_mullins_passthrough(monkeypatch):
    monkeypatch.setattr(gs.gemini_extract, "extract",
                        lambda *a, **k: [{"date": "2026-05-30", "open": "12:10", "close": "13:50"}])
    out = gs.gemini_mullins("<rendered week view text>")
    assert out[0]["open"] == "12:10"
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest scraper/tests/test_watchdog.py scraper/tests/test_gemini_sources.py -v`
Expected: FAIL — missing `mullins_equal` / `gemini_mullins`.

- [ ] **Step 3: Implement (append to scraper/watchdog.py)**

```python
def _mullins_key(events):
    return {(e.get("date"), e.get("open"), e.get("close")) for e in (events or [])}


def mullins_equal(a, b) -> bool:
    return _mullins_key(a) == _mullins_key(b)


def mullins_empty(events) -> bool:
    return len(events or []) == 0
```

Append to `scraper/gemini_sources.py`:

```python
_MULLINS_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "date": {"type": "string"},
            "open": {"type": "string"},
            "close": {"type": "string"},
        },
        "required": ["date", "open", "close"],
    },
}
_MULLINS_PROMPT = (
    "You are reading the Mullins Community Ice Center weekly schedule. Return "
    "only PUBLIC SKATING sessions as a list of {date (YYYY-MM-DD), open, close} "
    "using 24-hour HH:MM times. Ignore non-public-skate events."
)


def gemini_mullins(text):
    return gemini_extract.extract(
        text, schema=_MULLINS_SCHEMA, instructions=_MULLINS_PROMPT,
    )
```

- [ ] **Step 4: Wire into main.py**

`scrape_mullins.scrape_mullins()` returns a record dict with `events`. The
rendered HTML comes from `fetch_mullins_html()`. The Mullins record is part of
`results`/`doc.facilities`. Replace `_run_mullins` so it returns the HTML too,
and run the watchdog on the merged Mullins facility's `events`.

Modify `_run_mullins`:

```python
def _run_mullins() -> tuple[tuple[str, dict | None, Exception | None], str | None]:
    from scraper.scrape_mullins import fetch_mullins_html, parse_mullins_html
    try:
        html = fetch_mullins_html()
        return ("mullins-ice", parse_mullins_html(html), None), html
    except Exception as e:
        print(f"mullins scrape failed: {e}", file=sys.stderr)
        return ("mullins-ice", None, e), None
```

Update its call site:

```python
    mullins_result, mullins_html = _run_mullins()
    results.append(mullins_result)
```

After `doc = merge_results(...)` and the RecWell watchdog block, add:

```python
    if mullins_html:
        mfac = next((f for f in doc.facilities if f.id == "mullins-ice"), None)
        if mfac is not None:
            dec, meta, _ = run_source(
                "mullins-ice", parser_value=mfac.events or [],
                fetched_text=mullins_html,
                prev_meta=(prev_raw.get("extract_meta") or {}).get("mullins-ice"),
                gemini_fn=gemini_sources.gemini_mullins,
                is_empty=mullins_empty, equals=mullins_equal,
            )
            if dec.used_backup:
                mfac.events = dec.shipped
            if dec.divergence is not None:
                divergences.append(dec.divergence)
            extract_meta["mullins-ice"] = meta
```

Add imports: `from scraper.watchdog import mullins_empty, mullins_equal`.

- [ ] **Step 5: Run to verify pass + smoke**

Run: `.venv/bin/python -m pytest scraper/tests/ -v`
Expected: PASS.
Run: `.venv/bin/python -c "import scraper.main"`
Expected: no error.

- [ ] **Step 6: Commit**

```bash
git add scraper/watchdog.py scraper/gemini_sources.py scraper/main.py scraper/tests/test_watchdog.py scraper/tests/test_gemini_sources.py
git commit -m "feat(watchdog): Mullins ice cross-check + backup"
```

---

### Task 10: Alert → overrides watchdog

**Files:**
- Modify: `scraper/watchdog.py`, `scraper/gemini_sources.py`, `scraper/main.py`
- Test: `scraper/tests/test_watchdog.py`, `scraper/tests/test_gemini_sources.py`

The deterministic `parse_alert_overrides(text)` returns
`{fid: {start_date, closed_from, hours}}`. We cross-check the structured
overrides + holidays. The verbatim alert text is never compared.

- [ ] **Step 1: Write failing tests**

Append to `scraper/tests/test_watchdog.py`:

```python
from scraper.watchdog import overrides_equal, overrides_empty

_OV_A = {
    "overrides": {"rockwell-climbing": {
        "start_date": "2026-05-26", "closed_from": None,
        "hours": {d: ([{"open": "16:00", "close": "20:00"}] if d != "sun" else [])
                  for d in ("mon","tue","wed","thu","fri","sat","sun")}}},
    "holidays": [{"date": "2026-05-25", "name": "Memorial Day"}],
}


def test_overrides_equal_ignores_hours_order_and_holiday_order():
    import copy
    b = copy.deepcopy(_OV_A)
    b["holidays"] = list(reversed(b["holidays"]))  # same set
    assert overrides_equal(_OV_A, b)


def test_overrides_equal_detects_start_date_change():
    import copy
    b = copy.deepcopy(_OV_A)
    b["overrides"]["rockwell-climbing"]["start_date"] = "2026-06-01"
    assert not overrides_equal(_OV_A, b)


def test_overrides_empty():
    assert overrides_empty({"overrides": {}, "holidays": []})
    assert not overrides_empty(_OV_A)
```

Append to `scraper/tests/test_gemini_sources.py`:

```python
def test_gemini_overrides_passthrough(monkeypatch):
    monkeypatch.setattr(gs.gemini_extract, "extract",
                        lambda *a, **k: {"overrides": {}, "holidays": []})
    out = gs.gemini_overrides("FACILITIES ALERT: ...")
    assert out == {"overrides": {}, "holidays": []}
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest scraper/tests/test_watchdog.py scraper/tests/test_gemini_sources.py -v`
Expected: FAIL — missing `overrides_equal` / `gemini_overrides`.

- [ ] **Step 3: Implement (append to scraper/watchdog.py)**

```python
def _ov_is_empty(ov):
    ov = ov or {}
    return (
        not ov.get("start_date")
        and not ov.get("closed_from")
        and all(not (ov.get("hours", {}) or {}).get(d) for d in DAYS)
    )


def _overrides_key(obj):
    obj = obj or {}
    ovs = obj.get("overrides", {}) or {}
    norm_ovs = {}
    for fid, ov in ovs.items():
        if _ov_is_empty(ov):
            continue  # drop all-empty facility entries so a fixed-property
                      # Gemini schema that fills blanks doesn't false-alarm
        norm_ovs[fid] = (
            ov.get("start_date"),
            ov.get("closed_from"),
            tuple(sorted(
                (d, tuple(sorted(_pair(i) for i in (ov.get("hours", {}) or {}).get(d, []))))
                for d in DAYS
            )),
        )
    holidays = frozenset(
        (h.get("date"), h.get("name")) for h in (obj.get("holidays") or [])
    )
    return (tuple(sorted(norm_ovs.items())), holidays)


def overrides_equal(a, b) -> bool:
    return _overrides_key(a) == _overrides_key(b)


def overrides_empty(obj) -> bool:
    obj = obj or {}
    return not (obj.get("overrides") or {}) and not (obj.get("holidays") or [])
```

Append to `scraper/gemini_sources.py`:

Gemini structured output does not reliably support free-form maps
(`additionalProperties`), so the override map uses **fixed properties** for the
four known facility ids (avoids a map; Gemini fills only what it finds, and the
`_ov_is_empty` drop in `_overrides_key` discards blanks before comparison).

```python
_OVERRIDE_OBJ = {
    "type": "object",
    "properties": {
        "start_date": {"type": "string"},
        "closed_from": {"type": "string"},
        "hours": {"type": "object",
                  "properties": {d: {"type": "array", "items": _INTERVAL} for d in DAYS}},
    },
}
_OVERRIDE_FIDS = ("recreation-center", "boyden-pool", "curry-hicks-pool", "rockwell-climbing")
_OVERRIDES_SCHEMA = {
    "type": "object",
    "properties": {
        "overrides": {
            "type": "object",
            "properties": {fid: _OVERRIDE_OBJ for fid in _OVERRIDE_FIDS},
        },
        "holidays": {
            "type": "array",
            "items": {"type": "object",
                      "properties": {"date": {"type": "string"}, "name": {"type": "string"}},
                      "required": ["date", "name"]},
        },
    },
}
_OVERRIDES_PROMPT = (
    "You are reading the UMass RecWell 'FACILITIES ALERT' banner. Produce "
    "structured summer-hours overrides keyed by facility id (recreation-center, "
    "boyden-pool, curry-hicks-pool, rockwell-climbing). For each facility the "
    "banner gives a summer schedule, set its start_date (ISO YYYY-MM-DD), an "
    "optional closed_from ISO date if it says it will close for the semester, "
    "and per-weekday hours (24-hour HH:MM; closed days empty). Omit / leave "
    "empty any facility the banner does not mention. Also list dated holiday "
    "closures as {date, name}. Use null/empty when not stated."
)


def gemini_overrides(text):
    return gemini_extract.extract(
        text, schema=_OVERRIDES_SCHEMA, instructions=_OVERRIDES_PROMPT,
    )
```

- [ ] **Step 4: Wire into main.py (review-only — does not replace override logic)**

The alert overrides drive facility hours via existing gap logic; per the spec
the parser stays source of truth, so here Gemini is **review-only**: compare and
record a divergence, but keep the deterministic `overrides`/`holidays`. Backup
(shipping Gemini's overrides) is intentionally NOT applied for this source.

In `main()`, after `alert` is fetched and `overrides`/`holidays` computed
(around lines ~104 and ~190), add a comparison using the raw alert text:

```python
    if alert:
        det = {"overrides": {fid: {"start_date": ov.get("start_date"),
                                    "closed_from": ov.get("closed_from"),
                                    "hours": {d: [iv.to_dict() for iv in ov["hours"].get(d, [])]
                                              for d in DAYS_TUPLE}}
                              for fid, ov in parse_alert_overrides(alert).items()},
               "holidays": parse_holidays(alert)}
        g = gemini_sources.gemini_overrides(alert)
        disagree = g is not None and not overrides_empty(det) and not overrides_equal(det, g)
        if disagree:
            divergences.append(
                Divergence("alert-overrides", "parser and gemini disagree", det, g)
            )
        extract_meta["alert-overrides"] = {
            "input_sha": content_hash(alert),
            "divergence": bool(disagree),
        }
```

Add to the imports at the top of `main.py`:

```python
from scraper.models import DAYS as DAYS_TUPLE
from scraper.watchdog import Divergence, content_hash, overrides_empty, overrides_equal
```

(`parse_alert_overrides` and `parse_holidays` are already imported.)

- [ ] **Step 5: Run to verify pass + smoke**

Run: `.venv/bin/python -m pytest scraper/tests/ -v`
Expected: PASS.
Run: `.venv/bin/python -c "import scraper.main"`
Expected: no error.

- [ ] **Step 6: Commit**

```bash
git add scraper/watchdog.py scraper/gemini_sources.py scraper/main.py scraper/tests/test_watchdog.py scraper/tests/test_gemini_sources.py
git commit -m "feat(watchdog): alert-overrides review cross-check"
```

---

### Task 11: CI visibility — report + gate

**Files:**
- Modify: `scraper/watchdog.py` (report formatter), `scraper/main.py` (emit), `.github/workflows/scrape.yml` (gate)
- Test: `scraper/tests/test_watchdog.py`

- [ ] **Step 1: Write failing test (append)**

```python
def test_format_divergence_report_lists_each():
    from scraper.watchdog import Divergence, format_divergence_report
    divs = [Divergence("rockwell-climbing", "parser empty; gemini found data",
                       {"mon": []}, {"mon": [{"open": "16:00", "close": "20:00"}]})]
    md, warnings = format_divergence_report(divs)
    assert "rockwell-climbing" in md
    assert any("rockwell-climbing" in w for w in warnings)
    assert format_divergence_report([]) == ("", [])
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest scraper/tests/test_watchdog.py::test_format_divergence_report_lists_each -v`
Expected: FAIL — `cannot import name 'format_divergence_report'`.

- [ ] **Step 3: Implement (append to scraper/watchdog.py)**

```python
def format_divergence_report(divergences):
    """Return ``(markdown_summary, [github_warning_lines])`` for CI.

    Empty input yields ``("", [])``.
    """
    if not divergences:
        return "", []
    lines = ["### Scraper divergences", "", "| source | detail |", "|---|---|"]
    warnings = []
    for d in divergences:
        lines.append(f"| {d.source} | {d.detail} |")
        warnings.append(f"::warning::watchdog divergence in {d.source}: {d.detail}")
    return "\n".join(lines) + "\n", warnings
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest scraper/tests/test_watchdog.py -v`
Expected: PASS.

- [ ] **Step 5: Emit from main.py**

Near the end of `main()` (before `return 0`), add:

```python
    from scraper.watchdog import format_divergence_report
    md, warnings = format_divergence_report(divergences)
    for w in warnings:
        print(w)  # GitHub Actions ::warning:: annotations
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if md and summary_path:
        with open(summary_path, "a") as fh:
            fh.write(md)
    # Drop a machine-readable signal for the workflow gate step.
    Path(OUT_PATH.parent.parent / ".divergences").write_text(str(len(divergences)))
```

Add `import os` if not already imported (it is not currently — add it).

- [ ] **Step 6: Add the gate step to scrape.yml (Modify)**

In `.github/workflows/scrape.yml`, the "Commit if changed" step stays first
(data must ship). Append a final step AFTER it:

```yaml
      - name: Fail run on watchdog divergence
        run: |
          n=$(cat .divergences 2>/dev/null || echo 0)
          if [ "$n" != "0" ]; then
            echo "::error::$n watchdog divergence(s) — review the job summary."
            exit 1
          fi
          echo "No divergences."
```

Also add `.divergences` to `.gitignore` (Modify) so the signal file is not
committed:

```
.divergences
```

- [ ] **Step 7: Run full suite + import smoke**

Run: `.venv/bin/python -m pytest scraper/tests/ -v`
Expected: PASS (all).
Run: `.venv/bin/python -c "import scraper.main"`
Expected: no error.

- [ ] **Step 8: Commit**

```bash
git add scraper/watchdog.py scraper/main.py .github/workflows/scrape.yml .gitignore scraper/tests/test_watchdog.py
git commit -m "feat(ci): emit watchdog divergences and gate the run"
```

---

## Post-implementation verification

- [ ] Full suite green: `.venv/bin/python -m pytest scraper/tests/ -v`
- [ ] Optional live smoke (needs `GEMINI_API_KEY`): `GEMINI_API_KEY=… .venv/bin/python -m scraper.main` then inspect `data/hours.json` — confirm `rockwell-climbing` now shows `16:00–20:00` mon–sun and an `extract_meta` block is present.
- [ ] Confirm `data/hours.json` gained `extract_meta` and that re-running with unchanged sources skips Gemini calls (no new divergences, fast run).
- [ ] Open a PR from `feature/gemini-extraction-watchdog` to `main`.

---

## Notes on scope & decisions (from the spec)

- On a non-empty-but-conflicting parse, the parser value ships and a CI warning is raised (parser is source of truth). Only an empty parser is backfilled by Gemini.
- Alert→overrides is review-only (no backfill) because its output drives downstream gap logic; a wrong backfill there would propagate to facility hours.
- Programs (link harvesting) and Puffer (already Gemini) are out of scope.
- Caching state lives in committed `data/hours.json` under `extract_meta`, since GitHub Actions checks out fresh each run.
- **Garbage-input / fetch-failure handling (spec §Error handling):** a failed source fetch is caught and routes to the existing `stale`/prev path (RecWell: `recwell_html is None` skips the watchdog block; schedule/Mullins: the `except` falls back to `prev_raw`). An empty per-facility section is skipped (`if not text: continue` in `apply_hours_watchdog`). The decision logic also prevents a near-empty page from fabricating a closure: "both empty → ship parser", and Gemini's anti-hallucination prompt + `temperature 0` keep it from inventing hours from thin input. So Gemini's value is only ever shipped when the parser is empty *and* Gemini found real, schema-valid data.
- **Implementation-time validation for Task 10:** the alert-overrides schema/prompt is the most complex; during implementation, run one live `gemini_overrides(<real alert text>)` call and confirm the returned shape validates before relying on the cross-check (it is review-only, so a bad shape only suppresses or adds a warning, never ships).
