"""Scrape program/class listings from the RecWell registration site.

Each program has a Register button — we surface them with a sign-up flag and a
deep link to the official program page. We don't try to extract per-session
dates and times (those live behind JS on the detail page).
"""
from __future__ import annotations
import re
import requests
from bs4 import BeautifulSoup

CATEGORIES = [
    {
        "category": "climbing",
        "url": "https://recwell.umass.edu/Program/GetProducts?classification=c0cbe4c1-25c5-45f6-a571-59f756da5f09",
    },
    {
        "category": "fitness",
        "url": "https://recwell.umass.edu/Program/GetProducts?classification=00000000-0000-0000-0000-000000026001",
    },
]

EXCLUDED_NAME_PATTERNS = [
    re.compile(r"15\s*minute\s*climbing\s*orientation", re.I),
]

# Each link's visible text is prefixed by a material-icons token (e.g.
# "fitness_center Pilates 60") and suffixed by " $0".
_ICON_PREFIX = re.compile(r"^[a-z][a-z_]+\s+")
_PRICE_SUFFIX = re.compile(r"\s*\$\d+(?:\.\d+)?\s*$")


def _clean_name(text: str) -> str:
    text = _PRICE_SUFFIX.sub("", text).strip()
    text = _ICON_PREFIX.sub("", text)
    return text.strip()


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "program"


def parse_programs_html(html: str, category: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    items: list[dict] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "GetProgramDetails" not in href:
            continue
        name = _clean_name(a.get_text(" ", strip=True))
        if not name or any(p.search(name) for p in EXCLUDED_NAME_PATTERNS):
            continue
        if name in seen:
            continue
        seen.add(name)
        url = href if href.startswith("http") else "https://recwell.umass.edu" + (
            href if href.startswith("/") else "/" + href
        )
        items.append({
            "id": f"{category}-{_slugify(name)}",
            "name": name,
            "category": category,
            "signup_required": True,
            "url": url,
        })
    return items


def fetch_programs() -> list[dict]:
    items: list[dict] = []
    for cat in CATEGORIES:
        r = requests.get(cat["url"], headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
        r.raise_for_status()
        items.extend(parse_programs_html(r.text, cat["category"]))
    return items
