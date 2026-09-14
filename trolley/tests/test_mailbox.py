"""The mailbox watcher: the part that makes this run without being told to."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta

import pytest

from trolley.config import Config, MailboxConfig
from trolley.db import Database
from trolley.mailbox import (
    UID_KEY,
    VALIDITY_KEY,
    Mailbox,
    MailboxError,
    collect,
    collect_all,
    imap_date,
    read_order,
    reset_position,
)

from fake_imap import FakeIMAP, build_email, receipt_html

SETTINGS = MailboxConfig(
    enabled=True,
    host="imap.example.test",
    username="shopper@example.test",
    folder="INBOX",
    search='FROM "tesco"',
    backfill_days=730,
)


def configured(config: Config, **overrides) -> Config:
    """The session's config, pointed at the fake mailbox."""
    return replace(config, mailbox=replace(SETTINGS, **overrides))


def confirmation(ref: str, day: date, *lines: tuple[int, str, str]) -> bytes:
    return build_email("Your Tesco order confirmation", receipt_html(ref, day, list(lines)), day)


def receipt(ref: str, day: date, *lines: tuple[int, str, str]) -> bytes:
    return build_email("Your Tesco receipt", receipt_html(ref, day, list(lines)), day)


MILK = (2, "Tesco British Semi Skimmed Milk 2.272L", "2.50")
ROLL = (1, "Tesco Toilet Tissue 9 Roll", "4.00")
BREAD = (1, "Tesco White Sliced Bread 800G", "1.20")


def box(server: FakeIMAP, settings: MailboxConfig = SETTINGS) -> Mailbox:
    return Mailbox(settings, connect=lambda: server)


def test_order_emails_become_history_without_being_asked(db: Database, config: Config) -> None:
    server = FakeIMAP({1: confirmation("A1", date(2026, 9, 1), MILK, ROLL)})
    result = collect(db, configured(config), mailbox=box(server))

    assert result.receipts == 1
    assert {item.key for item in db.items()} == {"milk", "toilet-roll"}
    assert "1 message checked" in result.summary()


def test_mail_that_is_not_a_receipt_is_passed_over(db: Database, config: Config) -> None:
    server = FakeIMAP({
        1: build_email("Clubcard points update", "<p>You have 240 points.</p>"),
        2: confirmation("A1", date(2026, 9, 1), MILK),
    })
    result = collect(db, configured(config), mailbox=box(server))

    assert (result.examined, result.receipts, result.unreadable) == (2, 1, 1)
    assert "1 not a receipt" in result.summary()


def test_each_message_is_only_read_once(db: Database, config: Config) -> None:
    server = FakeIMAP({1: confirmation("A1", date(2026, 9, 1), MILK)})
    settings = configured(config)

    first = collect(db, settings, mailbox=box(server))
    second = collect(db, settings, mailbox=box(server))

    assert (first.examined, second.examined) == (1, 0)
    assert second.summary() == "no new mail"
    assert db.get_state(UID_KEY) == "1"


def test_only_mail_newer_than_the_last_read_is_fetched(db: Database, config: Config) -> None:
    server = FakeIMAP({1: confirmation("A1", date(2026, 9, 1), MILK)})
    settings = configured(config)
    collect(db, settings, mailbox=box(server))

    server.messages[2] = confirmation("A2", date(2026, 9, 4), BREAD)
    second = collect(db, settings, mailbox=box(server))

    assert second.examined == 1
    # A UID window, not another date sweep. It starts at the last UID read
    # because IMAP's "n:*" returns the highest message even when n is past it,
    # so the boundary is excluded on this side instead.
    assert "UID 1:*" in server.searches[-1] and "SINCE" not in server.searches[-1]


def test_marketing_mail_does_not_get_re_read_for_ever(db: Database, config: Config) -> None:
    """Progress advances past everything examined, not just the receipts."""
    server = FakeIMAP({1: build_email("Half price this week", "<p>Offers.</p>")})
    settings = configured(config)
    collect(db, settings, mailbox=box(server))
    assert db.get_state(UID_KEY) == "1"
    assert collect(db, settings, mailbox=box(server)).examined == 0


def test_the_receipt_replaces_the_confirmation_it_supersedes(db: Database, config: Config) -> None:
    """The confirmation says what was ordered; the receipt says what arrived."""
    day = date(2026, 9, 1)
    server = FakeIMAP({1: confirmation("A1", day, MILK, ROLL)})
    settings = configured(config)
    collect(db, settings, mailbox=box(server))
    assert len(db.purchases()) == 2

    # Toilet roll was out of stock, so it is not on the receipt.
    server.messages[2] = receipt("A1", day, MILK, BREAD)
    result = collect(db, settings, mailbox=box(server))

    assert result.ingest.replaced_orders == 1
    bought = {db.item(p.item_id).key for p in db.purchases()}
    assert bought == {"milk", "bread"}


def test_an_older_email_arriving_late_does_not_undo_the_receipt(db: Database, config: Config) -> None:
    day = date(2026, 9, 1)
    server = FakeIMAP({1: receipt("A1", day, MILK)})
    settings = configured(config)
    collect(db, settings, mailbox=box(server))

    server.messages[2] = confirmation("A1", day, MILK, ROLL)
    result = collect(db, settings, mailbox=box(server))

    assert result.ingest.skipped_orders == 1
    assert {db.item(p.item_id).key for p in db.purchases()} == {"milk"}


def test_a_first_run_searches_back_by_date_not_by_uid(db: Database, config: Config) -> None:
    server = FakeIMAP({1: confirmation("A1", date(2026, 9, 1), MILK)})
    collect(db, configured(config, backfill_days=365), mailbox=box(server))

    query = server.searches[0]
    assert 'FROM "tesco"' in query and "SINCE" in query and "UID" not in query


def test_a_renumbered_mailbox_is_read_again_from_the_start(db: Database, config: Config) -> None:
    server = FakeIMAP({1: confirmation("A1", date(2026, 9, 1), MILK)}, uidvalidity="1000")
    settings = configured(config)
    collect(db, settings, mailbox=box(server))

    server.uidvalidity = "2000"  # The server rebuilt the folder.
    result = collect(db, settings, mailbox=box(server))

    assert result.reset and result.examined == 1
    assert db.get_state(VALIDITY_KEY) == "2000"
    # Re-reading must not double-count what is already known.
    assert len(db.purchases()) == 1


def test_a_dry_run_reads_but_records_nothing(db: Database, config: Config) -> None:
    server = FakeIMAP({1: confirmation("A1", date(2026, 9, 1), MILK)})
    result = collect(db, configured(config), mailbox=box(server), dry_run=True)

    assert result.receipts == 1
    assert db.items() == [] and not db.get_state(UID_KEY)


def test_messages_can_be_marked_read_when_asked(db: Database, config: Config) -> None:
    server = FakeIMAP({1: confirmation("A1", date(2026, 9, 1), MILK)})
    collect(db, configured(config, mark_seen=True), mailbox=box(server))
    assert server.flagged == [1]


def test_the_inbox_is_left_alone_by_default(db: Database, config: Config) -> None:
    server = FakeIMAP({1: confirmation("A1", date(2026, 9, 1), MILK)})
    collect(db, configured(config), mailbox=box(server))
    assert server.flagged == []
    assert server.readonly is True


def test_a_backfill_keeps_going_until_it_is_caught_up(db: Database, config: Config) -> None:
    messages = {
        uid: confirmation(f"A{uid}", date(2026, 1, 1) + timedelta(days=uid * 3), MILK)
        for uid in range(1, 12)
    }
    server = FakeIMAP(messages)
    monkeypatched = collect_all(db, configured(config), mailbox=box(server))
    assert monkeypatched.examined == 11
    assert len(db.purchases()) == 11


def test_resetting_makes_it_read_everything_again(db: Database, config: Config) -> None:
    server = FakeIMAP({1: confirmation("A1", date(2026, 9, 1), MILK)})
    settings = configured(config)
    collect(db, settings, mailbox=box(server))

    reset_position(db)
    assert collect(db, settings, mailbox=box(server)).examined == 1


def test_a_rejected_password_says_what_to_do_about_it(db: Database, config: Config) -> None:
    server = FakeIMAP({}, fail_login=True)
    with pytest.raises(MailboxError, match="app password"):
        collect(db, configured(config), mailbox=box(server))


def test_a_missing_folder_names_itself(db: Database, config: Config) -> None:
    server = FakeIMAP({}, fail_select=True)
    with pytest.raises(MailboxError, match="no folder called"):
        collect(db, configured(config, folder="Tesco"), mailbox=box(server))


def test_a_connection_failure_is_reported_not_raised_raw(db: Database, config: Config) -> None:
    def refuse():
        raise OSError("connection refused")

    with pytest.raises(MailboxError, match="imap.example.test"):
        collect(db, configured(config), mailbox=Mailbox(SETTINGS, connect=refuse))


def test_the_connection_is_always_closed(db: Database, config: Config) -> None:
    server = FakeIMAP({1: confirmation("A1", date(2026, 9, 1), MILK)})
    collect(db, configured(config), mailbox=box(server))
    assert server.logouts == 1


def test_check_reports_what_it_can_see() -> None:
    server = FakeIMAP({1: confirmation("A1", date(2026, 9, 1), MILK)})
    message = Mailbox(SETTINGS, connect=lambda: server).check()
    assert "1 message(s) matching" in message
    assert "imap.example.test" in message


def test_unparseable_bytes_do_not_take_the_poll_down() -> None:
    assert read_order(b"\xff\xfe not an email at all") is None


@pytest.mark.parametrize(
    "day, expected",
    [(date(2026, 1, 5), "05-Jan-2026"), (date(2026, 12, 31), "31-Dec-2026")],
)
def test_dates_are_formatted_the_way_imap_wants(day: date, expected: str) -> None:
    assert imap_date(day) == expected
