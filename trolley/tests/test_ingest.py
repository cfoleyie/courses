"""Getting receipts into the database exactly once, under the right item."""

from __future__ import annotations

from datetime import date

from trolley.config import Config
from trolley.db import Database
from trolley.ingest import ingest, relink
from trolley.model import ParsedLine, ParsedOrder


def order(day: date, *names: str, ref: str | None = "R1") -> ParsedOrder:
    return ParsedOrder(
        bought_on=day,
        lines=tuple(ParsedLine(raw_name=name) for name in names),
        order_ref=ref,
        source="test",
    )


def test_brands_of_the_same_thing_land_on_one_item(db: Database, config: Config) -> None:
    ingest(db, [
        order(date(2026, 9, 1), "Tesco Toilet Tissue 9 Roll", ref="A"),
        order(date(2026, 9, 15), "Andrex Classic Clean Toilet Tissue 12 Rolls", ref="B"),
    ], config)

    item = db.item_by_key("toilet-roll")
    assert item is not None
    assert len(db.purchases(item.id)) == 2


def test_importing_the_same_email_twice_changes_nothing(db: Database, config: Config) -> None:
    first = ingest(db, [order(date(2026, 9, 1), "Tesco Milk 2L")], config)
    second = ingest(db, [order(date(2026, 9, 1), "Tesco Milk 2L")], config)
    assert (first.added, second.added) == (1, 0)
    assert second.skipped_orders == 1
    assert len(db.purchases()) == 1


def test_re_reading_a_stored_order_still_does_not_duplicate(db: Database, config: Config) -> None:
    ingest(db, [order(date(2026, 9, 1), "Tesco Milk 2L")], config)
    forced = ingest(db, [order(date(2026, 9, 1), "Tesco Milk 2L")], config, force=True)
    assert forced.duplicates == 1
    assert len(db.purchases()) == 1


def test_a_dry_run_writes_nothing_but_still_reports(db: Database, config: Config) -> None:
    result = ingest(db, [order(date(2026, 9, 1), "Tesco Milk 2L")], config, dry_run=True)
    assert result.matches[0].item_name == "Milk"
    assert result.dry_run and "would be recorded" in result.summary()
    assert db.items() == [] and db.purchases() == []


def test_a_name_seen_before_skips_the_guesswork(db: Database, config: Config) -> None:
    ingest(db, [order(date(2026, 9, 1), "Tesco Milk 2L", ref="A")], config)
    again = ingest(db, [order(date(2026, 9, 8), "Tesco Milk 2L", ref="B")], config)
    assert again.matches[0].how == "alias"


def test_config_aliases_steer_the_match(db: Database) -> None:
    config = Config(aliases={"oat drink": "milk"})
    result = ingest(db, [order(date(2026, 9, 1), "Oatly Oat Drink Whole 1L")], config)
    assert result.matches[0].item_key == "milk"


def test_relinking_moves_the_history_as_well(db: Database, config: Config) -> None:
    ingest(db, [
        order(date(2026, 9, 1), "Oatly Oat Drink Whole 1L", ref="A"),
        order(date(2026, 9, 8), "Oatly Oat Drink Whole 1L", ref="B"),
    ], config)
    assert db.item_by_key("milk") is None

    message = relink(db, "Oatly Oat Drink Whole 1L", "milk")
    milk = db.item_by_key("milk")
    assert milk is not None
    assert len(db.purchases(milk.id)) == 2
    assert "2 past purchase" in message

    # And the rule sticks for the next import.
    later = ingest(db, [order(date(2026, 9, 15), "Oatly Oat Drink Whole 1L", ref="C")], config)
    assert later.matches[0].item_key == "milk"


def test_orders_without_a_reference_are_still_imported(db: Database, config: Config) -> None:
    result = ingest(db, [order(date(2026, 9, 1), "Tesco Milk 2L", ref=None)], config)
    assert result.added == 1


def test_relinking_cleans_up_the_item_it_emptied(db: Database, config: Config) -> None:
    """Otherwise an empty item sits in the list for ever saying "no pattern yet"."""
    ingest(db, [order(date(2026, 9, 1), "Oatly Oat Drink Whole 1L")], config)
    assert db.item_by_key("oatly-oat-drink-whole") is not None

    relink(db, "Oatly Oat Drink Whole 1L", "milk")
    assert db.item_by_key("oatly-oat-drink-whole") is None
    assert [item.key for item in db.items()] == ["milk"]


def test_relinking_leaves_an_item_that_still_has_other_history(db: Database, config: Config) -> None:
    ingest(db, [
        order(date(2026, 9, 1), "Tesco Semi Skimmed Milk 2L", ref="A"),
        order(date(2026, 9, 8), "Tesco Whole Milk 1L", ref="B"),
    ], config)
    relink(db, "Tesco Whole Milk 1L", "cream")
    assert db.item_by_key("milk") is not None
    assert len(db.purchases(db.item_by_key("milk").id)) == 1


def test_a_delivery_receipt_replaces_the_confirmation(db: Database, config: Config) -> None:
    """Substitutions mean the receipt, not the confirmation, is the truth."""
    from trolley.model import Stage

    def staged(stage: Stage, *names: str) -> ParsedOrder:
        return ParsedOrder(
            bought_on=date(2026, 9, 1),
            lines=tuple(ParsedLine(raw_name=name) for name in names),
            order_ref="ORD-1",
            source="email",
            stage=stage,
        )

    ingest(db, [staged(Stage.BOOKED, "Tesco Semi Skimmed Milk 2L", "Tesco Toilet Tissue 9 Roll")], config)
    later = ingest(db, [staged(Stage.DELIVERED, "Tesco Semi Skimmed Milk 2L", "Tesco Bananas Loose")], config)

    assert later.replaced_orders == 1
    assert {db.item(p.item_id).key for p in db.purchases()} == {"milk", "bananas"}


def test_emails_arriving_out_of_order_still_end_up_right(db: Database, config: Config) -> None:
    from trolley.model import Stage

    def staged(stage: Stage, *names: str) -> ParsedOrder:
        return ParsedOrder(
            bought_on=date(2026, 9, 1),
            lines=tuple(ParsedLine(raw_name=name) for name in names),
            order_ref="ORD-1",
            source="email",
            stage=stage,
        )

    # Both in one batch, receipt listed first: the sort puts them right.
    ingest(db, [
        staged(Stage.DELIVERED, "Tesco Semi Skimmed Milk 2L"),
        staged(Stage.BOOKED, "Tesco Semi Skimmed Milk 2L", "Tesco Toilet Tissue 9 Roll"),
    ], config)
    assert {db.item(p.item_id).key for p in db.purchases()} == {"milk"}
