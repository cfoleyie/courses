"""End to end over a real socket, with real imaplib doing the talking.

These are the cases the mocked tests cannot see: command quoting, the UID
SEARCH wire format, and literal parsing on FETCH.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date

import pytest

from trolley.config import Config, MailboxConfig
from trolley.db import Database
from trolley.mailbox import Mailbox, MailboxError, collect

from fake_imap import build_email, receipt_html
from imap_server import TinyIMAP

MILK = (2, "Tesco British Semi Skimmed Milk 2.272L", "2.50")
ROLL = (1, "Tesco Toilet Tissue 9 Roll", "4.00")


def order_email(ref: str, day: date) -> bytes:
    return build_email(
        "Your Tesco order confirmation", receipt_html(ref, day, [MILK, ROLL]), day
    )


@pytest.fixture
def server():
    messages = {
        1: order_email("A1", date(2026, 8, 20)),
        2: order_email("A2", date(2026, 9, 1)),
    }
    with TinyIMAP(messages) as running:
        yield running


def settings_for(server: TinyIMAP, **overrides) -> MailboxConfig:
    return replace(
        MailboxConfig(
            enabled=True,
            host="127.0.0.1",
            port=server.port,
            username="columfoley@gmail.com",
            security="none",
            folder="INBOX",
            search='FROM "tesco"',
        ),
        **overrides,
    )


def test_real_imap_round_trip_builds_the_history(
    db: Database, config: Config, server: TinyIMAP, monkeypatch
) -> None:
    monkeypatch.setenv("TROLLEY_IMAP_PASSWORD", "app-password")
    settings = settings_for(server)
    result = collect(db, replace(config, mailbox=settings))

    assert (result.examined, result.receipts) == (2, 2)
    assert {item.key for item in db.items()} == {"milk", "toilet-roll"}
    assert len(db.purchases()) == 4
    assert server.logins == [("columfoley@gmail.com", "app-password")]


def test_the_second_pass_over_a_real_server_fetches_nothing(
    db: Database, config: Config, server: TinyIMAP, monkeypatch
) -> None:
    monkeypatch.setenv("TROLLEY_IMAP_PASSWORD", "app-password")
    trial = replace(config, mailbox=settings_for(server))
    collect(db, trial)
    assert collect(db, trial).examined == 0


def test_a_new_email_on_a_real_server_is_picked_up(
    db: Database, config: Config, server: TinyIMAP, monkeypatch
) -> None:
    monkeypatch.setenv("TROLLEY_IMAP_PASSWORD", "app-password")
    trial = replace(config, mailbox=settings_for(server))
    collect(db, trial)

    server.messages[3] = order_email("A3", date(2026, 9, 12))
    assert collect(db, trial).examined == 1
    assert len(db.purchases()) == 6


def test_a_folder_with_a_space_survives_the_wire(
    db: Database, config: Config, server: TinyIMAP, monkeypatch
) -> None:
    """Unquoted, the server sees two arguments and rejects the command."""
    monkeypatch.setenv("TROLLEY_IMAP_PASSWORD", "app-password")
    server.folders.add("Shopping/Tesco Orders")
    settings = settings_for(server, folder="Shopping/Tesco Orders")
    result = collect(db, replace(config, mailbox=settings))
    assert result.receipts == 2


def test_a_rejected_password_over_a_real_socket_becomes_a_clear_error(
    server: TinyIMAP, monkeypatch
) -> None:
    """imaplib raises its own exception type; it must not escape as one."""
    monkeypatch.setenv("TROLLEY_IMAP_PASSWORD", "wrong")
    with pytest.raises(MailboxError, match="rejected"):
        Mailbox(settings_for(server)).check()


def test_check_talks_to_a_real_server(
    config: Config, server: TinyIMAP, monkeypatch
) -> None:
    monkeypatch.setenv("TROLLEY_IMAP_PASSWORD", "app-password")
    message = Mailbox(settings_for(server)).check()
    assert "2 message(s) matching" in message


def test_the_search_sent_is_what_imap_expects(
    db: Database, config: Config, server: TinyIMAP, monkeypatch
) -> None:
    monkeypatch.setenv("TROLLEY_IMAP_PASSWORD", "app-password")
    trial = replace(config, mailbox=settings_for(server))
    collect(db, trial)
    collect(db, trial)

    searches = [command for command in server.commands if command.startswith("UID SEARCH")]
    assert 'FROM "tesco"' in searches[0] and "SINCE" in searches[0]
    assert "UID 2:*" in searches[-1]
