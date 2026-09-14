"""The engine's arithmetic: what it learns from gaps, and when it speaks up."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta

import pytest

from trolley.model import Item, Purchase, Status
from trolley.predict import assess, estimate, merge_same_day, weighted_median

from conftest import TODAY, purchases_every


def test_weighted_median_follows_the_weight_not_the_count() -> None:
    # Three cheap votes for 10 cannot outweigh one heavy vote for 30.
    assert weighted_median([(10, 1), (10, 1), (10, 1), (30, 20)]) == 30


def test_weighted_median_rejects_empty_input() -> None:
    with pytest.raises(ValueError):
        weighted_median([])


def test_regular_history_gives_back_its_own_interval(item: Item) -> None:
    est = estimate(item, purchases_every(14, 8), TODAY)
    assert est.basis == "history"
    assert est.unit_interval == pytest.approx(14, abs=0.6)
    assert est.due_on == TODAY + timedelta(days=14)
    assert est.confidence > 0.6


def test_buying_two_packs_pushes_the_next_reminder_out(item: Item) -> None:
    """One pack every 14 days and two packs every 28 days are the same habit."""
    singles = estimate(item, purchases_every(14, 8, quantity=1), TODAY)
    doubles = estimate(item, purchases_every(28, 8, quantity=2), TODAY)
    assert doubles.unit_interval == pytest.approx(singles.unit_interval, abs=0.6)
    # ...but the double purchase is expected to last twice as long.
    assert doubles.interval == pytest.approx(2 * singles.interval, abs=1.2)


def test_one_stock_up_does_not_move_the_estimate(item: Item) -> None:
    """A median ignores the holiday; a mean would be dragged for months."""
    history = purchases_every(14, 8)
    steady = estimate(item, history, TODAY)

    disrupted = list(history)
    disrupted[3] = replace(disrupted[3], bought_on=disrupted[3].bought_on - timedelta(days=40))
    shaken = estimate(item, disrupted, TODAY)

    assert shaken.unit_interval == pytest.approx(steady.unit_interval, abs=2.0)


def test_recent_gaps_count_for_more_than_old_ones(item: Item) -> None:
    """A household that has started getting through it faster is believed."""
    old = [TODAY - timedelta(days=d) for d in (400, 380, 360, 340, 320)]
    recent = [TODAY - timedelta(days=d) for d in (28, 21, 14, 7, 0)]
    history = [
        Purchase(id=None, item_id=1, bought_on=day) for day in sorted(old + recent)
    ]
    est = estimate(item, history, TODAY)
    assert est.unit_interval < 14  # Pulled towards the recent weekly rhythm.


def test_a_very_long_absence_is_not_treated_as_one_slow_cycle(item: Item) -> None:
    history = [
        Purchase(id=None, item_id=1, bought_on=TODAY - timedelta(days=d))
        for d in (900, 28, 14, 0)
    ]
    est = estimate(item, history, TODAY)
    assert est.unit_interval == pytest.approx(14, abs=2)


def test_a_single_purchase_leans_on_the_catalogue(item: Item) -> None:
    history = [Purchase(id=None, item_id=1, bought_on=TODAY - timedelta(days=20))]
    est = estimate(item, history, TODAY, prior=17)
    assert est.basis == "prior"
    assert est.unit_interval == 17
    assert 0 < est.confidence < 0.5  # Worth mentioning, not worth insisting on.


def test_a_single_purchase_with_no_prior_predicts_nothing(item: Item) -> None:
    history = [Purchase(id=None, item_id=1, bought_on=TODAY - timedelta(days=20))]
    est = estimate(item, history, TODAY, prior=None)
    assert est.due_on is None and est.basis == "none"


def test_thin_history_is_pulled_towards_the_prior(item: Item) -> None:
    est = estimate(item, purchases_every(30, 2), TODAY, prior=10)
    assert 10 < est.unit_interval < 30


def test_an_override_beats_both_history_and_prior(item: Item) -> None:
    fixed = replace(item, interval_override=9)
    est = estimate(fixed, purchases_every(30, 6), TODAY, prior=20)
    assert est.basis == "override"
    assert est.due_on == TODAY + timedelta(days=9)


def test_two_lines_in_one_order_are_one_purchase() -> None:
    same_day = [
        Purchase(id=None, item_id=1, bought_on=TODAY, quantity=1),
        Purchase(id=None, item_id=1, bought_on=TODAY, quantity=2),
    ]
    merged = merge_same_day(same_day)
    assert len(merged) == 1 and merged[0].quantity == 3


def test_no_history_at_all_is_survivable(item: Item) -> None:
    est = estimate(item, [], TODAY, prior=14)
    assert est.due_on is None and est.purchases == 0


# ----- deciding whether to speak up ------------------------------------

MONDAY = date(2026, 9, 14)
FRIDAY = date(2026, 9, 18)


def _assess(item: Item, days_since: int, every: int, *, today: date = MONDAY):
    history = purchases_every(every, 6, last=today - timedelta(days=days_since))
    est = estimate(item, history, today)
    return assess(est, today=today, slot_date=MONDAY, horizon_date=FRIDAY)


def test_something_that_lasts_past_the_next_delivery_is_left_alone(item: Item) -> None:
    assert _assess(item, days_since=1, every=30) is None


def test_something_due_before_the_delivery_after_this_one_is_suggested(item: Item) -> None:
    """The whole point: it survives Monday but not until Friday, so buy it now."""
    suggestion = _assess(item, days_since=11, every=14)
    assert suggestion is not None and suggestion.status is Status.SOON


def test_something_already_overdue_is_flagged_as_such(item: Item) -> None:
    suggestion = _assess(item, days_since=40, every=14)
    assert suggestion is not None and suggestion.status is Status.OVERDUE


def test_being_more_overdue_scores_higher(item: Item) -> None:
    mild = _assess(item, days_since=15, every=14)
    bad = _assess(item, days_since=45, every=14)
    assert bad.score > mild.score


def test_an_item_due_exactly_on_the_horizon_still_makes_the_list(item: Item) -> None:
    """It scores lowest, but a zero score would hide it entirely."""
    suggestion = _assess(item, days_since=10, every=14)
    assert suggestion is not None and suggestion.score > 0


def test_paused_items_are_never_suggested(item: Item) -> None:
    assert _assess(replace(item, paused=True), days_since=40, every=14) is None


def test_snoozing_covers_this_delivery_but_not_the_next(item: Item) -> None:
    snoozed = replace(item, snoozed_until=MONDAY)
    assert _assess(snoozed, days_since=40, every=14) is None

    history = purchases_every(14, 6, last=MONDAY - timedelta(days=40))
    est = estimate(snoozed, history, FRIDAY)
    assert assess(est, today=FRIDAY, slot_date=FRIDAY, horizon_date=date(2026, 9, 21)) is not None


def test_a_nudge_stretches_the_estimate(item: Item) -> None:
    plain = estimate(item, purchases_every(14, 6), MONDAY)
    nudged = estimate(replace(item, nudge=1.5), purchases_every(14, 6), MONDAY)
    assert nudged.due_on > plain.due_on


def test_the_reason_reads_like_a_sentence(item: Item) -> None:
    suggestion = _assess(item, days_since=40, every=14)
    assert suggestion.reason.startswith("Due ")
    assert "ago ago" not in suggestion.reason
    assert "today ago" not in suggestion.reason
