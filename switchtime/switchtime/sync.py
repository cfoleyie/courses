"""The sync engine: IXL in, console limit out.

One pass per kid, in a deliberate order:

1. credit any newly finished IXL skills,
2. charge for whatever the console says was played since we last looked,
3. write the resulting balance back as an absolute daily limit.

Steps 1 and 2 are independent, so a failure in either still leaves the ledger
consistent — the run is reported as degraded and the next pass picks it up.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from .config import Config, KidConfig
from .db import Database
from .ledger import (
    Event,
    Kind,
    Status,
    balance,
    consumption_delta,
    earned_on,
    expiry_event,
    grantable_minutes,
    target_daily_limit,
)
from .providers.base import ProviderError
from .switch import MAX_LIMIT, SwitchError

_LOG = logging.getLogger(__name__)


@dataclass
class SyncReport:
    kid_id: str
    at: str
    ok: bool = True
    reason: str = "scheduled"
    new_lessons: int = 0
    minutes_earned: int = 0
    minutes_consumed: int = 0
    balance: int = 0
    played_today: int = 0
    target_limit: int | None = None
    applied_limit: int | None = None
    provider_ok: bool = True
    switch_ok: bool = True
    messages: list[str] = field(default_factory=list)
    lesson_titles: list[str] = field(default_factory=list)

    def note(self, message: str) -> None:
        self.messages.append(message)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class SyncEngine:
    def __init__(
        self,
        config: Config,
        db: Database,
        provider: Any,
        switch: Any,
    ) -> None:
        self.config = config
        self.db = db
        self.provider = provider
        self.switch = switch
        self._tz = ZoneInfo(config.server.timezone)
        self._locks: dict[str, asyncio.Lock] = {k.id: asyncio.Lock() for k in config.kids}
        self._last_forced: dict[str, float] = {}
        self._task: asyncio.Task | None = None
        self._stopping = asyncio.Event()

    # ----- clock ---------------------------------------------------------

    def now(self) -> datetime:
        return datetime.now(self._tz)

    def today(self) -> str:
        return self.now().date().isoformat()

    # ----- public API ----------------------------------------------------

    def cooldown_remaining(self, kid_id: str) -> int:
        """Seconds until a kid may force another sync. Stops button-mashing."""
        last = self._last_forced.get(kid_id)
        if last is None:
            return 0
        elapsed = time.monotonic() - last
        remaining = self.config.ixl.force_poll_cooldown_seconds - elapsed
        return max(0, int(remaining + 0.999))

    async def sync_kid(self, kid_id: str, *, reason: str = "scheduled") -> SyncReport:
        kid = self.config.kid(kid_id)
        lock = self._locks.setdefault(kid_id, asyncio.Lock())
        async with lock:
            if reason == "forced":
                self._last_forced[kid_id] = time.monotonic()
            report = await self._sync_locked(kid, reason=reason)
        self.db.set_state(f"report:{kid_id}", report.as_dict())
        return report

    async def sync_all(self, *, reason: str = "scheduled") -> list[SyncReport]:
        return [await self.sync_kid(kid.id, reason=reason) for kid in self.config.kids]

    def last_report(self, kid_id: str) -> dict[str, Any] | None:
        return self.db.get_state(f"report:{kid_id}")

    # ----- one pass ------------------------------------------------------

    async def _sync_locked(self, kid: KidConfig, *, reason: str) -> SyncReport:
        now = self.now()
        today = now.date().isoformat()
        report = SyncReport(kid_id=kid.id, at=now.isoformat(), reason=reason)

        self._roll_day(kid, today, now, report)
        await self._credit_lessons(kid, today, now, report)
        await self._settle_console(kid, today, now, report)

        report.balance = balance(self.db.events_for(kid.id))
        report.ok = report.provider_ok and report.switch_ok
        return report

    def _roll_day(self, kid: KidConfig, today: str, now: datetime, report: SyncReport) -> None:
        """Handle the first sync of a new day."""
        key = f"day:{kid.id}"
        stored = self.db.get_state(key)
        if stored == today:
            return
        if stored is not None:
            # The console's counter resets to zero at midnight, so zero — not
            # "unknown" — is the new day's true baseline. Storing None here
            # instead would make the first sync of every day charge nothing,
            # handing over any play that happened before it (a whole morning,
            # if the machine running this was asleep overnight).
            self.db.set_state(f"played:{kid.id}", 0)
            expiry = expiry_event(
                self.db.events_for(kid.id), kid.id, stored, now, self.config.rules
            )
            if expiry is not None and self.db.add_event(expiry):
                report.note(f"{-expiry.minutes} min expired from {stored}")
        self.db.set_state(key, today)

    async def _credit_lessons(
        self, kid: KidConfig, today: str, now: datetime, report: SyncReport
    ) -> None:
        if not self.config.ixl.enabled or not kid.ixl_ready:
            report.note("IXL sync is off for this kid — claims must be approved by hand.")
            return
        try:
            result = await self.provider.fetch(kid.id)
        except ProviderError as exc:
            report.provider_ok = False
            report.note(f"IXL check failed: {exc}")
            return

        report.messages.extend(result.diagnostics)
        if not result.ok:
            report.provider_ok = False
            return

        known = self.db.known_refs(kid.id)
        per_lesson = self.config.minutes_for(kid.id)
        for lesson in result.lessons:
            if lesson.ref in known:
                continue
            events = self.db.events_for(kid.id)
            granted = grantable_minutes(events, today, per_lesson, self.config.rules)
            if granted <= 0:
                report.note(
                    f"Daily cap reached — {lesson.title} recorded but earned nothing."
                )
            event = Event(
                kid_id=kid.id,
                kind=Kind.EARN_IXL,
                minutes=granted,
                day=today,
                created_at=now,
                status=Status.APPROVED,
                ref=lesson.ref,
                note=lesson.describe(),
            )
            if self.db.add_event(event) is None:
                continue  # raced with another pass; the ref is already banked
            known.add(lesson.ref)
            report.new_lessons += 1
            report.minutes_earned += granted
            report.lesson_titles.append(lesson.title)

    async def _settle_console(
        self, kid: KidConfig, today: str, now: datetime, report: SyncReport
    ) -> None:
        if not kid.switch_ready:
            report.note(f"No Switch device configured for {kid.name}.")
            return
        try:
            state = await self.switch.snapshot(kid)
        except SwitchError as exc:
            report.switch_ok = False
            report.note(f"Could not read the Switch: {exc}")
            return

        report.played_today = state.played_today

        previous = self.db.get_state(f"played:{kid.id}")
        used = consumption_delta(previous, state.played_today)
        if used > 0:
            charged = self.db.add_event(
                Event(
                    kid_id=kid.id,
                    kind=Kind.CONSUME,
                    minutes=-used,
                    day=today,
                    created_at=now,
                    ref=f"play:{today}:{state.played_today}",
                    note=f"{used} min played on the Switch",
                )
            )
            if charged is not None:
                report.minutes_consumed = used
        self.db.set_state(f"played:{kid.id}", state.played_today)

        current_balance = balance(self.db.events_for(kid.id))
        # Nintendo will not accept more than MAX_LIMIT; a parent may cap it lower.
        ceiling = min(MAX_LIMIT, max(0, self.config.nintendo.max_daily_minutes))
        target = target_daily_limit(
            current_balance, state.played_today, self.config.rules, ceiling=ceiling
        )
        report.target_limit = target

        if state.limit_minutes == target and not state.extra_time_active:
            report.applied_limit = target
            return  # already correct; skip the write entirely

        try:
            report.applied_limit = await self.switch.set_daily_limit(kid, target)
        except SwitchError as exc:
            report.switch_ok = False
            report.note(f"Could not set the limit: {exc}")

    # ----- background loop -----------------------------------------------

    async def start(self) -> None:
        if self._task is None or self._task.done():
            self._stopping.clear()
            self._task = asyncio.create_task(self._run(), name="switchtime-poller")

    async def stop(self) -> None:
        self._stopping.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None

    async def _run(self) -> None:
        interval = self.config.ixl.poll_seconds
        _LOG.info("poller started, every %ss", interval)
        while not self._stopping.is_set():
            for kid in self.config.kids:
                if self._stopping.is_set():
                    break
                try:
                    report = await self.sync_kid(kid.id)
                    if not report.ok:
                        _LOG.warning("sync degraded for %s: %s", kid.id, report.messages)
                except Exception:  # noqa: BLE001 - the loop must outlive any one failure
                    _LOG.exception("sync crashed for %s", kid.id)
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=interval)
            except asyncio.TimeoutError:
                continue

    # ----- parent actions -------------------------------------------------

    def add_manual_claim(self, kid_id: str, note: str, minutes: int | None = None) -> Event:
        """A kid asks for credit. Parked as pending until a parent approves."""
        now = self.now()
        event = Event(
            kid_id=kid_id,
            kind=Kind.EARN_MANUAL,
            minutes=minutes if minutes is not None else self.config.minutes_for(kid_id),
            day=now.date().isoformat(),
            created_at=now,
            status=Status.PENDING,
            ref=None,
            note=note.strip()[:200] or "Manual claim",
        )
        stored = self.db.add_event(event)
        return stored or event

    def adjust(self, kid_id: str, minutes: int, note: str) -> Event:
        now = self.now()
        event = Event(
            kid_id=kid_id,
            kind=Kind.ADJUST,
            minutes=int(minutes),
            day=now.date().isoformat(),
            created_at=now,
            status=Status.APPROVED,
            ref=None,
            note=note.strip()[:200] or "Parent adjustment",
        )
        return self.db.add_event(event) or event

    def decide(self, event_id: int, *, approve: bool) -> bool:
        return self.db.set_status(event_id, Status.APPROVED if approve else Status.REJECTED)

    def earned_today(self, kid_id: str) -> int:
        return earned_on(self.db.events_for(kid_id), self.today())
