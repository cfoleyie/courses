from __future__ import annotations

from datetime import datetime

import pytest

from switchtime.config import Rules
from switchtime.ledger import (
    Event,
    Kind,
    Status,
    balance,
    consumption_delta,
    earned_on,
    expiry_event,
    grantable_minutes,
    humanise,
    target_daily_limit,
)

NOW = datetime(2026, 9, 7, 17, 30)


def ev(minutes: int, kind: Kind = Kind.EARN_IXL, *, day: str = "2026-09-07", status=Status.APPROVED):
    return Event(kid_id="k", kind=kind, minutes=minutes, day=day, created_at=NOW, status=status)


class TestBalance:
    def test_sums_only_approved(self):
        events = [ev(30), ev(30, status=Status.PENDING), ev(-10, Kind.CONSUME)]
        assert balance(events) == 20

    def test_rejected_never_counts(self):
        assert balance([ev(30, status=Status.REJECTED)]) == 0

    def test_empty(self):
        assert balance([]) == 0


class TestEarnedOn:
    def test_ignores_spend_and_other_days(self):
        events = [ev(30), ev(-25, Kind.CONSUME), ev(30, day="2026-09-06")]
        assert earned_on(events, "2026-09-07") == 30

    def test_manual_earnings_count_towards_the_cap(self):
        assert earned_on([ev(30, Kind.EARN_MANUAL)], "2026-09-07") == 30

    def test_adjustments_do_not(self):
        # A parent handing out time deliberately should not be throttled by the
        # cap meant for automated IXL credit.
        assert earned_on([ev(60, Kind.ADJUST)], "2026-09-07") == 0


class TestGrantable:
    rules = Rules(minutes_per_lesson=30, daily_earn_cap_minutes=90, max_balance_minutes=120)

    def test_full_grant_when_there_is_room(self):
        assert grantable_minutes([], "2026-09-07", 30, self.rules) == 30

    def test_trimmed_by_daily_cap(self):
        events = [ev(30), ev(30), ev(20)]  # 80 earned, cap 90
        assert grantable_minutes(events, "2026-09-07", 30, self.rules) == 10

    def test_zero_once_the_cap_is_spent(self):
        events = [ev(30), ev(30), ev(30)]
        assert grantable_minutes(events, "2026-09-07", 30, self.rules) == 0

    def test_trimmed_by_balance_ceiling(self):
        # Yesterday's untouched balance leaves only 20 minutes of headroom.
        events = [ev(100, day="2026-09-06")]
        assert grantable_minutes(events, "2026-09-07", 30, self.rules) == 20

    def test_negative_request_grants_nothing(self):
        assert grantable_minutes([], "2026-09-07", -5, self.rules) == 0


class TestConsumptionDelta:
    def test_first_sighting_charges_nothing(self):
        # Whatever is already on the clock predates us watching.
        assert consumption_delta(None, 45) == 0

    def test_normal_progress(self):
        assert consumption_delta(10, 25) == 15

    def test_midnight_reset_is_not_a_refund(self):
        assert consumption_delta(90, 0) == 0

    def test_no_movement(self):
        assert consumption_delta(30, 30) == 0


class TestTargetDailyLimit:
    rules = Rules(floor_minutes=0)

    def test_limit_is_played_plus_owed(self):
        assert target_daily_limit(30, 45, self.rules) == 75

    def test_zero_balance_locks_at_what_was_played(self):
        assert target_daily_limit(0, 60, self.rules) == 60

    def test_is_idempotent(self):
        first = target_daily_limit(30, 45, self.rules)
        assert target_daily_limit(30, 45, self.rules) == first

    def test_clamped_to_the_console_ceiling(self):
        assert target_daily_limit(500, 100, self.rules, ceiling=360) == 360

    def test_negative_balance_never_goes_below_played(self):
        # A balance can go negative if a sync is missed mid-session; the limit
        # must still not ask Nintendo for a negative number.
        assert target_daily_limit(-20, 40, self.rules) == 40

    def test_floor_keeps_a_minimum_allowance(self):
        assert target_daily_limit(0, 0, Rules(floor_minutes=15)) == 15


class TestExpiry:
    def test_no_event_when_rollover_is_on(self):
        assert expiry_event([ev(60)], "k", "2026-09-07", NOW, Rules(rollover=True)) is None

    def test_burns_off_the_balance_when_rollover_is_off(self):
        event = expiry_event([ev(60)], "k", "2026-09-07", NOW, Rules(rollover=False))
        assert event is not None and event.minutes == -60

    def test_nothing_to_expire(self):
        assert expiry_event([], "k", "2026-09-07", NOW, Rules(rollover=False)) is None


@pytest.mark.parametrize(
    "minutes,expected",
    [(0, "0m"), (5, "5m"), (60, "1h"), (95, "1h 35m"), (-30, "-30m"), (360, "6h")],
)
def test_humanise(minutes, expected):
    assert humanise(minutes) == expected
