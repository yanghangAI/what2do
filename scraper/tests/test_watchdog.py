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
