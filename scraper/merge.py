"""Combine per-facility scrape results with the previous JSON, applying staleness rules."""
from __future__ import annotations
from typing import Iterable
from scraper.models import Facility, HoursDoc, Interval, Location, DAYS

TIMEZONE = "America/New_York"


def _facility_from_result(result: dict, now_iso: str) -> Facility:
    hours: dict[str, list[Interval]] = {}
    for d in DAYS:
        hours[d] = list(result["hours"].get(d, []))
    return Facility(
        id=result["id"],
        name=result["name"],
        category=result["category"],
        location=Location(label=result["location_label"], maps_url=result["maps_url"]),
        source_url=result["source_url"],
        hours=hours,
        notes=list(result.get("notes", [])),
        scrape_status="ok",
        last_scraped=now_iso,
        events=list(result["events"]) if result.get("events") is not None else None,
    )


def _stale_from_previous(prev_facility: Facility) -> Facility:
    return Facility(
        id=prev_facility.id,
        name=prev_facility.name,
        category=prev_facility.category,
        location=prev_facility.location,
        source_url=prev_facility.source_url,
        hours={d: list(prev_facility.hours.get(d, [])) for d in DAYS},
        notes=list(prev_facility.notes),
        scrape_status="stale",
        last_scraped=prev_facility.last_scraped,
        events=list(prev_facility.events) if prev_facility.events is not None else None,
    )


def _failed_placeholder(facility_id: str, now_iso: str) -> Facility:
    return Facility(
        id=facility_id,
        name=facility_id,
        category="swim",
        location=Location(label="", maps_url=""),
        source_url="",
        hours={d: [] for d in DAYS},
        notes=[],
        scrape_status="failed",
        last_scraped=now_iso,
    )


def merge_results(
    results: Iterable[tuple[str, dict | None, Exception | None]],
    prev: HoursDoc | None,
    now_iso: str,
) -> HoursDoc:
    prev_by_id: dict[str, Facility] = {}
    if prev is not None:
        prev_by_id = {f.id: f for f in prev.facilities}

    facilities: list[Facility] = []
    any_success = False

    for facility_id, result, error in results:
        if error is None and result is not None:
            facilities.append(_facility_from_result(result, now_iso))
            any_success = True
        elif facility_id in prev_by_id:
            facilities.append(_stale_from_previous(prev_by_id[facility_id]))
        else:
            facilities.append(_failed_placeholder(facility_id, now_iso))

    last_updated = now_iso if any_success else (prev.last_updated if prev else now_iso)
    return HoursDoc(last_updated=last_updated, timezone=TIMEZONE, facilities=facilities)
