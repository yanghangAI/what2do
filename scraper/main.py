"""Entry point: run all scrapers, merge with previous JSON, write data/hours.json."""
from __future__ import annotations
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from scraper.merge import merge_results
from scraper.models import HoursDoc
from scraper.scrape_recwell import SOURCE_URL as RECWELL_URL, scrape_recwell
from scraper.scrape_mullins import scrape_mullins

OUT_PATH = Path(__file__).resolve().parent.parent / "data" / "hours.json"
TZ = ZoneInfo("America/New_York")


def _load_previous() -> HoursDoc | None:
    if not OUT_PATH.exists():
        return None
    try:
        return HoursDoc.from_dict(json.loads(OUT_PATH.read_text()))
    except Exception:
        return None


def _fetch_recwell_html() -> str:
    r = requests.get(RECWELL_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    r.raise_for_status()
    return r.text


def _run_recwell() -> list[tuple[str, dict | None, Exception | None]]:
    try:
        html = _fetch_recwell_html()
        records = scrape_recwell(html)
        return [(r["id"], r, None) for r in records]
    except Exception as e:
        print(f"recwell scrape failed: {e}", file=sys.stderr)
        # Mark all three RecWell facilities as failed
        return [
            ("boyden-pool", None, e),
            ("curry-hicks-pool", None, e),
            ("rockwell-climbing", None, e),
        ]


def _run_mullins() -> tuple[str, dict | None, Exception | None]:
    try:
        return ("mullins-ice", scrape_mullins(), None)
    except Exception as e:
        print(f"mullins scrape failed: {e}", file=sys.stderr)
        return ("mullins-ice", None, e)


def main() -> int:
    now_iso = datetime.now(TZ).isoformat(timespec="seconds")
    prev = _load_previous()

    results: list[tuple[str, dict | None, Exception | None]] = []
    results.extend(_run_recwell())
    results.append(_run_mullins())

    doc = merge_results(results, prev, now_iso=now_iso)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(doc.to_dict(), indent=2) + "\n")
    print(f"wrote {OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
