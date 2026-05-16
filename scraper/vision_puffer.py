"""Use Gemini's vision API to read per-beach E. coli geomean values off
a scanned Puffer's Pond water quality test PDF.

Tesseract can't handle the handwritten chain-of-custody form, but
Gemini 2.0 Flash reads it reliably and is free at the volumes we need
(one call per workflow run).

The caller must set ``GEMINI_API_KEY`` in the environment. If absent,
``extract_readings`` returns ``None`` gracefully — production should
treat a missing key as "skip, show no numbers" rather than failing.
"""
from __future__ import annotations

import base64
import json
import os
import re
import time
import zlib

import requests

_MODEL_CANDIDATES = (
    # In order of preference. Try each until one isn't rate-limited or
    # quota-blocked — different models have different free-tier coverage
    # and Google rotates which one is free-eligible.
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.0-flash-lite",
    "gemini-2.0-flash",
)
_GEMINI_URL_TMPL = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)

_PROMPT = (
    "This is a Puffer's Pond water quality test form (a chain-of-custody "
    "sheet from Amherst WWTP). Extract the two 'Geometric Mean of 5 most "
    "recent samples' values — one for South Beach and one for North Beach "
    "— in MPN/100 ml E. coli. Also extract the sample collection date if "
    "you can read it. Return ONLY JSON in this exact shape:\n"
    '{"south_geomean": <number or null>, '
    '"north_geomean": <number or null>, '
    '"test_date": "<YYYY-MM-DD or null>"}\n'
    "If a value isn't clearly readable, use null. Do not guess."
)


def _pdf_first_image(pdf_bytes: bytes) -> tuple[str, bytes] | None:
    """Return ``(mime_type, bytes)`` for the largest embedded image in the
    PDF — the scanned page itself. We send the image directly because
    inline image inputs are tokenized much more cheaply than a full
    application/pdf payload under Gemini's free tier."""
    streams = list(re.finditer(
        rb"<<([^>]+)>>\s*stream\r?\n(.*?)\r?\nendstream", pdf_bytes, re.DOTALL,
    ))
    best: tuple[str, bytes] | None = None
    best_size = 0
    for m in streams:
        header = m.group(1)
        raw = m.group(2)
        if b"/Subtype /Image" not in header:
            continue
        if b"/DCTDecode" not in header:
            continue
        # Pipeline /FlateDecode /DCTDecode → deflate first, then it's JPEG.
        try:
            data = zlib.decompress(raw) if b"/FlateDecode" in header else raw
        except zlib.error:
            continue
        if not data.startswith(b"\xff\xd8"):
            continue
        if len(data) > best_size:
            best = ("image/jpeg", data)
            best_size = len(data)
    return best


def extract_readings(pdf_bytes: bytes, api_key: str | None = None) -> dict | None:
    api_key = api_key or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None

    img = _pdf_first_image(pdf_bytes)
    if img:
        mime, payload = img
    else:
        mime, payload = "application/pdf", pdf_bytes

    body = {
        "contents": [{"parts": [
            {"inline_data": {
                "mime_type": mime,
                "data": base64.b64encode(payload).decode(),
            }},
            {"text": _PROMPT},
        ]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.0,
        },
    }
    # Try each candidate model in turn. 429s with limit=0 mean the model
    # isn't free-tier eligible for this project — move on; transient 429s
    # / 5xx are retried with a short backoff.
    payload = None
    last_err: str | None = None
    for model in _MODEL_CANDIDATES:
        url = _GEMINI_URL_TMPL.format(model=model) + f"?key={api_key}"
        for attempt in (1, 2):
            r = requests.post(url, json=body, timeout=60)
            if r.status_code == 200:
                payload = r.json()
                break
            last_err = f"{model} {r.status_code}: {r.text[:300]}"
            if r.status_code == 429 and '"limit": 0' in r.text:
                break  # not free-tier eligible — try next model
            if r.status_code not in (429, 500, 502, 503, 504):
                break  # non-retryable
            time.sleep(2 ** attempt)
        if payload is not None:
            break
    if payload is None:
        raise RuntimeError(f"Gemini failed across all models: {last_err}")
    try:
        text = payload["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return _normalize(parsed)


def _normalize(parsed: dict) -> dict | None:
    """Coerce types, validate ranges, and drop nonsense values."""
    def _num(v):
        if v is None:
            return None
        try:
            n = float(v)
        except (TypeError, ValueError):
            return None
        # E. coli readings are non-negative; cap at a sane upper bound to
        # reject obviously wrong vision outputs.
        if n < 0 or n > 100000:
            return None
        return n

    out = {
        "north": _num(parsed.get("north_geomean")),
        "south": _num(parsed.get("south_geomean")),
        "source": "gemini",
    }
    date = parsed.get("test_date")
    if isinstance(date, str) and len(date) == 10 and date[4] == "-" and date[7] == "-":
        out["test_date"] = date
    if out["north"] is None and out["south"] is None:
        return None
    return out
