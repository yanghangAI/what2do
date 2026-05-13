from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
ScrapeStatus = Literal["ok", "stale", "failed"]
Category = Literal["swim", "climbing", "ice", "fitness"]


@dataclass(frozen=True)
class Interval:
    open: str
    close: str

    def to_dict(self) -> dict:
        return {"open": self.open, "close": self.close}

    @classmethod
    def from_dict(cls, d: dict) -> "Interval":
        return cls(open=d["open"], close=d["close"])


@dataclass(frozen=True)
class Location:
    label: str
    maps_url: str

    def to_dict(self) -> dict:
        return {"label": self.label, "maps_url": self.maps_url}

    @classmethod
    def from_dict(cls, d: dict) -> "Location":
        return cls(label=d["label"], maps_url=d["maps_url"])


@dataclass
class Facility:
    id: str
    name: str
    category: Category
    location: Location
    source_url: str
    hours: dict[str, list[Interval]]
    notes: list[str]
    scrape_status: ScrapeStatus
    last_scraped: str

    def __post_init__(self) -> None:
        self.hours = {d: list(self.hours.get(d, [])) for d in DAYS}

    def to_dict(self) -> dict:
        full_hours = {d: [i.to_dict() for i in self.hours.get(d, [])] for d in DAYS}
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "location": self.location.to_dict(),
            "source_url": self.source_url,
            "hours": full_hours,
            "notes": list(self.notes),
            "scrape_status": self.scrape_status,
            "last_scraped": self.last_scraped,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Facility":
        return cls(
            id=d["id"],
            name=d["name"],
            category=d["category"],
            location=Location.from_dict(d["location"]),
            source_url=d["source_url"],
            hours={day: [Interval.from_dict(i) for i in d["hours"].get(day, [])] for day in DAYS},
            notes=list(d.get("notes", [])),
            scrape_status=d["scrape_status"],
            last_scraped=d["last_scraped"],
        )


@dataclass
class HoursDoc:
    last_updated: str
    timezone: str
    facilities: list[Facility] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "last_updated": self.last_updated,
            "timezone": self.timezone,
            "facilities": [f.to_dict() for f in self.facilities],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "HoursDoc":
        return cls(
            last_updated=d["last_updated"],
            timezone=d["timezone"],
            facilities=[Facility.from_dict(f) for f in d.get("facilities", [])],
        )
