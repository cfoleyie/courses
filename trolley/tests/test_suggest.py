"""The behaviour the app exists for, end to end over a real-shaped history."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from trolley.config import Config
from trolley.db import Database
from trolley.importers import FakeImporter
from trolley.ingest import ingest
from trolley.model import ParsedLine, ParsedOrder, Status
from trolley.suggest import build, decide, estimates, render_text

from conftest import DUBLIN, TODAY

SUNDAY = datetime(2026, 9, 13, 19, 0, tzinfo=DUBLIN)


def seed(db: Database, config: Config, weeks: int = 40) -> None:
    ingest(db, FakeImporter().generate(weeks=weeks, today=TODAY), config)


def buy(db: Database, config: Config, name: str, days: list[int], *, today: date = TODAY) -> None:
    ingest(
        db,
        [
            ParsedOrder(
                bought_on=today - timedelta(days=ago),
                lines=(ParsedLine(raw_name=name),),
                order_ref=f"{name}-{ago}",
                source="test",
            )
            for ago in days
        ],
        config,
    )


def names(report) -> list[str]:
    return [suggestion.item.name for suggestion in report.suggestions]


def test_the_list_is_built_for_the_next_delivery(db: Database, config: Config) -> None:
    seed(db, config)
    report = build(db, config, SUNDAY)
    assert report.slot.day == date(2026, 9, 14)
    assert report.horizon.day == date(2026, 9, 18)
    assert report.suggestions


def test_the_forgotten_staple_goes_to_the_top(db: Database, config: Config) -> None:
    """The example that started this: no toilet roll for weeks, so ask about it."""
    seed(db, config)
    toilet_roll = db.item_by_key("toilet-roll")
    with db.connect() as conn:
        conn.execute(
            "DELETE FROM purchases WHERE item_id = ? AND bought_on > ?",
            (toilet_roll.id, (TODAY - timedelta(days=40)).isoformat()),
        )

    report = build(db, config, SUNDAY)
    top = report.suggestions[0]
    assert top.item.key == "toilet-roll"
    assert top.status is Status.OVERDUE
    assert "Due" in top.reason


def test_something_bought_yesterday_is_not_suggested(db: Database, config: Config) -> None:
    buy(db, config, "Tesco Bin Liners 40 Pack", [120, 80, 40, 1])
    assert "Bin bags" not in names(build(db, config, SUNDAY))


def test_a_one_off_purchase_is_never_treated_as_a_habit(db: Database, config: Config) -> None:
    buy(db, config, "Tesco Birthday Candles 24 Pack", [200])
    report = build(db, config, SUNDAY)
    assert "Birthday candles" not in names(report)
    assert any(est.item.key == "birthday-candles" for est in report.unsure)


def test_a_known_staple_bought_once_is_still_worth_asking_about(db: Database, config: Config) -> None:
    """No pattern yet, but the catalogue knows roughly how often this runs out."""
    buy(db, config, "Tesco Toilet Tissue 9 Roll", [30])
    report = build(db, config, SUNDAY)
    assert "Toilet roll" in names(report)
    assert report.suggestions[0].estimate.basis == "prior"


def test_adding_something_takes_it_off_the_suggestions(db: Database, config: Config) -> None:
    seed(db, config)
    report = build(db, config, SUNDAY)
    first = report.suggestions[0]
    decide(db, config, first.item.id, report.slot.day, "add")

    after = build(db, config, SUNDAY)
    assert first.item.name not in names(after)
    assert [entry["item_id"] for entry in db.list_for(report.slot.day)] == [first.item.id]


def test_not_now_skips_this_delivery_only(db: Database, config: Config) -> None:
    seed(db, config)
    report = build(db, config, SUNDAY)
    first = report.suggestions[0]
    decide(db, config, first.item.id, report.slot.day, "snooze")

    assert first.item.name not in names(build(db, config, SUNDAY))
    # Thursday evening, planning Friday: it is back.
    thursday = datetime(2026, 9, 17, 20, 0, tzinfo=DUBLIN)
    assert first.item.name in names(build(db, config, thursday))


def test_turning_a_suggestion_down_stretches_the_estimate(db: Database, config: Config) -> None:
    seed(db, config)
    report = build(db, config, SUNDAY)
    item_id = report.suggestions[0].item.id
    before = next(e for e in estimates(db, config, TODAY) if e.item.id == item_id)

    decide(db, config, item_id, report.slot.day, "dismiss")
    after = next(e for e in estimates(db, config, TODAY) if e.item.id == item_id)
    assert after.interval > before.interval


def test_accepting_a_suggestion_clears_an_earlier_stretch(db: Database, config: Config) -> None:
    seed(db, config)
    report = build(db, config, SUNDAY)
    item_id = report.suggestions[0].item.id
    decide(db, config, item_id, report.slot.day, "dismiss")
    assert db.item(item_id).nudge > 1.0

    decide(db, config, item_id, report.slot.day, "add")
    assert db.item(item_id).nudge == 1.0


def test_dismissals_cannot_push_an_item_away_for_ever(db: Database, config: Config) -> None:
    seed(db, config)
    report = build(db, config, SUNDAY)
    item_id = report.suggestions[0].item.id
    for _ in range(20):
        decide(db, config, item_id, report.slot.day, "dismiss")
    assert db.item(item_id).nudge == config.suggest.nudge_max


def test_pausing_and_resuming_an_item(db: Database, config: Config) -> None:
    seed(db, config)
    report = build(db, config, SUNDAY)
    first = report.suggestions[0]
    decide(db, config, first.item.id, report.slot.day, "pause")
    assert first.item.name not in names(build(db, config, SUNDAY))

    decide(db, config, first.item.id, report.slot.day, "resume")
    assert first.item.name in names(build(db, config, SUNDAY))


def test_the_list_is_capped_so_it_stays_readable(db: Database, config: Config) -> None:
    seed(db, config)
    small = Config(
        server=config.server, slots=config.slots,
        suggest=type(config.suggest)(max_suggestions=2),
    )
    assert len(build(db, small, SUNDAY).suggestions) <= 2


def test_the_plain_text_version_reads_as_a_message(db: Database, config: Config) -> None:
    seed(db, config)
    text = render_text(build(db, config, SUNDAY))
    assert "Monday delivery" in text
    assert "to consider" in text


def test_an_empty_database_produces_an_empty_list(db: Database, config: Config) -> None:
    report = build(db, config, SUNDAY)
    assert report.suggestions == ()
    assert "nothing looks due" in render_text(report).casefold()


def test_no_slots_configured_means_no_report(db: Database) -> None:
    assert build(db, Config(slots=()), SUNDAY) is None
