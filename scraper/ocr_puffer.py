"""OCR helper: extract E. coli MPN/100ml geomeans from a Puffer's Pond
water-quality test PDF.

The Town of Amherst publishes weekly results as scanned chain-of-custody
forms. Single-sample values are filled in by hand and tesseract can't
read them reliably, but the **5-sample geometric mean** for each beach
is typewritten on a stable line ("South Beach Geometric Mean of 5 most
recent samples: <N>") — readable enough with light digit/letter
correction. We target only those geomeans and return ``None`` (rather
than guess) when the OCR pass doesn't find them.

Returns ``None`` when ``pdftoppm``/``tesseract`` aren't installed, so
local dev / unit tests stay self-contained.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path


# Match "<beach> beach … geometric mean …" — case-insensitive, allow
# newlines and noise between the words.
_GEOMEAN_LABEL_RE = re.compile(
    r"(north|south)\s*beach[^\n]{0,40}?geometric\s+mean", re.I,
)

# Common tesseract confusions on these scans.
_DIGIT_FIXES = str.maketrans({
    "S": "5", "s": "5",
    "O": "0", "o": "0",
    "l": "1", "I": "1", "i": "1",
    "B": "8",
    "Z": "2", "z": "2",
})

_TOKEN_RE = re.compile(r"[A-Za-z0-9.]{2,}")
# Strict numeric format after digit-fixing: require a decimal point. The
# "Geometric Mean of 5 samples" is always a quotient, so the typewritten
# values on these forms are reliably formatted like "45.54" / "4.17".
# Requiring the dot keeps integer junk ("17" from a date column, "100"
# from "MPN/100ml") from being mistaken for a real reading.
_STRICT_NUM_RE = re.compile(r"^\d{1,4}\.\d{1,2}$")


def _tools_available() -> bool:
    return bool(shutil.which("pdftoppm") and shutil.which("tesseract"))


def _ocr_pdf(pdf_bytes: bytes) -> str | None:
    if not _tools_available():
        return None
    with tempfile.TemporaryDirectory() as tmp:
        tmpd = Path(tmp)
        pdf = tmpd / "report.pdf"
        pdf.write_bytes(pdf_bytes)
        try:
            subprocess.run(
                ["pdftoppm", "-r", "400", "-png", "-gray",
                 str(pdf), str(tmpd / "page")],
                check=True, capture_output=True, timeout=90,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return None
        text_parts: list[str] = []
        for png in sorted(tmpd.glob("page-*.png")):
            try:
                r = subprocess.run(
                    ["tesseract", str(png), "-", "--psm", "6"],
                    check=True, capture_output=True, timeout=90, text=True,
                )
                text_parts.append(r.stdout)
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                continue
        return "\n".join(text_parts) if text_parts else None


def parse_ocr_text(text: str) -> dict | None:
    """Pick out per-beach geomean values from an OCR transcript.

    Returns ``{"north": float|None, "south": float|None, "kind":
    "geomean", "raw_text": str}`` when at least one geomean was found,
    else ``None``.
    """
    if not text:
        return None
    # "kind": "estimate" because the form's mixed typewritten/handwritten
    # layout makes it hard to tell whether the captured number is the
    # 5-sample geomean (typewritten under "Analysis | Analysis") or the
    # single-sample value from the table below — the frontend should
    # label these as best-effort estimates and link to the source PDF.
    out = {"north": None, "south": None, "kind": "estimate", "raw_text": text}
    for label_m in _GEOMEAN_LABEL_RE.finditer(text):
        beach = label_m.group(1).lower()
        window = text[label_m.end(): label_m.end() + 150]
        key = "north" if beach.startswith("n") else "south"
        for tok_m in _TOKEN_RE.finditer(window):
            tok = tok_m.group(0)
            # Skip tokens that had no real digits before fixing (avoids
            # turning "of"→"0f" or "Analysis"→"Ana1y515" into numbers).
            if not any(c.isdigit() for c in tok):
                continue
            fixed = tok.translate(_DIGIT_FIXES)
            if not _STRICT_NUM_RE.match(fixed):
                continue
            try:
                val = float(fixed)
            except ValueError:
                continue
            if val <= 0 or val > 100000:
                continue
            if out[key] is None:
                out[key] = val
                break
    if out["north"] is None and out["south"] is None:
        return None
    return out


def extract_puffer_results(pdf_bytes: bytes) -> dict | None:
    text = _ocr_pdf(pdf_bytes)
    if text is None:
        return None
    return parse_ocr_text(text)
