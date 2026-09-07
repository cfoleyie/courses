"""The domain core: an append-only minute ledger and the Switch limit it implies.

Everything here is pure. No database, no network, no clock of its own — which
is what makes the awkward parts (daily caps, rollover, translating a balance
into a console limit) cheap to test.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Iterable, Sequence

from .config import Rules


class Kind(StrEnum):
    """Why minutes moved."""

    EARN_IXL = "earn_ixl"        # the poller saw a finished IXL skill
    EARN_MANUAL = "earn_manual"  # a kid asked, a parent approved
    ADJUST = "adjust"            # a parent added or removed minutes by hand
    CONSUME = "consume"          # the console reported play time
    EXPIRE = "expire"            # end-of-day burn-off when rollover is off


class Status(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


#: Kinds that count towards the daily earn cap. An approved manual claim uses
#: up cap headroom like an IXL lesson does, but is not itself trimmed by it:
#: a parent tapping Yes is a deliberate override, the same as an ADJUST.
EARN_KINDS = frozenset({Kind.EARN_IXL, Kind.EARN_MANUAL})


@dataclass(frozen=True, slots=True)
class Event:
    kid_id: str
    kind: Kind
    minutes: int
    day: str                       # local YYYY-MM-DD, the day it counts against
    created_at: datetime
    status: Status = Status.APPROVED
    ref: str | None = None         # dedupe key, unique per kid
    note: str = ""
    id: int | None = None

    @property
    def counts(self) -> bool:
        return self.status is Status.APPROVED


def balance(events: Iterable[Event]) -> int:
    """Minutes available to spend right now."""
    return sum(e.minutes for e in events if e.counts)


def earned_on(events: Iterable[Event], day: str) -> int:
    """Minutes credited on `day`, ignoring spend. Drives the daily earn cap."""
    return sum(e.minutes for e in events if e.counts and e.kind in EARN_KINDS and e.day == day)


def grantable_minutes(
    events: Sequence[Event],
    day: str,
    wanted: int,
    rules: Rules,
) -> int:
    """How much of `wanted` we may actually credit today.

    Trimmed by both the daily earn cap and the ceiling on a stored balance, so
    a big catch-up session cannot bank a week of console time in one evening.
    """
    if wanted <= 0:
        return 0
    room_today = max(0, rules.daily_earn_cap_minutes - earned_on(events, day))
    room_total = max(0, rules.max_balance_minutes - balance(events))
    return max(0, min(wanted, room_today, room_total))


def consumption_delta(previous_seen: int | None, playing_time: int) -> int:
    """Minutes played since we last looked.

    `playing_time` is the console's own running total for today, so it climbs
    through the day and drops back to zero at midnight. A drop means a new day
    started (or Nintendo re-reported), and the right answer is zero rather than
    a negative charge.
    """
    if previous_seen is None:
        # First sighting of the day. Whatever is on the clock was played before
        # we were watching, so charging for it would double-bill.
        return 0
    if playing_time < previous_seen:
        return 0
    return playing_time - previous_seen


def target_daily_limit(
    current_balance: int,
    played_today: int,
    rules: Rules,
    *,
    ceiling: int = 360,
) -> int:
    """The console's daily play-time limit that leaves exactly `current_balance` to play.

    Nintendo enforces a *total for the day*, not a countdown, so the limit has
    to be what has already been played plus what is still owed. Computing it
    from absolute values rather than nudging it makes every write idempotent:
    a retried or duplicated sync lands on the same number.
    """
    target = played_today + max(0, current_balance)
    target = max(target, rules.floor_minutes)
    return max(0, min(target, ceiling))


def expiry_event(
    events: Sequence[Event],
    kid_id: str,
    day: str,
    now: datetime,
    rules: Rules,
) -> Event | None:
    """Burn off a leftover balance when rollover is disabled."""
    if rules.rollover:
        return None
    leftover = balance(events)
    if leftover <= 0:
        return None
    return Event(
        kid_id=kid_id,
        kind=Kind.EXPIRE,
        minutes=-leftover,
        day=day,
        created_at=now,
        ref=f"expire:{day}",
        note=f"{leftover} min expired at end of day",
    )


def approve(event: Event, *, approved: bool = True) -> Event:
    return replace(event, status=Status.APPROVED if approved else Status.REJECTED)


def local_day(moment: datetime) -> str:
    return moment.date().isoformat()


def today_str(tz) -> str:  # noqa: ANN001 - tzinfo-like
    return datetime.now(tz).date().isoformat()


def humanise(minutes: int) -> str:
    """`95` -> `1h 35m`, for the UI and log lines."""
    minutes = int(round(minutes))
    sign = "-" if minutes < 0 else ""
    minutes = abs(minutes)
    hours, mins = divmod(minutes, 60)
    if not hours:
        return f"{sign}{mins}m"
    if not mins:
        return f"{sign}{hours}h"
    return f"{sign}{hours}h {mins}m"


__all__ = [
    "Event",
    "Kind",
    "Status",
    "balance",
    "consumption_delta",
    "earned_on",
    "expiry_event",
    "grantable_minutes",
    "humanise",
    "local_day",
    "target_daily_limit",
]
