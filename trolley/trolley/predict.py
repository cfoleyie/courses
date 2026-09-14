"""Working out when each item runs out, and whether that lands before the next
delivery after the one being planned.

Two ideas drive everything here.

The first is that the useful unit is not "days between orders" but "days one
unit lasts". Buying two packs of toilet roll should push the next reminder out
twice as far, so every observed gap is divided by the quantity that had to
cover it, and the estimate is multiplied back up by the size of the most recent
purchase.

The second is that a fortnightly rhythm is noisy in ways an average handles
badly. One holiday, one stock-up, one week with guests, and a mean interval is
wrong for months. A recency-weighted *median* ignores those excursions while
still moving when habits genuinely change.
"""

from __future__ import annotations

import math
from datetime import date, timedelta

from .model import Estimate, Item, Purchase, Status, Suggestion
from .slots import WEEKDAYS

#: Older gaps still count, but a habit from four months ago counts half as much
#: as last week's. Long enough to survive a holiday, short enough to follow a
#: change in household size.
HALF_LIFE_DAYS = 120.0

#: Gaps beyond this are treated as "stopped buying it, then started again"
#: rather than as one very slow cycle, and are left out of the estimate.
MAX_SENSIBLE_GAP_DAYS = 240.0

#: Floor on confidence from scatter alone, so an erratic item still ranks.
MIN_SCATTER_CONFIDENCE = 0.15

#: An item seen once, with no catalogue prior, cannot be predicted at all.
CONFIDENCE_FROM_PRIOR = 0.3

#: A slot preference needs this many purchases behind it before it is believed.
#: With two deliveries a week, four in a row on the same day is already an
#: unlikely coincidence; fewer than that is just a short run.
SLOT_MIN_PURCHASES = 4

#: And this share of them, by recency weight, must fall in that one slot. Half
#: is what pure chance gives with two deliveries, so this is a real lean.
SLOT_THRESHOLD = 0.75

#: How a score is split between "it is in the window at all" (BASE), "how long
#: it would be out of stock" (URGENCY) and "how far past due it already is"
#: (OVERDUE). They sum to 1, so a score is always a fraction of confidence.
BASE_WEIGHT = 0.15
URGENCY_WEIGHT = 0.55
OVERDUE_WEIGHT = 0.30


def weighted_median(pairs: list[tuple[float, float]]) -> float:
    """Median of (value, weight) pairs, interpolating at the halfway mass."""
    if not pairs:
        raise ValueError("weighted_median of an empty sequence")
    ordered = sorted(pairs)
    total = sum(weight for _, weight in ordered)
    if total <= 0:
        return ordered[len(ordered) // 2][0]
    half, running = total / 2, 0.0
    for value, weight in ordered:
        running += weight
        if running >= half:
            return value
    return ordered[-1][0]


def _gaps(purchases: list[Purchase], today: date) -> list[tuple[float, float]]:
    """Per-unit gaps paired with a recency weight, newest counting most."""
    out: list[tuple[float, float]] = []
    for earlier, later in zip(purchases, purchases[1:]):
        days = (later.bought_on - earlier.bought_on).days
        if days <= 0 or days > MAX_SENSIBLE_GAP_DAYS:
            continue
        quantity = max(earlier.quantity, 0.1)
        age = max((today - later.bought_on).days, 0)
        out.append((days / quantity, 0.5 ** (age / HALF_LIFE_DAYS)))
    return out


def _scatter_confidence(gaps: list[tuple[float, float]], centre: float) -> float:
    """How tightly the gaps cluster, as a 0..1 multiplier."""
    if len(gaps) < 2 or centre <= 0:
        return MIN_SCATTER_CONFIDENCE
    deviation = weighted_median([(abs(value - centre), weight) for value, weight in gaps])
    return max(MIN_SCATTER_CONFIDENCE, min(1.0, 1.0 - deviation / centre))


def merge_same_day(purchases: list[Purchase]) -> list[Purchase]:
    """Two lines of the same item in one order are one purchase, not two.

    Left unmerged they would produce a zero-day gap and make the item look far
    more frequent than it is.
    """
    by_day: dict[date, Purchase] = {}
    for purchase in sorted(purchases, key=lambda p: p.bought_on):
        existing = by_day.get(purchase.bought_on)
        if existing is None:
            by_day[purchase.bought_on] = purchase
        else:
            from dataclasses import replace

            by_day[purchase.bought_on] = replace(
                existing, quantity=existing.quantity + purchase.quantity
            )
    return [by_day[day] for day in sorted(by_day)]


def slot_affinity(
    purchases: list[Purchase],
    today: date,
    *,
    min_purchases: int = SLOT_MIN_PURCHASES,
    threshold: float = SLOT_THRESHOLD,
) -> tuple[str | None, float]:
    """Which weekday an item is usually bought on, if it clearly is one.

    Steak and beer go in the Friday order for the weekend; chicken goes in the
    Monday one. Nothing in the interval arithmetic can see that, because both
    are just purchases a week apart. This looks at the day of the week instead.

    Recent purchases count for more, as everywhere else, so a habit that has
    moved is followed rather than averaged with the one it replaced.
    """
    history = merge_same_day(purchases)
    if len(history) < min_purchases:
        return None, 0.0

    weights: dict[str, float] = {}
    total = 0.0
    for purchase in history:
        age = max((today - purchase.bought_on).days, 0)
        weight = 0.5 ** (age / HALF_LIFE_DAYS)
        day = WEEKDAYS[purchase.bought_on.weekday()]
        weights[day] = weights.get(day, 0.0) + weight
        total += weight

    if total <= 0:
        return None, 0.0
    day, weight = max(weights.items(), key=lambda pair: pair[1])
    share = weight / total
    return (day, share) if share >= threshold else (None, share)


def estimate(
    item: Item,
    purchases: list[Purchase],
    today: date,
    prior: float | None = None,
    *,
    slot_min_purchases: int = SLOT_MIN_PURCHASES,
    slot_threshold: float = SLOT_THRESHOLD,
) -> Estimate:
    """Build the engine's view of one item from its purchase history."""
    history = merge_same_day(purchases)
    last = history[-1] if history else None
    last_quantity = max(last.quantity, 0.1) if last else 1.0

    gaps = _gaps(history, today)
    unit_interval: float | None = None
    confidence = 0.0
    basis = "none"

    if gaps:
        observed = weighted_median(gaps)
        # Few gaps means a shaky estimate, so pull it towards the catalogue's
        # idea of this staple until enough evidence accumulates to stand alone.
        sample_weight = len(gaps) / (len(gaps) + 2)
        if prior:
            unit_interval = sample_weight * observed + (1 - sample_weight) * prior
        else:
            unit_interval = observed
        confidence = sample_weight * _scatter_confidence(gaps, observed)
        basis = "history"
    elif prior:
        unit_interval = prior
        confidence = CONFIDENCE_FROM_PRIOR
        basis = "prior"

    if item.interval_override:
        unit_interval = item.interval_override
        confidence = max(confidence, 0.9)
        basis = "override"

    interval = due_on = None
    if unit_interval and last:
        # `nudge` records that suggestions keep getting turned down: the item
        # evidently lasts longer than the receipts imply.
        interval = unit_interval * last_quantity * max(item.nudge, 0.1)
        due_on = last.bought_on + timedelta(days=round(interval))

    # A pinned preference wins outright; otherwise the history is asked.
    pinned = (item.slot_preference or "").strip().casefold()
    if pinned and pinned != "any":
        preferred, share, slot_pinned = pinned, 1.0, True
    elif pinned == "any":
        preferred, share, slot_pinned = None, 0.0, False
    else:
        preferred, share = slot_affinity(
            history, today, min_purchases=slot_min_purchases, threshold=slot_threshold
        )
        slot_pinned = False

    return Estimate(
        item=item,
        unit_interval=unit_interval,
        interval=interval,
        last_bought=last.bought_on if last else None,
        last_quantity=last_quantity,
        due_on=due_on,
        confidence=round(confidence, 4),
        basis=basis,
        purchases=len(history),
        preferred_slot=preferred,
        slot_share=round(share, 3),
        slot_pinned=slot_pinned,
    )


def _span(days: int) -> str:
    """A length of time in the words a person would use for it."""
    if days <= 0:
        return "today"
    if days == 1:
        return "1 day"
    if days < 14:
        return f"{days} days"
    weeks = round(days / 7)
    return "1 week" if weeks == 1 else f"{weeks} weeks"


def _ago(days: int) -> str:
    """How long ago something happened, without the "today ago" awkwardness."""
    return "today" if days <= 0 else f"{_span(days)} ago"


def explain(est: Estimate, today: date, status: Status) -> str:
    """One line saying why this is on the list, in the user's own terms."""
    if est.interval is None or est.due_on is None or est.last_bought is None:
        return "No pattern yet."

    every = _span(round(est.interval))
    bought = _ago((today - est.last_bought).days)
    lead = {
        Status.OVERDUE: f"Due {_ago((today - est.due_on).days)}.",
        Status.DUE: "Due by this delivery.",
        Status.SOON: "Runs out before the delivery after this one.",
    }[status]

    if est.basis == "prior":
        return f"{lead} Bought once, {bought}; a typical restock is every {every}."
    if est.basis == "override":
        return f"{lead} Set to every {every}; last bought {bought}."
    return f"{lead} Usually every {every}; last bought {bought}."


def _defer_to(
    est: Estimate,
    slot_weekday: str | None,
    own_slot_date: date | None,
) -> str | None:
    """Whether this item should wait for the delivery it is usually bought in.

    Steak bought every Friday comes due on a Friday, and the "will it last
    until the next delivery" rule would put it on Monday's list every week,
    because Friday is exactly when it runs out. It is not needed on Monday: it
    is needed on Friday, and Friday's van arrives in time.

    A pinned slot waits unconditionally, because the user has said this is a
    weekend thing. A slot merely learned from the history gives way when the
    item would actually run dry before its own delivery came round.
    """
    preferred = est.preferred_slot
    if not preferred or not slot_weekday or preferred == slot_weekday:
        return None
    if own_slot_date is None:
        return None  # That delivery is no longer in the schedule.
    if est.slot_pinned or (est.due_on is not None and est.due_on >= own_slot_date):
        return preferred
    return None


def assess(
    est: Estimate,
    *,
    today: date,
    slot_date: date,
    horizon_date: date,
    slot_weekday: str | None = None,
    own_slot_date: date | None = None,
) -> Suggestion | None:
    """Decide whether an item belongs on the list for the slot being planned.

    The test is not "is it due today" but "will it run out before the delivery
    *after* this one". Missing this order means waiting the rest of the week,
    so anything that would not survive that long has to go on now.

    An item with a delivery of its own is the exception: see `_defer_to`. It
    still comes back as a suggestion, marked with the delivery it is waiting
    for, so the caller can show it as held rather than losing it silently.
    """
    item = est.item
    if item.paused or est.due_on is None or est.interval is None:
        return None
    if item.snoozed_until and item.snoozed_until >= slot_date:
        return None
    if est.due_on > horizon_date:
        return None

    if est.due_on < today:
        status = Status.OVERDUE
    elif est.due_on <= slot_date:
        status = Status.DUE
    else:
        status = Status.SOON

    interval = max(est.interval, 1.0)
    # Days the cupboard would be empty if this order is skipped, as a fraction
    # of the item's own cycle: one week dry matters more for milk than for bleach.
    shortfall = (horizon_date - est.due_on).days / interval
    urgency = 1.0 - math.exp(-max(shortfall, 0.0))
    # A separate term for plainly forgotten things, so a fortnight-overdue item
    # outranks a staple that is merely due again on schedule.
    overdue = min(max((today - est.due_on).days / interval, 0.0), 1.0)
    # The floor matters: an item due exactly on the horizon has no shortfall and
    # is not overdue, but it still belongs on the list, just at the bottom.
    score = est.confidence * (BASE_WEIGHT + URGENCY_WEIGHT * urgency + OVERDUE_WEIGHT * overdue)

    deferred_to = _defer_to(est, slot_weekday, own_slot_date)
    reason = explain(est, today, status)
    if deferred_to:
        reason = f"Usually a {deferred_to.capitalize()} item. {reason}"

    return Suggestion(
        estimate=est,
        status=status,
        score=round(score, 4),
        reason=reason,
        quantity=max(1.0, round(est.last_quantity)),
        deferred_to=deferred_to,
    )
