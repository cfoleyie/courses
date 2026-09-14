"""When the reminder goes out.

The server checks this on a timer and cron checks it by running the command,
so both guards have to live here: close enough to the delivery to matter, and
once per delivery no matter how often the question is asked.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from trolley.config import Config, NotifyConfig
from trolley.db import Database
from trolley.importers import FakeImporter
from trolley.ingest import ingest
from trolley.reminders import marker_for, send_if_due

from conftest import DUBLIN, TODAY

SUNDAY_EVENING = datetime(2026, 9, 13, 19, 0, tzinfo=DUBLIN)
FRIDAY_MORNING = datetime(2026, 9, 11, 9, 0, tzinfo=DUBLIN)


class Outbox:
    """Stands in for the notifier, so nothing leaves the test."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def __call__(self, config, subject: str, body: str) -> None:
        self.sent.append((subject, body))


@pytest.fixture
def notifying(config: Config) -> Config:
    return replace(config, notify=NotifyConfig(enabled=True, channel="console", hours_before=14))


@pytest.fixture
def stocked(db: Database, config: Config) -> Database:
    ingest(db, FakeImporter().generate(weeks=30, today=TODAY), config)
    return db


def test_the_reminder_waits_until_it_can_still_change_the_order(stocked, notifying) -> None:
    outbox = Outbox()
    outcome = send_if_due(stocked, notifying, FRIDAY_MORNING, send=outbox)

    assert not outcome.sent and not outbox.sent
    assert "hours away" in outcome.reason


def test_it_goes_out_once_inside_the_window(stocked, notifying) -> None:
    outbox = Outbox()
    outcome = send_if_due(stocked, notifying, SUNDAY_EVENING, send=outbox)

    assert outcome.sent and len(outbox.sent) == 1
    subject, body = outbox.sent[0]
    assert "Monday delivery" in subject and "Monday delivery" in body


def test_asking_again_does_not_send_again(stocked, notifying) -> None:
    """This is what makes it safe to run from cron every few minutes."""
    outbox = Outbox()
    send_if_due(stocked, notifying, SUNDAY_EVENING, send=outbox)
    later = send_if_due(stocked, notifying, SUNDAY_EVENING + timedelta(minutes=30), send=outbox)

    assert not later.sent and len(outbox.sent) == 1
    assert "already sent" in later.reason


def test_running_it_every_ten_minutes_all_evening_sends_one(stocked, notifying) -> None:
    outbox = Outbox()
    moment = SUNDAY_EVENING
    for _ in range(60):
        send_if_due(stocked, notifying, moment, send=outbox)
        moment += timedelta(minutes=10)
    assert len(outbox.sent) == 1


def test_the_next_delivery_gets_its_own_reminder(stocked, notifying) -> None:
    outbox = Outbox()
    send_if_due(stocked, notifying, SUNDAY_EVENING, send=outbox)
    # Thursday evening, planning Friday: a different delivery, so it goes again.
    send_if_due(stocked, notifying, datetime(2026, 9, 17, 19, 0, tzinfo=DUBLIN), send=outbox)
    assert len(outbox.sent) == 2


def test_nothing_due_is_not_worth_interrupting_for(db, notifying) -> None:
    outbox = Outbox()
    outcome = send_if_due(db, notifying, SUNDAY_EVENING, send=outbox)

    assert not outcome.sent and not outbox.sent
    assert "nothing looks due" in outcome.reason
    # Recorded, so the rest of the window is not spent re-checking.
    assert db.get_state(marker_for(outcome and SUNDAY_EVENING.date() + timedelta(days=1)))


def test_a_machine_that_was_off_still_catches_the_window(stocked, notifying) -> None:
    """Booting at 7am for an 8am delivery is late, but not too late."""
    outbox = Outbox()
    outcome = send_if_due(
        stocked, notifying, datetime(2026, 9, 14, 7, 0, tzinfo=DUBLIN), send=outbox
    )
    assert outcome.sent


def test_a_machine_that_was_off_all_window_moves_to_the_next_delivery(stocked, notifying) -> None:
    outbox = Outbox()
    # Monday 9am: that van has been. Attention is on Friday now, which is far off.
    outcome = send_if_due(
        stocked, notifying, datetime(2026, 9, 14, 9, 0, tzinfo=DUBLIN), send=outbox
    )
    assert not outcome.sent and "Friday delivery" in outcome.reason


def test_forcing_sends_whatever_the_timing(stocked, notifying) -> None:
    outbox = Outbox()
    outcome = send_if_due(stocked, notifying, FRIDAY_MORNING, force=True, send=outbox)
    assert outcome.sent and len(outbox.sent) == 1


def test_forcing_does_not_rob_the_scheduled_one(stocked, notifying) -> None:
    """Asking for the list by hand should not cancel the evening reminder."""
    outbox = Outbox()
    send_if_due(stocked, notifying, SUNDAY_EVENING - timedelta(days=1), force=True, send=outbox)
    scheduled = send_if_due(stocked, notifying, SUNDAY_EVENING, send=outbox)

    assert scheduled.sent and len(outbox.sent) == 2


def test_no_slots_configured_is_explained(db: Database) -> None:
    outbox = Outbox()
    outcome = send_if_due(db, Config(slots=()), SUNDAY_EVENING, send=outbox)
    assert not outcome.sent and "no delivery slots" in outcome.reason
