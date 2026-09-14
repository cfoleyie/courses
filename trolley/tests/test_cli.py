"""The command line, which is how history gets in and how cron sends reminders."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from trolley.cli import main
from trolley.config import load_config
from trolley.db import Database

RECEIPT = """Tesco order confirmation
Order Number: 771234567
Delivery date: 18/09/2026

1 Tesco White Sliced Bread 800G  £1.20
2 Tesco Toilet Tissue 9 Roll  £8.00
Delivery charge  £4.50
"""


@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(
        f'[server]\ndatabase = "{tmp_path / "trolley.db"}"\n'
        '[notify]\nenabled = true\nchannel = "console"\n'
    )
    return path


def run(config_file: Path, *args: str) -> int:
    return main(["--config", str(config_file), *args])


def test_import_reads_a_receipt_and_says_what_it_found(config_file, tmp_path, capsys) -> None:
    receipt = tmp_path / "order.txt"
    receipt.write_text(RECEIPT)

    assert run(config_file, "import", str(receipt)) == 0
    out = capsys.readouterr().out
    assert "2 purchases recorded" in out

    db = Database(tmp_path / "trolley.db")
    assert db.item_by_key("toilet-roll") is not None


def test_a_dry_run_shows_the_matches_and_writes_nothing(config_file, tmp_path, capsys) -> None:
    receipt = tmp_path / "order.txt"
    receipt.write_text(RECEIPT)

    assert run(config_file, "import", "--dry-run", str(receipt)) == 0
    out = capsys.readouterr().out
    assert "-> Toilet roll" in out
    assert "Nothing was written" in out
    assert Database(tmp_path / "trolley.db").items() == []


def test_a_whole_folder_can_be_imported_at_once(config_file, tmp_path, capsys) -> None:
    folder = tmp_path / "emails"
    folder.mkdir()
    (folder / "one.txt").write_text(RECEIPT)
    (folder / "two.txt").write_text(RECEIPT.replace("18/09/2026", "25/09/2026").replace("771234567", "771234568"))
    (folder / "notes.md").write_text("not a receipt")

    assert run(config_file, "import", str(folder)) == 0
    assert "2 order" in capsys.readouterr().out


def test_suggest_and_items_run_against_real_history(config_file, tmp_path, capsys) -> None:
    assert run(config_file, "demo", "--weeks", "20") == 0
    capsys.readouterr()

    assert run(config_file, "suggest") == 0
    assert "delivery" in capsys.readouterr().out

    assert run(config_file, "items") == 0
    assert "Milk" in capsys.readouterr().out


def test_a_purchase_can_be_added_by_hand(config_file, tmp_path, capsys) -> None:
    assert run(config_file, "add", "Tesco Toilet Tissue 9 Roll", "--date", "14/09/2026") == 0
    assert "Toilet roll" in capsys.readouterr().out
    db = Database(tmp_path / "trolley.db")
    assert db.purchases(db.item_by_key("toilet-roll").id)[0].bought_on == date(2026, 9, 14)


def test_an_unreadable_date_is_refused(config_file, capsys) -> None:
    assert run(config_file, "add", "Milk", "--date", "sometime last week") == 1
    assert "could not read date" in capsys.readouterr().err


def test_link_moves_a_product_onto_another_item(config_file, tmp_path, capsys) -> None:
    run(config_file, "add", "Oatly Oat Drink Whole 1L")
    capsys.readouterr()
    assert run(config_file, "link", "Oatly Oat Drink Whole 1L", "milk") == 0
    assert "now counts as Milk" in capsys.readouterr().out


def test_notify_stays_quiet_when_nothing_is_due(config_file, capsys) -> None:
    assert run(config_file, "notify") == 0
    assert "nothing due" in capsys.readouterr().out


def test_notify_sends_the_list_when_there_is_one(config_file, capsys) -> None:
    run(config_file, "demo", "--weeks", "20")
    capsys.readouterr()
    assert run(config_file, "notify") == 0
    assert "delivery" in capsys.readouterr().out


def test_a_broken_config_is_reported_rather_than_crashing(tmp_path, capsys) -> None:
    bad = tmp_path / "config.toml"
    bad.write_text('[server]\ndatabse = "x"\n')
    assert main(["--config", str(bad), "suggest"]) == 2
    assert "config error" in capsys.readouterr().err


def test_mail_says_what_to_do_when_it_is_not_set_up(config_file, capsys) -> None:
    assert run(config_file, "mail") == 1
    assert "[mailbox] is not enabled" in capsys.readouterr().err


def test_mail_reports_a_connection_problem_without_a_traceback(tmp_path, capsys, monkeypatch) -> None:
    monkeypatch.setenv("TROLLEY_IMAP_PASSWORD", "secret")
    path = tmp_path / "config.toml"
    path.write_text(
        f'[server]\ndatabase = "{tmp_path / "trolley.db"}"\n'
        '[mailbox]\nenabled = true\nhost = "imap.invalid.test"\nusername = "a@b.test"\n'
    )
    assert main(["--config", str(path), "mail", "--test"]) == 1
    assert "imap.invalid.test" in capsys.readouterr().err


def test_setup_mail_goes_all_the_way_through_a_real_server(tmp_path, monkeypatch, capsys) -> None:
    """The whole command, over a socket, as someone would actually run it."""
    from datetime import date

    from trolley.setup_mail import Prompt

    from fake_imap import build_email, receipt_html
    from imap_server import TinyIMAP

    email = build_email(
        "Your Tesco order confirmation",
        receipt_html("A1", date(2026, 9, 1), [(1, "Tesco Toilet Tissue 9 Roll", "4.00")]),
        date(2026, 9, 1),
    )
    config = tmp_path / "config.toml"
    config.write_text(f'[server]\ndatabase = "{tmp_path / "trolley.db"}"\n')

    typed = iter(["INBOX", 'FROM "tesco"'])
    scripted = Prompt(
        ask=lambda question, default="": next(typed, "") or default,
        # Pasted the way Google displays it, spaces and all.
        secret=lambda prompt="": "abcd efgh ijkl mnop",
        confirm=lambda question, default=True: True,
        say=print,
    )
    monkeypatch.setattr("trolley.setup_mail.terminal_prompt", lambda: scripted)

    with TinyIMAP({1: email}) as server:
        exit_code = main([
            "--config", str(config), "setup-mail",
            "--username", "columfoley@gmail.com",
            "--host", "127.0.0.1", "--port", str(server.port), "--security", "none",
        ])
        assert exit_code == 0
        # The spaces are stripped before the server ever sees the password.
        assert all(
            credentials == ("columfoley@gmail.com", "abcdefghijklmnop")
            for credentials in server.logins
        )

    saved = load_config(config)
    assert saved.mailbox.enabled and saved.mailbox.username == "columfoley@gmail.com"
    assert saved.mailbox.security == "none"

    out = capsys.readouterr().out
    assert "Toilet roll" in out and "added [mailbox]" in out

    # The password is written beside the config, never into it.
    assert "abcdefghijklmnop" in (tmp_path / ".env").read_text()
    assert "abcdefghijklmnop" not in config.read_text()


def test_setup_mail_writes_nothing_when_the_server_refuses(tmp_path, monkeypatch, capsys) -> None:
    from trolley.setup_mail import Prompt

    from imap_server import TinyIMAP

    config = tmp_path / "config.toml"
    config.write_text(f'[server]\ndatabase = "{tmp_path / "trolley.db"}"\n')

    scripted = Prompt(
        ask=lambda question, default="": default,
        secret=lambda prompt="": "wrong",
        confirm=lambda question, default=True: True,
        say=print,
    )
    monkeypatch.setattr("trolley.setup_mail.terminal_prompt", lambda: scripted)

    with TinyIMAP({}) as server:
        exit_code = main([
            "--config", str(config), "setup-mail",
            "--username", "columfoley@gmail.com",
            "--host", "127.0.0.1", "--port", str(server.port), "--security", "none",
        ])

    assert exit_code == 1
    assert "[mailbox]" not in config.read_text()
    assert not (tmp_path / ".env").exists()
    assert "rejected" in capsys.readouterr().out


def test_slot_reports_and_pins_the_delivery_day(config_file, tmp_path, capsys) -> None:
    from datetime import date, timedelta

    run(config_file, "demo", "--weeks", "2")
    capsys.readouterr()

    # Eight Fridays of steak is a habit anyone can see.
    for week in range(8):
        friday = date.today() - timedelta(days=7 * week)
        while friday.weekday() != 4:
            friday -= timedelta(days=1)
        run(config_file, "add", "Tesco Irish Striploin Steak", "--date", friday.isoformat())
    capsys.readouterr()

    assert run(config_file, "slot", "steak") == 0
    assert "friday" in capsys.readouterr().out

    assert run(config_file, "slot", "steak", "any") == 0
    assert "whichever delivery is next" in capsys.readouterr().out

    assert run(config_file, "slot", "steak", "auto") == 0
    assert "back to learning" in capsys.readouterr().out


def test_slot_refuses_a_day_that_is_not_one(config_file, capsys) -> None:
    run(config_file, "add", "Tesco Irish Striploin Steak")
    capsys.readouterr()
    assert run(config_file, "slot", "steak", "funday") == 1
    assert "expected a weekday" in capsys.readouterr().err


def test_slot_says_when_it_does_not_know_the_item(config_file, capsys) -> None:
    assert run(config_file, "slot", "pomegranate molasses", "friday") == 1
    assert "no item matching" in capsys.readouterr().err
