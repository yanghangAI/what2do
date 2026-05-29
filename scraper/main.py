"""Entry point: run all scrapers, merge with previous JSON, write data/hours.json."""
from __future__ import annotations
import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from scraper.merge import merge_results
from scraper.models import Facility, HoursDoc, Location, DAYS as DAYS_TUPLE
from bs4 import BeautifulSoup
from scraper import gemini_sources
from scraper.scrape_recwell import SOURCE_URL as RECWELL_URL, scrape_recwell
from scraper.scrape_recwell import FACILITIES as RECWELL_FACILITIES, _section_text_after
from scraper.watchdog import apply_hours_watchdog, run_source, schedule_empty, schedule_equal, mullins_empty, mullins_equal, overrides_empty, overrides_equal
from scraper.scrape_programs import fetch_programs
from scraper.scrape_puffer import SOURCE_URL as PUFFER_URL, fetch_puffer
from scraper.scrape_schedule import fetch_schedule_text, parse_schedule_text
from scraper.scrape_alert import (
    fetch_alert,
    mask_pre_start_days,
    merge_alert_state,
    parse_alert_overrides,
    parse_holidays,
)

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


def _run_recwell() -> tuple[list[tuple[str, dict | None, Exception | None]], str | None]:
    try:
        html = _fetch_recwell_html()
        records = scrape_recwell(html)
        return [(r["id"], r, None) for r in records], html
    except Exception as e:
        print(f"recwell scrape failed: {e}", file=sys.stderr)
        return [
            ("boyden-pool", None, e),
            ("curry-hicks-pool", None, e),
            ("rockwell-climbing", None, e),
        ], None


def _run_mullins() -> tuple[tuple[str, dict | None, Exception | None], str | None]:
    from scraper.scrape_mullins import fetch_mullins_html, parse_mullins_html
    try:
        html = fetch_mullins_html()
        return ("mullins-ice", parse_mullins_html(html), None), html
    except Exception as e:
        print(f"mullins scrape failed: {e}", file=sys.stderr)
        return ("mullins-ice", None, e), None


def main() -> int:
    now_iso = datetime.now(TZ).isoformat(timespec="seconds")
    prev = _load_previous()

    try:
        prev_raw = json.loads(OUT_PATH.read_text()) if OUT_PATH.exists() else {}
    except Exception as e:
        print(f"warning: could not parse previous hours.json: {e}", file=sys.stderr)
        prev_raw = {}

    results: list[tuple[str, dict | None, Exception | None]] = []
    recwell_results, recwell_html = _run_recwell()
    results.extend(recwell_results)
    mullins_result, mullins_html = _run_mullins()
    results.append(mullins_result)

    doc = merge_results(results, prev, now_iso=now_iso)

    divergences = []
    extract_meta = {}
    if recwell_html:
        soup = BeautifulSoup(recwell_html, "html.parser")
        section_texts = {
            fac["id"]: _section_text_after(soup, fac["match"])
            for fac in RECWELL_FACILITIES
        }
        divs, meta = apply_hours_watchdog(
            doc.facilities, section_texts,
            prev_meta=prev_raw.get("extract_meta") or {},
            gemini_fn=gemini_sources.gemini_facility_hours,
        )
        divergences.extend(divs)
        extract_meta.update(meta)

    if mullins_html:
        mfac = next((f for f in doc.facilities if f.id == "mullins-ice"), None)
        if mfac is not None:
            dec, meta, _ = run_source(
                "mullins-ice", parser_value=mfac.events or [],
                fetched_text=mullins_html,
                prev_meta=(prev_raw.get("extract_meta") or {}).get("mullins-ice"),
                gemini_fn=gemini_sources.gemini_mullins,
                is_empty=mullins_empty, equals=mullins_equal,
            )
            if dec.used_backup:
                mfac.events = dec.shipped
            if dec.divergence is not None:
                divergences.append(dec.divergence)
            extract_meta["mullins-ice"] = meta

    try:
        programs = fetch_programs()
    except Exception as e:
        print(f"programs scrape failed: {e}", file=sys.stderr)
        programs = prev_raw.get("programs", [])

    try:
        schedule_text = fetch_schedule_text()
        schedule = parse_schedule_text(schedule_text)
        dec, meta, _ = run_source(
            "schedule", parser_value=schedule, fetched_text=schedule_text,
            prev_meta=(prev_raw.get("extract_meta") or {}).get("schedule"),
            gemini_fn=gemini_sources.gemini_schedule,
            is_empty=schedule_empty, equals=schedule_equal,
        )
        if dec.used_backup:
            schedule = dec.shipped
        if dec.divergence is not None:
            divergences.append(dec.divergence)
        extract_meta["schedule"] = meta
    except Exception as e:
        print(f"schedule scrape failed: {e}", file=sys.stderr)
        schedule = prev_raw.get("schedule", [])

    try:
        alert = fetch_alert()
    except Exception as e:
        print(f"alert scrape failed: {e}", file=sys.stderr)
        alert = prev_raw.get("alert")

    if alert:
        det = {"overrides": {fid: {"start_date": ov.get("start_date"),
                                    "closed_from": ov.get("closed_from"),
                                    "hours": {d: [iv.to_dict() for iv in ov["hours"].get(d, [])]
                                              for d in DAYS_TUPLE}}
                              for fid, ov in parse_alert_overrides(alert).items()},
               "holidays": parse_holidays(alert)}
        dec, meta, _ = run_source(
            "alert-overrides", parser_value=det, fetched_text=alert,
            prev_meta=(prev_raw.get("extract_meta") or {}).get("alert-overrides"),
            gemini_fn=gemini_sources.gemini_overrides,
            is_empty=overrides_empty, equals=overrides_equal,
        )
        # REVIEW-ONLY: never apply dec.shipped — record divergence only.
        if dec.divergence is not None:
            divergences.append(dec.divergence)
        extract_meta["alert-overrides"] = meta

    today_dt = datetime.now(TZ).date()
    today_iso = today_dt.strftime("%Y-%m-%d")
    overrides = parse_alert_overrides(alert) if alert else {}
    prev_state = prev_raw.get("alert_state")
    if prev_state is None and prev_raw.get("alert"):
        # Bootstrap from the previous alert text when alert_state hasn't been
        # persisted yet (e.g. first run after this field was added).
        prev_overrides = parse_alert_overrides(prev_raw["alert"])
        prev_state = {
            fid: {"start_date": ov.get("start_date"), "closed_from": ov.get("closed_from")}
            for fid, ov in prev_overrides.items()
        }
    overrides, alert_state = merge_alert_state(overrides, prev_state)

    overridden_ids: list[str] = []
    for facility in doc.facilities:
        ov = overrides.get(facility.id)
        if not ov:
            continue
        start = ov.get("start_date")
        closed_from = ov.get("closed_from")
        # Gap window: today is before start_date AND at least one of the
        # following is true:
        #   * explicit closed_from (parsed from "will close at <date>") passed
        #   * scraped hours == override hours (upstream has flipped to future
        #     summer hours already — definitive evidence of the gap)
        #   * within a 14-day fallback window before start_date (UMass often
        #     deletes the explicit close-date sentence shortly after it
        #     passes, leaving us only the start_date to reason from)
        fallback_close = (
            (date.fromisoformat(start) - timedelta(days=14)).isoformat()
            if start else None
        )
        in_gap = bool(start and today_iso < start and (
            (closed_from and today_iso >= closed_from)
            or facility.hours == ov["hours"]
            or (fallback_close and today_iso >= fallback_close)
        ))
        if start and today_iso >= start:
            facility.hours = ov["hours"]
            facility.notes = list(facility.notes) + [
                f"Summer hours from RecWell alert (effective {start})."
            ]
            overridden_ids.append(facility.id + " [summer]")
        elif in_gap:
            facility.hours = mask_pre_start_days(today_dt, ov["hours"], start)
            facility.notes = list(facility.notes) + [
                f"Closed for semester transition; summer hours begin {start}."
            ]
            overridden_ids.append(facility.id + " [closed-gap]")
    if overridden_ids:
        print(f"applied alert overrides to: {', '.join(overridden_ids)}", file=sys.stderr)

    # Puffer's Pond water quality (separate data source — Town of Amherst).
    prev_puffer_wq = None
    for f in prev_raw.get("facilities", []):
        if f.get("id") == "puffer-pond":
            prev_puffer_wq = f.get("water_quality")
            break
    try:
        puffer = fetch_puffer(prev=prev_puffer_wq)
        wq = puffer.to_dict() if puffer else prev_puffer_wq
        puffer_status = "ok" if puffer else ("stale" if prev_puffer_wq else "failed")
    except Exception as e:
        print(f"puffer scrape failed: {e}", file=sys.stderr)
        wq = prev_puffer_wq
        puffer_status = "stale" if prev_puffer_wq else "failed"
    doc.facilities.append(Facility(
        id="puffer-pond",
        name="Puffer's Pond",
        category="swim",
        location=Location(
            label="Puffer's Pond, North Amherst",
            maps_url="https://www.google.com/maps/search/?api=1&query=Puffer%27s+Pond+Amherst+MA",
        ),
        source_url=PUFFER_URL,
        hours={d: [] for d in ("mon","tue","wed","thu","fri","sat","sun")},
        notes=[],
        scrape_status=puffer_status,
        last_scraped=now_iso,
        water_quality=wq,
    ))

    out = doc.to_dict()
    out["programs"] = programs
    out["schedule"] = schedule
    out["alert"] = alert
    out["alert_state"] = alert_state
    out["holidays"] = parse_holidays(alert)
    out["extract_meta"] = {**(prev_raw.get("extract_meta") or {}), **extract_meta}
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, indent=2) + "\n")
    print(f"wrote {OUT_PATH}")

    from scraper.watchdog import format_divergence_report
    md, warnings = format_divergence_report(divergences)
    for w in warnings:
        print(w)  # GitHub Actions ::warning:: annotations
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if md and summary_path:
        with open(summary_path, "a") as fh:
            fh.write(md)
    # Drop a machine-readable signal for the workflow gate step.
    Path(OUT_PATH.parent.parent / ".divergences").write_text(str(len(divergences)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
