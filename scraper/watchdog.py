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
