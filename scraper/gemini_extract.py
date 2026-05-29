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

# Public override knob; everything else in this module is internal.
MODEL_CANDIDATES = ("gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.0-flash")
_URL_TMPL = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)
_ANTI_HALLUCINATION = (
    "Extract only what is explicitly present in the text. If a day or field is "
    "not listed, return it as closed/empty/null. Never guess or invent values."
)


def extract(text, *, schema, instructions, api_key=None, models=MODEL_CANDIDATES):
    api_key = api_key or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None
    prompt = f"{instructions}\n\n{_ANTI_HALLUCINATION}\n\nTEXT:\n{text}"
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
        for i, attempt in enumerate((1, 2)):
            r = requests.post(url, json=body, timeout=60)
            if r.status_code == 200:
                payload = r.json()
                break
            if r.status_code == 429 and '"limit": 0' in r.text:
                break  # model not free-tier eligible — try next
            if r.status_code not in (429, 500, 502, 503, 504):
                break  # non-retryable
            if i == 0:
                time.sleep(2 ** attempt)  # only sleep between attempts
        if payload is not None:
            break
    if payload is None:
        return None
    try:
        out_text = payload["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(out_text)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError):
        return None
