"""Persistence: the parts where getting it wrong corrupts the history."""

from __future__ import annotations

from datetime import date

from trolley.db import Database


def test_an_item_key_is_claimed_once(db: Database) -> None:
    first = db.upsert_item("milk", "Milk", "dairy")
    again = db.upsert_item("milk", "Something else", "other")
    assert first.id == again.id
    assert again.name == "Milk"  # The first write wins; imports never rename.


def test_the_same_line_of_the_same_order_is_stored_once(db: Database) -> None:
    item = db.upsert_item("milk", "Milk")
    assert db.add_purchase(item.id, date(2026, 9, 1), 1, "Tesco Milk", "ORD-1")
    assert not db.add_purchase(item.id, date(2026, 9, 1), 1, "Tesco Milk", "ORD-1")
    assert len(db.purchases(item.id)) == 1


def test_two_different_products_in_one_order_both_count(db: Database) -> None:
    item = db.upsert_item("milk", "Milk")
    db.add_purchase(item.id, date(2026, 9, 1), 1, "Tesco Whole Milk", "ORD-1")
    db.add_purchase(item.id, date(2026, 9, 1), 1, "Tesco Semi Skimmed Milk", "ORD-1")
    assert len(db.purchases(item.id)) == 2


def test_purchases_without_an_order_reference_are_not_deduped(db: Database) -> None:
    """Manual entries are deliberate: two taps mean two purchases."""
    item = db.upsert_item("milk", "Milk")
    db.add_purchase(item.id, date(2026, 9, 1), 1, "Milk", None)
    db.add_purchase(item.id, date(2026, 9, 1), 1, "Milk", None)
    assert len(db.purchases(item.id)) == 2


def test_purchases_come_back_in_date_order(db: Database) -> None:
    item = db.upsert_item("milk", "Milk")
    for day in (date(2026, 9, 8), date(2026, 9, 1), date(2026, 9, 15)):
        db.add_purchase(item.id, day, 1, "Milk", f"ORD-{day}")
    assert [p.bought_on for p in db.purchases(item.id)] == [
        date(2026, 9, 1), date(2026, 9, 8), date(2026, 9, 15)
    ]


def test_updates_round_trip_through_sqlite_types(db: Database) -> None:
    item = db.upsert_item("milk", "Milk")
    db.update_item(item.id, paused=True, snoozed_until=date(2026, 9, 14), nudge=1.3)
    updated = db.item(item.id)
    assert updated.paused is True
    assert updated.snoozed_until == date(2026, 9, 14)
    assert updated.nudge == 1.3


def test_unknown_fields_are_ignored_rather_than_injected(db: Database) -> None:
    item = db.upsert_item("milk", "Milk")
    db.update_item(item.id, name="Milk", nonsense="1; DROP TABLE items")
    assert db.item(item.id) is not None


def test_the_list_holds_one_row_per_item(db: Database) -> None:
    item = db.upsert_item("milk", "Milk")
    day = date(2026, 9, 14)
    db.add_to_list(day, item.id, 1)
    db.add_to_list(day, item.id, 3)
    entries = db.list_for(day)
    assert len(entries) == 1 and entries[0]["quantity"] == 3

    db.remove_from_list(day, item.id)
    assert db.list_for(day) == []


def test_lists_for_different_deliveries_do_not_mix(db: Database) -> None:
    item = db.upsert_item("milk", "Milk")
    db.add_to_list(date(2026, 9, 14), item.id)
    db.add_to_list(date(2026, 9, 18), item.id)
    db.clear_list(date(2026, 9, 14))
    assert db.list_for(date(2026, 9, 14)) == []
    assert len(db.list_for(date(2026, 9, 18))) == 1


def test_deleting_an_item_takes_its_history_with_it(db: Database) -> None:
    item = db.upsert_item("milk", "Milk")
    db.add_purchase(item.id, date(2026, 9, 1), 1, "Milk", "ORD-1")
    db.add_to_list(date(2026, 9, 14), item.id)
    db.delete_item(item.id)
    assert db.purchases() == [] and db.list_for(date(2026, 9, 14)) == []


def test_state_and_orders_survive_a_reopen(config, db: Database) -> None:
    db.set_state("notified:2026-09-14", "yes")
    db.record_order("ORD-1", date(2026, 9, 14), "email", 12)
    reopened = Database(config.server.database)
    assert reopened.get_state("notified:2026-09-14") == "yes"
    assert reopened.order_seen("ORD-1")
    assert reopened.orders()[0]["lines"] == 12
