"""Weekend shopping belongs to the weekend order.

Steak and beer are bought on Fridays for the weekend; chicken goes in the
Monday order for midweek. Nothing in the interval arithmetic can see that: both
are purchases a week apart. Left alone, the "will it last until the delivery
after this one" rule puts every Friday item on Monday's list, because Friday is
exactly when it runs out.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta

import pytest

from trolley.config import Config, SuggestConfig
from trolley.db import Database
from trolley.ingest import ingest
from trolley.model import ParsedLine, ParsedOrder, Purchase
from trolley.predict import slot_affinity
from trolley.suggest import build, estimates, render_text

from conftest import DUBLIN

#: The two evenings an order actually gets built.
SUNDAY = datetime(2026, 9, 13, 19, 0, tzinfo=DUBLIN)
THURSDAY = datetime(2026, 9, 17, 19, 0, tzinfo=DUBLIN)

WEEKEND = ("Tesco Irish Striploin Steak 2 Pack", "Heineken Lager 12 X 330Ml")
MIDWEEK = ("Tesco Irish Chicken Breast Fillets 600G",)
EVERY_ORDER = ("Tesco British Semi Skimmed Milk 2.272L", "Tesco White Sliced Bread 800G")


@pytest.fixture
def config(config: Config) -> Config:
    """Pin the restock intervals so these tests are about the day, not the maths.

    Left to blend with the catalogue's typical intervals, steak comes out at
    eight days rather than seven, and is simply not due in the window being
    tested. That is correct behaviour, and it is not what is under test here.
    """
    return replace(config, intervals={"steak": 7, "beer": 7, "chicken": 7,
                                      "milk": 3.5, "bread": 3.5})


def shopping_habit(
    db: Database, config: Config, *, through: datetime = SUNDAY, weeks: int = 12
) -> None:
    """Months of the pattern above, every delivery up to the evening given.

    The cut-off matters. Generating history that stops before the last
    delivery that should have happened makes everything look overdue, and an
    overdue item is meant to escape the hold, so the test would pass or fail
    for the wrong reason.
    """
    orders = []
    day = through.date()
    while len(orders) < weeks * 2:
        if day.weekday() in (0, 4):
            names = (MIDWEEK if day.weekday() == 0 else WEEKEND) + EVERY_ORDER
            orders.append(
                ParsedOrder(
                    bought_on=day,
                    lines=tuple(ParsedLine(raw_name=name) for name in names),
                    order_ref=f"{day}",
                    source="test",
                )
            )
        day -= timedelta(days=1)
    ingest(db, orders, config)


def suggested(report) -> set[str]:
    return {suggestion.item.key for suggestion in report.suggestions}


def held(report) -> dict[str, str]:
    return {s.item.key: s.deferred_to for s in report.deferred}


# ----- learning the day ------------------------------------------------


def test_a_weekday_habit_is_spotted(item) -> None:
    fridays = [
        Purchase(id=None, item_id=1, bought_on=date(2026, 9, 11) - timedelta(days=7 * n))
        for n in range(8)
    ]
    assert slot_affinity(fridays, date(2026, 9, 14)) == ("friday", 1.0)


def test_something_bought_in_every_order_has_no_day(item) -> None:
    both = [
        Purchase(id=None, item_id=1, bought_on=day)
        for day in (date(2026, 9, 14) - timedelta(days=n) for n in range(56))
        if day.weekday() in (0, 4)
    ]
    assert slot_affinity(both, date(2026, 9, 14))[0] is None


def test_a_short_run_is_not_a_habit(item) -> None:
    fridays = [
        Purchase(id=None, item_id=1, bought_on=date(2026, 9, 11) - timedelta(days=7 * n))
        for n in range(3)
    ]
    assert slot_affinity(fridays, date(2026, 9, 14))[0] is None


def test_one_stray_purchase_does_not_break_the_habit(item) -> None:
    days = [date(2026, 9, 11) - timedelta(days=7 * n) for n in range(7)]
    days.append(date(2026, 8, 24))  # one Monday among the Fridays
    purchases = [Purchase(id=None, item_id=1, bought_on=day) for day in days]
    assert slot_affinity(purchases, date(2026, 9, 14))[0] == "friday"


def test_a_habit_that_moved_is_followed(item) -> None:
    """Weighting by recency means last year's routine stops counting."""
    old = [date(2025, 9, 8) + timedelta(days=7 * n) for n in range(8)]  # Mondays
    new = [date(2026, 7, 10) + timedelta(days=7 * n) for n in range(10)]  # Fridays
    purchases = [Purchase(id=None, item_id=1, bought_on=day) for day in sorted(old + new)]
    assert slot_affinity(purchases, date(2026, 9, 14))[0] == "friday"


def test_a_habit_that_only_just_moved_is_not_believed_yet(item) -> None:
    """Two Fridays after months of Mondays is a blip until it keeps happening."""
    old = [date(2026, 6, 1) + timedelta(days=7 * n) for n in range(12)]  # Mondays
    new = [date(2026, 9, 4), date(2026, 9, 11)]  # Fridays
    purchases = [Purchase(id=None, item_id=1, bought_on=day) for day in sorted(old + new)]
    assert slot_affinity(purchases, date(2026, 9, 14))[0] == "monday"


# ----- acting on it ----------------------------------------------------


def test_the_weekend_shopping_is_not_put_on_the_monday_list(db, config) -> None:
    shopping_habit(db, config)
    report = build(db, config, SUNDAY)

    assert report.slot.day == date(2026, 9, 14)
    assert "steak" not in suggested(report) and "beer" not in suggested(report)
    assert held(report) == {"steak": "friday", "beer": "friday"}


def test_the_weekend_shopping_is_on_the_friday_list(db, config) -> None:
    shopping_habit(db, config, through=THURSDAY)
    report = build(db, config, THURSDAY)

    assert report.slot.day == date(2026, 9, 18)
    assert {"steak", "beer"} <= suggested(report)


def test_the_midweek_shopping_is_on_the_monday_list(db, config) -> None:
    shopping_habit(db, config)
    assert "chicken" in suggested(build(db, config, SUNDAY))


def test_the_midweek_shopping_is_held_back_on_friday(db, config) -> None:
    shopping_habit(db, config, through=THURSDAY)
    assert held(build(db, config, THURSDAY)).get("chicken") == "monday"


def test_things_bought_in_every_order_are_never_held_back(db, config) -> None:
    for moment in (SUNDAY, THURSDAY):
        shopping_habit(db, config, through=moment)
        report = build(db, config, moment)
        assert {"milk", "bread"} <= suggested(report)
        assert "milk" not in held(report) and "bread" not in held(report)


def test_a_learned_day_gives_way_when_you_would_actually_run_out(db, config) -> None:
    """A Friday habit is a preference, not a rule: running out still wins."""
    shopping_habit(db, config)
    steak = db.item_by_key("steak")
    with db.connect() as conn:
        # No steak for a month, so Friday is far too late to start worrying.
        conn.execute(
            "DELETE FROM purchases WHERE item_id = ? AND bought_on > ?",
            (steak.id, "2026-08-14"),
        )
    report = build(db, config, SUNDAY)
    assert "steak" in suggested(report)


def test_a_pinned_day_is_obeyed_even_then(db, config) -> None:
    """Pinning says this is a weekend thing, and means it."""
    shopping_habit(db, config)
    steak = db.item_by_key("steak")
    db.update_item(steak.id, slot_preference="friday")
    with db.connect() as conn:
        conn.execute(
            "DELETE FROM purchases WHERE item_id = ? AND bought_on > ?",
            (steak.id, "2026-08-14"),
        )
    report = build(db, config, SUNDAY)
    assert "steak" not in suggested(report)
    assert held(report)["steak"] == "friday"


def test_pinning_any_opts_an_item_out_entirely(db, config) -> None:
    shopping_habit(db, config)
    db.update_item(db.item_by_key("steak").id, slot_preference="any")
    report = build(db, config, SUNDAY)
    assert "steak" in suggested(report)
    assert "steak" not in held(report)


def test_a_pinned_day_beats_a_history_that_disagrees(db, config) -> None:
    shopping_habit(db, config)
    db.update_item(db.item_by_key("chicken").id, slot_preference="friday")
    chicken = next(e for e in estimates(db, config, date(2026, 9, 14)) if e.item.key == "chicken")
    assert (chicken.preferred_slot, chicken.slot_pinned) == ("friday", True)


def test_the_whole_idea_can_be_switched_off(db, config) -> None:
    shopping_habit(db, config)
    plain = replace(config, suggest=SuggestConfig(slot_awareness=False))
    report = build(db, plain, SUNDAY)
    assert {"steak", "beer"} <= suggested(report)
    assert report.deferred == ()


def test_a_pin_still_works_with_the_learning_switched_off(db, config) -> None:
    """Turning off the guessing must not throw away an explicit instruction."""
    shopping_habit(db, config)
    db.update_item(db.item_by_key("steak").id, slot_preference="friday")
    plain = replace(config, suggest=SuggestConfig(slot_awareness=False))
    assert held(build(db, plain, SUNDAY)).get("steak") == "friday"


def test_a_day_with_no_delivery_any_more_is_not_waited_for(db, config) -> None:
    """Deliveries moved to Tuesday and Saturday; nothing should stick waiting."""
    shopping_habit(db, config)
    db.update_item(db.item_by_key("steak").id, slot_preference="wednesday")
    report = build(db, config, SUNDAY)
    assert "steak" not in held(report)


def test_the_message_says_what_is_being_held(db, config) -> None:
    shopping_habit(db, config)
    text = render_text(build(db, config, SUNDAY))
    assert "Waiting for their usual delivery" in text
    assert "Steak" in text


def test_the_reason_explains_the_hold(db, config) -> None:
    shopping_habit(db, config)
    steak = next(s for s in build(db, config, SUNDAY).deferred if s.item.key == "steak")
    assert steak.reason.startswith("Usually a Friday item.")


def test_held_items_are_not_lost_from_the_count(db, config) -> None:
    """They are held, not dropped: the app can still show them."""
    shopping_habit(db, config)
    report = build(db, config, SUNDAY)
    assert len(report.deferred) == 2
