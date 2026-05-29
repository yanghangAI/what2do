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


def test_run_source_replays_cached_gemini_on_hash_match():
    calls = []

    def fake_gemini(text):
        calls.append(text)
        return ["X"]

    # prev run cached gemini=["b"]; parser is empty now -> backfill must replay
    prev = {"input_sha": content_hash("T1"), "gemini": ["b"], "divergence": True}
    dec, meta, cached = run_source(
        "src", parser_value=[], fetched_text="T1", prev_meta=prev,
        gemini_fn=fake_gemini, is_empty=lambda v: not v, equals=lambda a, b: a == b,
    )
    assert cached is True
    assert calls == []                  # Gemini NOT called
    assert dec.used_backup is True      # cached gemini replayed -> backfill
    assert dec.shipped == ["b"]
    assert dec.divergence is not None   # divergence re-derived (reaches CI)
    assert meta["gemini"] == ["b"]


def test_run_source_recalls_when_cached_gemini_is_none():
    calls = []

    def fake_gemini(text):
        calls.append(text)
        return ["a"]

    prev = {"input_sha": content_hash("T1"), "gemini": None}
    dec, meta, cached = run_source(
        "src", parser_value=[], fetched_text="T1", prev_meta=prev,
        gemini_fn=fake_gemini, is_empty=lambda v: not v, equals=lambda a, b: a == b,
    )
    assert cached is False
    assert calls == ["T1"]              # cached None is a miss -> retry


def test_run_source_persists_gemini_for_caching():
    dec, meta, cached = run_source(
        "src", parser_value=["a"], fetched_text="T2", prev_meta=None,
        gemini_fn=lambda t: ["a"], is_empty=lambda v: not v, equals=lambda a, b: a == b,
    )
    assert cached is False
    assert meta["gemini"] == ["a"]
    assert meta["input_sha"] == content_hash("T2")


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


from scraper.watchdog import decide, mullins_equal, mullins_empty

# Mullins is BACKUP-ONLY: the parser reads the displayed Finnly week from
# structured aria-labels; Gemini reads the whole multi-week dataset embedded in
# the raw HTML. A review cross-check is pure noise, so mullins_equal always
# "agrees" — Gemini only contributes via the empty-parser backup path.


def test_mullins_equal_always_agrees_review_is_disabled():
    # Even wildly different event sets never flag a review divergence.
    a = [{"date": "2026-05-30", "open": "12:10", "close": "13:50"}]
    b = [{"date": "2026-07-02", "open": "09:00", "close": "10:00"}]
    assert mullins_equal(a, b)
    assert mullins_equal(a, [])


def test_mullins_empty():
    assert mullins_empty([])
    assert not mullins_empty([{"date": "2026-05-30", "open": "12:10", "close": "13:50"}])


def test_mullins_empty_respects_today():
    today = "2026-05-29"
    # only a past-dated session -> no upcoming coverage -> empty
    assert mullins_empty([{"date": "2026-05-22", "open": "12:00", "close": "13:00"}], today)


def test_mullins_no_divergence_when_parser_has_data():
    # The whole point: parser has upcoming sessions, Gemini over-reads the HTML,
    # but no divergence is flagged (parser authoritative).
    today = "2026-05-29"
    parser = [{"date": "2026-05-30", "open": "13:00", "close": "14:00"}]
    gemini = [{"date": d, "open": "09:00", "close": "10:00"}
              for d in ("2026-05-22", "2026-05-30", "2026-06-15", "2026-07-02")]
    dec = decide("mullins-ice", parser, gemini,
                 is_empty=lambda v: mullins_empty(v, today),
                 equals=lambda x, y: mullins_equal(x, y, today))
    assert dec.divergence is None
    assert dec.used_backup is False


def test_mullins_backup_fires_only_when_parser_empty():
    today = "2026-05-29"
    gemini = [{"date": "2026-05-30", "open": "13:00", "close": "14:00"}]
    dec = decide("mullins-ice", [], gemini,
                 is_empty=lambda v: mullins_empty(v, today),
                 equals=lambda x, y: mullins_equal(x, y, today))
    assert dec.used_backup is True
    assert dec.divergence is not None


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


def test_format_divergence_report_lists_each():
    from scraper.watchdog import Divergence, format_divergence_report
    divs = [Divergence("rockwell-climbing", "parser empty; gemini found data",
                       {"mon": []}, {"mon": [{"open": "16:00", "close": "20:00"}]})]
    md, warnings = format_divergence_report(divs)
    assert "rockwell-climbing" in md
    assert any("rockwell-climbing" in w for w in warnings)
    assert format_divergence_report([]) == ("", [])


def test_apply_hours_watchdog_replays_backfill_on_cache_hit():
    days = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
    fac = _fac("rockwell-climbing", {d: [] for d in days})   # parser empty again
    section_texts = {"rockwell-climbing": "Monday 4pm - 8pm"}
    gemini_hours = {d: [{"open": "16:00", "close": "20:00"}] for d in days}
    prev_meta = {"rockwell-climbing": {
        "input_sha": content_hash("Monday 4pm - 8pm"),
        "gemini": gemini_hours, "divergence": True,
    }}
    called = []

    def gemini_fn(text):
        called.append(text)
        return gemini_hours

    divs, meta = apply_hours_watchdog(
        [fac], section_texts, prev_meta=prev_meta, gemini_fn=gemini_fn,
    )
    assert called == []                                   # cache hit: no Gemini call
    assert fac.hours["mon"] == [_I("16:00", "20:00")]     # backfill REPLAYED (was the bug)
    assert fac.hours["sun"] == [_I("16:00", "20:00")]
    assert len(divs) == 1                                 # divergence re-surfaced to CI
