"""Building the list for the next delivery, and learning from the answer."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from . import predict
from .catalogue import prior_interval
from .config import Config
from .db import Database
from .model import Estimate, Status, Suggestion
from .slots import Slot, planning_window


@dataclass(frozen=True, slots=True)
class Report:
    """Everything the UI needs for one upcoming delivery."""

    slot: Slot
    horizon: Slot
    suggestions: tuple[Suggestion, ...]
    #: Items whose history is too thin to suggest, kept for the "not sure" list.
    unsure: tuple[Estimate, ...]
    already_listed: tuple[int, ...]
    generated_at: datetime

    @property
    def urgent(self) -> tuple[Suggestion, ...]:
        return tuple(s for s in self.suggestions if s.status is Status.OVERDUE)


def _now(config: Config, now: datetime | None = None) -> datetime:
    zone = ZoneInfo(config.server.timezone)
    return (now.astimezone(zone) if now and now.tzinfo else (now or datetime.now(zone)).replace(tzinfo=zone))


def estimates(db: Database, config: Config, today: date) -> list[Estimate]:
    """The engine's view of every item currently known."""
    grouped = db.purchases_by_item()
    out = []
    for item in db.items():
        prior = config.intervals.get(item.key, prior_interval(item.key))
        out.append(predict.estimate(item, grouped.get(item.id, []), today, prior))
    return out


def build(db: Database, config: Config, now: datetime | None = None) -> Report | None:
    """Work out what should go on the order that is being planned next.

    Returns None only when no delivery slots are configured at all.
    """
    moment = _now(config, now)
    window = planning_window(config.slot_specs, moment, tz=config.server.timezone)
    if window is None:
        return None
    slot, horizon = window
    today = moment.date()

    listed = {entry["item_id"] for entry in db.list_for(slot.day)}
    rules = config.suggest

    suggestions: list[Suggestion] = []
    unsure: list[Estimate] = []
    for est in estimates(db, config, today):
        if est.item.id in listed:
            continue
        suggestion = predict.assess(
            est, today=today, slot_date=slot.day, horizon_date=horizon.day
        )
        if suggestion is None:
            # Worth showing separately: bought before, but not predictable yet.
            if not est.item.paused and est.purchases and est.due_on is None:
                unsure.append(est)
            continue
        if not rules.include_soon and suggestion.status is Status.SOON:
            continue
        if est.confidence < rules.min_confidence or suggestion.score < rules.min_score:
            unsure.append(est)
            continue
        suggestions.append(suggestion)

    suggestions.sort(key=lambda s: (-s.score, s.item.name))
    unsure.sort(key=lambda e: e.item.name)

    return Report(
        slot=slot,
        horizon=horizon,
        suggestions=tuple(suggestions[: rules.max_suggestions]),
        unsure=tuple(unsure),
        already_listed=tuple(sorted(listed)),
        generated_at=moment,
    )


def decide(
    db: Database,
    config: Config,
    item_id: int,
    slot_day: date,
    action: str,
    quantity: float = 1.0,
) -> str:
    """Apply a yes/no on a suggestion, and let the engine learn from it.

    A dismissal is evidence the item lasts longer than the receipts suggest, so
    it stretches the estimate a little. Accepting one is evidence the estimate
    was right, so it clears any stretch that had built up.
    """
    item = db.item(item_id)
    if item is None:
        raise KeyError(f"no item with id {item_id}")
    rules = config.suggest
    db.record_decision(item_id, slot_day, action)

    if action == "add":
        db.add_to_list(slot_day, item_id, quantity)
        db.update_item(item_id, nudge=1.0)
        return f"{item.name} added to the {slot_day:%A} list"
    if action == "remove":
        db.remove_from_list(slot_day, item_id)
        return f"{item.name} taken off the list"
    if action == "dismiss":
        db.update_item(item_id, nudge=min(item.nudge * rules.nudge_step, rules.nudge_max))
        return f"{item.name} dismissed; it will be suggested less often"
    if action == "snooze":
        db.update_item(item_id, snoozed_until=slot_day)
        return f"{item.name} skipped for this delivery"
    if action == "pause":
        db.update_item(item_id, paused=True)
        return f"{item.name} will not be suggested again"
    if action == "resume":
        db.update_item(item_id, paused=False, snoozed_until=None, nudge=1.0)
        return f"{item.name} is back in the rotation"
    raise ValueError(f"unknown action {action!r}")


def render_text(report: Report) -> str:
    """The list as plain text, for a notification or the clipboard."""
    when = report.slot.at.strftime("%A %-d %B")
    if not report.suggestions:
        return f"{report.slot.label} ({when}): nothing looks due."

    lines = [f"{report.slot.label} ({when}) — {len(report.suggestions)} to consider:"]
    for suggestion in report.suggestions:
        mark = {"overdue": "!", "due": "*", "soon": "-"}[suggestion.status.value]
        quantity = f" x{suggestion.quantity:g}" if suggestion.quantity > 1 else ""
        lines.append(f" {mark} {suggestion.item.name}{quantity} — {suggestion.reason}")
    return "\n".join(lines)
