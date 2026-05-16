"""OCR helper: extract E. coli MPN/100ml readings from a Puffer's Pond
water-quality test PDF.

The Town of Amherst publishes weekly results as scanned PDFs (no text
layer), so we shell out to ``pdftoppm`` + ``tesseract`` if available.
Returns ``None`` if the binaries aren't installed or the OCR pass
produces nothing recognizable — callers should treat missing numbers
as "unknown" and fall back to the human-readable status string.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path


_BEACH_NUM_RE = re.compile(
    r"\b(north|south)\b[^\d]{0,40}?(\d{1,5}(?:\.\d+)?)", re.I,
)
_LABELED_NUM_RE = re.compile(
    r"(\d{1,5}(?:\.\d+)?)\s*(?:mpn|cfu|colonies)?\s*/\s*100\s*m[lL]", re.I,
)


def _tools_available() -> bool:
    return bool(shutil.which("pdftoppm") and shutil.which("tesseract"))


def _ocr_pdf(pdf_bytes: bytes) -> str | None:
    if not _tools_available():
        return None
    with tempfile.TemporaryDirectory() as tmp:
        tmpd = Path(tmp)
        pdf = tmpd / "report.pdf"
        pdf.write_bytes(pdf_bytes)
        # Render to 300dpi grayscale PNGs.
        try:
            subprocess.run(
                ["pdftoppm", "-r", "300", "-png", "-gray", str(pdf), str(tmpd / "page")],
                check=True, capture_output=True, timeout=60,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return None
        text_parts: list[str] = []
        for png in sorted(tmpd.glob("page-*.png")):
            try:
                r = subprocess.run(
                    ["tesseract", str(png), "-", "--psm", "6"],
                    check=True, capture_output=True, timeout=60, text=True,
                )
                text_parts.append(r.stdout)
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                continue
        return "\n".join(text_parts) if text_parts else None


def parse_ocr_text(text: str) -> dict | None:
    """Pick out per-beach E. coli MPN/100ml values from an OCR transcript.

    The Town's report layout varies year to year; rather than parsing a
    fixed table we look for beach-name → number pairs anywhere in the
    text. Returns ``{"north": float|None, "south": float|None,
    "raw_text": str}`` if any number was found.
    """
    if not text:
        return None
    out = {"north": None, "south": None, "raw_text": text}
    for m in _BEACH_NUM_RE.finditer(text):
        beach = m.group(1).lower()
        try:
            val = float(m.group(2))
        except ValueError:
            continue
        # Skip values that look like dates (e.g. 2025) or single-digit junk.
        if val > 100000 or val == 0:
            continue
        key = "north" if beach.startswith("n") else "south"
        if out[key] is None:
            out[key] = val
    if out["north"] is None and out["south"] is None:
        return None
    return out


def extract_puffer_results(pdf_bytes: bytes) -> dict | None:
    text = _ocr_pdf(pdf_bytes)
    if text is None:
        return None
    return parse_ocr_text(text)
