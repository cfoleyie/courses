"""Which delivery is being planned, and which one sets the horizon."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from trolley.slots import SlotSpec, planning_window, upcoming, weekday_number

from conftest import DUBLIN

SPECS = [SlotSpec(day="monday", at="08:00"), SlotSpec(day="friday", at="08:00")]


def at(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=DUBLIN)


@pytest.mark.parametrize(
    "now, slot, horizon",
    [
        # Sunday evening: the Monday order is the one being built.
        ("2026-09-13T19:00", date(2026, 9, 14), date(2026, 9, 18)),
        # Thursday evening: Friday's order, with Monday as the fallback.
        ("2026-09-17T20:00", date(2026, 9, 18), date(2026, 9, 21)),
        # Monday morning after the van has been: attention moves to Friday.
        ("2026-09-14T09:00", date(2026, 9, 18), date(2026, 9, 21)),
        # Right on the slot time, the slot has gone.
        ("2026-09-14T08:00", date(2026, 9, 18), date(2026, 9, 21)),
    ],
)
def test_the_window_follows_the_week(now: str, slot: date, horizon: date) -> None:
    planned, next_up = planning_window(SPECS, at(now))
    assert (planned.day, next_up.day) == (slot, horizon)


def test_a_single_weekly_delivery_still_has_a_horizon() -> None:
    planned, next_up = planning_window([SlotSpec(day="monday")], at("2026-09-13T19:00"))
    assert (next_up.day - planned.day).days == 7


def test_slots_come_back_in_order() -> None:
    slots = upcoming(SPECS, at("2026-09-13T19:00"), count=4)
    assert [s.day for s in slots] == [
        date(2026, 9, 14), date(2026, 9, 18), date(2026, 9, 21), date(2026, 9, 25)
    ]


def test_no_slots_means_no_window() -> None:
    assert planning_window([], at("2026-09-13T19:00")) is None
    assert upcoming([], at("2026-09-13T19:00")) == []


def test_labels_fall_back_to_the_day() -> None:
    assert SlotSpec(day="friday").title() == "Friday delivery"
    assert SlotSpec(day="friday", label="Weekend shop").title() == "Weekend shop"


def test_a_misspelled_day_is_caught_early() -> None:
    with pytest.raises(ValueError, match="unknown weekday"):
        weekday_number("moonday")
