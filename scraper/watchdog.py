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
