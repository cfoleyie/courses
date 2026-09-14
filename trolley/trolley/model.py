"""Core records shared by the store, the engine and the API.

Everything here is a plain dataclass. The database module owns persistence and
the prediction module owns arithmetic, so these stay free of both.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum


class Status(str, Enum):
    """How urgent a suggestion is, relative to the delivery slots around it."""

    OVERDUE = "overdue"  #: The estimated run-out date has already passed.
    DUE = "due"  #: Runs out on or before the slot being planned.
    SOON = "soon"  #: Runs out before the slot after this one, so buy it now.


@dataclass(frozen=True, slots=True)
class Item:
    """A thing bought repeatedly, independent of which brand was picked."""

    id: int | None
    key: str  #: Canonical slug, e.g. "toilet-roll".
    name: str  #: Display name, e.g. "Toilet roll".
    category: str = "other"
    unit: str = "pack"
    #: Set to override the learned interval entirely (days between purchases).
    interval_override: float | None = None
    paused: bool = False
    #: Suppress suggestions for slots delivering on or before this date.
    snoozed_until: date | None = None
    #: Grows each time a suggestion is turned down; stretches the estimate.
    nudge: float = 1.0


@dataclass(frozen=True, slots=True)
class Purchase:
    """One line of one order: this item, this many, this day."""

    id: int | None
    item_id: int
    bought_on: date
    quantity: float = 1.0
    raw_name: str = ""
    order_ref: str | None = None
    source: str = "manual"


@dataclass(frozen=True, slots=True)
class Estimate:
    """What the engine believes about an item's rhythm."""

    item: Item
    #: Days one unit lasts. None when there is not enough history to say.
    unit_interval: float | None
    #: Days the most recent purchase is expected to last (unit x quantity).
    interval: float | None
    last_bought: date | None
    last_quantity: float
    due_on: date | None
    #: 0..1. Blends how many gaps were seen with how consistent they were.
    confidence: float = 0.0
    #: Where the interval came from: "history", "prior", "override" or "none".
    basis: str = "none"
    purchases: int = 0


@dataclass(frozen=True, slots=True)
class Suggestion:
    """An estimate that earned a place on the list for a particular slot."""

    estimate: Estimate
    status: Status
    score: float
    reason: str
    quantity: float = 1.0

    @property
    def item(self) -> Item:
        return self.estimate.item


@dataclass(frozen=True, slots=True)
class ParsedLine:
    """One line an importer pulled out of a receipt, before normalisation."""

    raw_name: str
    quantity: float = 1.0
    price: float | None = None


@dataclass(frozen=True, slots=True)
class ParsedOrder:
    """A whole receipt, as read from an email or a spreadsheet."""

    bought_on: date
    lines: tuple[ParsedLine, ...] = field(default_factory=tuple)
    order_ref: str | None = None
    source: str = "import"
