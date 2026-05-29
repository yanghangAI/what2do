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


def _mullins_key(events):
    return {(e.get("date"), e.get("open"), e.get("close")) for e in (events or [])}


def mullins_equal(a, b) -> bool:
    return _mullins_key(a) == _mullins_key(b)


def mullins_empty(events) -> bool:
    return len(events or []) == 0


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
