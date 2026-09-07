from __future__ import annotations

import pytest

from switchtime.config import Rules
from switchtime.ledger import Kind, Status, balance
from switchtime.providers.base import ProviderError
from switchtime.switch import SwitchState

pytestmark = pytest.mark.asyncio


def today(engine):
    return engine.today()


class TestEarning:
    async def test_a_finished_lesson_becomes_minutes(self, engine, provider, db):
        provider.queue_lesson("oliver", "ixl:add-fractions:x", day=today(engine))
        report = await engine.sync_kid("oliver")
        assert report.new_lessons == 1
        assert report.minutes_earned == 30
        assert balance(db.events_for("oliver")) == 30

    async def test_the_same_lesson_is_never_paid_twice(self, engine, provider, db):
        provider.queue_lesson("oliver", "ixl:add-fractions:x", day=today(engine))
        await engine.sync_kid("oliver")
        second = await engine.sync_kid("oliver")
        assert second.new_lessons == 0
        assert balance(db.events_for("oliver")) == 30

    async def test_two_different_lessons_both_pay(self, engine, provider, db):
        provider.queue_lesson("oliver", "ixl:a:x", day=today(engine))
        provider.queue_lesson("oliver", "ixl:b:x", day=today(engine))
        report = await engine.sync_kid("oliver")
        assert report.new_lessons == 2
        assert balance(db.events_for("oliver")) == 60

    async def test_the_daily_cap_is_enforced(self, engine, provider, db):
        for i in range(5):  # 5 x 30 = 150, cap is 90
            provider.queue_lesson("oliver", f"ixl:s{i}:x", day=today(engine))
        await engine.sync_kid("oliver")
        assert balance(db.events_for("oliver")) == 90

    async def test_kids_do_not_share_a_ledger(self, engine, provider, db):
        provider.queue_lesson("oliver", "ixl:a:x", day=today(engine))
        await engine.sync_kid("oliver")
        await engine.sync_kid("alice")
        assert balance(db.events_for("oliver")) == 30
        assert balance(db.events_for("alice")) == 0


class TestConsole:
    async def test_limit_is_played_plus_balance(self, engine, provider, switch):
        provider.queue_lesson("oliver", "ixl:a:x", day=today(engine))
        switch.state["oliver"] = SwitchState("d", played_today=20, limit_minutes=0,
                                             remaining=0, extra_time_active=False)
        report = await engine.sync_kid("oliver")
        # First sighting charges nothing, so 30 earned stays whole: 20 + 30.
        assert report.target_limit == 50
        assert switch.writes[-1] == ("oliver", 50)

    async def test_play_time_is_charged_against_the_balance(self, engine, provider, switch, db):
        provider.queue_lesson("oliver", "ixl:a:x", day=today(engine))
        switch.state["oliver"] = SwitchState("d", 0, 0, 0, False)
        await engine.sync_kid("oliver")
        switch.state["oliver"] = SwitchState("d", 18, 30, 12, False)
        report = await engine.sync_kid("oliver")
        assert report.minutes_consumed == 18
        assert balance(db.events_for("oliver")) == 12
        assert report.target_limit == 30  # 18 played + 12 left

    async def test_first_sighting_does_not_bill_earlier_play(self, engine, switch, db):
        switch.state["oliver"] = SwitchState("d", played_today=200, limit_minutes=None,
                                             remaining=None, extra_time_active=False)
        report = await engine.sync_kid("oliver")
        assert report.minutes_consumed == 0
        assert balance(db.events_for("oliver")) == 0

    async def test_no_write_when_the_limit_is_already_right(self, engine, switch):
        switch.state["oliver"] = SwitchState("d", played_today=0, limit_minutes=0,
                                             remaining=0, extra_time_active=False)
        await engine.sync_kid("oliver")
        before = len(switch.writes)
        await engine.sync_kid("oliver")
        assert len(switch.writes) == before

    async def test_active_bonus_time_forces_a_rewrite(self, engine, switch):
        switch.state["oliver"] = SwitchState("d", 0, 0, 0, extra_time_active=True)
        await engine.sync_kid("oliver")
        assert switch.writes, "bonus time must be cleared back to our own number"

    async def test_zero_balance_locks_the_console_at_what_was_played(self, engine, switch):
        switch.state["oliver"] = SwitchState("d", 0, None, None, False)
        await engine.sync_kid("oliver")
        switch.state["oliver"] = SwitchState("d", 45, 0, 0, False)
        report = await engine.sync_kid("oliver")
        assert report.target_limit == 45


    async def test_the_console_ceiling_can_be_lowered(self, engine, config, switch):
        import dataclasses

        from switchtime.config import NintendoConfig

        engine.config = dataclasses.replace(
            config, nintendo=NintendoConfig(enabled=False, dry_run=True, max_daily_minutes=90)
        )
        engine.adjust("oliver", 300, "banked a lot")
        switch.state["oliver"] = SwitchState("d", 0, 0, 0, False)
        report = await engine.sync_kid("oliver")
        assert report.target_limit == 90, "max_daily_minutes must cap the console"


class TestFailureIsolation:
    async def test_ixl_outage_still_settles_the_console(self, engine, provider, switch):
        provider.fail_with = "IXL timed out"
        report = await engine.sync_kid("oliver")
        assert report.ok is False
        assert report.provider_ok is False
        assert report.switch_ok is True
        assert switch.writes, "the console should still have been reconciled"

    async def test_console_outage_still_credits_lessons(self, engine, provider, switch, db):
        provider.queue_lesson("oliver", "ixl:a:x", day=today(engine))
        switch.fail_with = "Nintendo returned 400"
        report = await engine.sync_kid("oliver")
        assert report.ok is False
        assert report.switch_ok is False
        assert balance(db.events_for("oliver")) == 30, "minutes are owed even if unspendable"

    async def test_a_failed_sync_is_reported_not_raised(self, engine, provider):
        provider.fail_with = "boom"
        report = await engine.sync_kid("oliver")
        assert any("boom" in m for m in report.messages)


class TestDayRollover:
    async def test_yesterdays_total_is_never_differenced_against_today(self, engine, switch, db):
        switch.state["oliver"] = SwitchState("d", 100, 100, 0, False)
        await engine.sync_kid("oliver")
        db.set_state("day:oliver", "2026-01-01")  # pretend the last run was long ago
        switch.state["oliver"] = SwitchState("d", 5, 100, 95, False)
        report = await engine.sync_kid("oliver")
        # 5, not 95: the counter restarted, so the baseline restarts at zero too.
        assert report.minutes_consumed == 5

    async def test_play_before_the_first_sync_of_a_day_is_still_charged(self, engine, switch, db):
        # The machine running this can be asleep overnight. Whatever the console
        # logged since midnight is real play and must not be given away.
        switch.state["oliver"] = SwitchState("d", 0, 0, 0, False)
        await engine.sync_kid("oliver")
        db.set_state("day:oliver", "2026-01-01")
        switch.state["oliver"] = SwitchState("d", 45, 0, 0, False)
        report = await engine.sync_kid("oliver")
        assert report.minutes_consumed == 45

    async def test_a_kid_never_seen_before_is_not_billed_for_the_backlog(self, engine, switch, db):
        # Day one of the install: the console may already show hours played.
        # Charging those would put a kid deeply negative before they started.
        switch.state["oliver"] = SwitchState("d", 200, None, None, False)
        report = await engine.sync_kid("oliver")
        assert report.minutes_consumed == 0
        assert balance(db.events_for("oliver")) == 0

    async def test_balance_expires_overnight_when_rollover_is_off(self, engine, provider, db, config):
        import dataclasses

        engine.config = dataclasses.replace(config, rules=Rules(rollover=False, daily_earn_cap_minutes=90))
        provider.queue_lesson("oliver", "ixl:a:x", day=today(engine))
        await engine.sync_kid("oliver")
        assert balance(db.events_for("oliver")) == 30
        db.set_state("day:oliver", "2026-01-01")
        await engine.sync_kid("oliver")
        assert balance(db.events_for("oliver")) == 0


class TestManualClaims:
    async def test_a_claim_starts_pending_and_is_worth_nothing_yet(self, engine, db):
        event = engine.add_manual_claim("oliver", "Did two pages")
        assert event.status is Status.PENDING
        assert balance(db.events_for("oliver")) == 0

    async def test_approval_pays_out(self, engine, db):
        event = engine.add_manual_claim("oliver", "Did two pages")
        assert engine.decide(event.id, approve=True)
        assert balance(db.events_for("oliver")) == 30

    async def test_rejection_pays_nothing(self, engine, db):
        event = engine.add_manual_claim("oliver", "Nope")
        assert engine.decide(event.id, approve=False)
        assert balance(db.events_for("oliver")) == 0

    async def test_a_decision_cannot_be_made_twice(self, engine):
        event = engine.add_manual_claim("oliver", "Once")
        assert engine.decide(event.id, approve=True)
        assert not engine.decide(event.id, approve=False)

    async def test_parent_adjustment_applies_immediately(self, engine, db):
        engine.adjust("oliver", -15, "Was cheeky")
        assert balance(db.events_for("oliver")) == -15


class TestCooldown:
    async def test_forced_sync_starts_a_cooldown(self, engine):
        assert engine.cooldown_remaining("oliver") == 0
        await engine.sync_kid("oliver", reason="forced")
        assert engine.cooldown_remaining("oliver") > 0

    async def test_scheduled_syncs_do_not(self, engine):
        await engine.sync_kid("oliver", reason="scheduled")
        assert engine.cooldown_remaining("oliver") == 0
