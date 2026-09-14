"""The delivery calendar: which slot is being planned, and which one follows it.

The second one matters as much as the first. With deliveries on Monday and
Friday, skipping the Monday order means going without until Friday, so the
question at list-building time is always "does this last until the delivery
after next".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def weekday_number(name: str) -> int:
    try:
        return WEEKDAYS.index(name.strip().casefold())
    except ValueError as exc:
        raise ValueError(f"unknown weekday {name!r}; expected one of {', '.join(WEEKDAYS)}") from exc


@dataclass(frozen=True, slots=True)
class Slot:
    """One delivery: when it lands, and what to call it."""

    label: str
    at: datetime

    @property
    def day(self) -> date:
        return self.at.date()

    @property
    def is_today(self) -> bool:
        return self.at.date() == datetime.now(self.at.tzinfo).date()


@dataclass(frozen=True, slots=True)
class SlotSpec:
    """A recurring delivery in the user's week."""

    day: str
    at: str = "08:00"
    label: str = ""

    def parsed_time(self) -> time:
        hour, _, minute = self.at.partition(":")
        return time(int(hour), int(minute or 0))

    def title(self) -> str:
        return self.label or f"{self.day.capitalize()} delivery"


def upcoming(specs: list[SlotSpec], now: datetime, count: int = 2, *, tz: str = "Europe/Dublin") -> list[Slot]:
    """The next `count` deliveries strictly after `now`, in order."""
    if not specs:
        return []
    zone = ZoneInfo(tz)
    now = now.astimezone(zone) if now.tzinfo else now.replace(tzinfo=zone)

    found: list[Slot] = []
    for offset in range(0, 7 * (count + 2)):
        day = now.date() + timedelta(days=offset)
        for spec in specs:
            if day.weekday() != weekday_number(spec.day):
                continue
            at = datetime.combine(day, spec.parsed_time(), tzinfo=zone)
            if at > now:
                found.append(Slot(label=spec.title(), at=at))
        if len(found) >= count:
            break
    found.sort(key=lambda slot: slot.at)
    return found[:count]


def next_by_weekday(slots: list[Slot]) -> dict[str, date]:
    """The soonest upcoming delivery for each weekday that has one.

    Used to answer "when does this item's usual delivery come round again",
    which is what decides whether it can wait for it.
    """
    found: dict[str, date] = {}
    for slot in slots:
        day = WEEKDAYS[slot.at.weekday()]
        found.setdefault(day, slot.day)
    return found


def planning_window(
    specs: list[SlotSpec], now: datetime, *, tz: str = "Europe/Dublin"
) -> tuple[Slot, Slot] | None:
    """The slot being planned and the one after it, which sets the horizon."""
    slots = upcoming(specs, now, count=2, tz=tz)
    return (slots[0], slots[1]) if len(slots) == 2 else None
