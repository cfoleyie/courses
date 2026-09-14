"""Deciding when the reminder goes out, in one place.

The server checks this on a timer and the command line checks it from cron.
Both need the same two guards, and having them in only one of the two is how
you end up either missing the reminder or getting it every half hour all week:

- it is not sent until the delivery is close enough to still change the order;
- and it is sent once per delivery, whatever restarts or re-runs happen.

The second guard is what makes `trolley notify` safe to run from cron as often
as you like, and what stops a server restart inside the window from repeating
a list that has already gone out.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable

from . import notify, suggest
from .config import Config
from .db import Database


@dataclass(frozen=True, slots=True)
class Outcome:
    """What the check decided, and why, in words worth printing."""

    sent: bool
    reason: str


def marker_for(slot_day) -> str:
    """The state key recording that this delivery's reminder has gone."""
    return f"notified:{slot_day.isoformat()}"


def send_if_due(
    db: Database,
    config: Config,
    now: datetime | None = None,
    *,
    force: bool = False,
    send: Callable[..., None] = notify.send,
) -> Outcome:
    """Send the reminder for the next delivery, if this is the moment for it.

    `force` skips both guards and does not record that it happened, because it
    is somebody asking for the list by hand: the scheduled one should still go
    out at its usual time.
    """
    report = suggest.build(db, config, now)
    if report is None:
        return Outcome(False, "no delivery slots are configured")

    moment = report.generated_at
    body = suggest.render_text(report)
    subject = f"Trolley: {len(report.suggestions)} for {report.slot.label}"

    if force:
        send(config.notify, subject, body)
        return Outcome(True, f"sent the list for {report.slot.label}")

    lead = report.slot.at - moment
    if lead > timedelta(hours=config.notify.hours_before):
        hours = lead.total_seconds() / 3600
        return Outcome(
            False,
            f"{report.slot.label} is {hours:.0f} hours away; "
            f"the reminder goes out {config.notify.hours_before:g} hours before",
        )

    marker = marker_for(report.slot.day)
    if db.get_state(marker):
        return Outcome(False, f"already sent the reminder for {report.slot.label}")

    if not report.suggestions:
        # Record it anyway: nothing due is an answer, and re-checking every
        # few minutes for the rest of the window would not change it.
        db.set_state(marker, "empty")
        return Outcome(False, f"nothing looks due for {report.slot.label}")

    send(config.notify, subject, body)
    db.set_state(marker, moment.isoformat(timespec="seconds"))
    return Outcome(True, f"sent {len(report.suggestions)} suggestions for {report.slot.label}")
