"""The guided setup, which is the only part most people will ever run."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from trolley.config import Config, MailboxConfig, load_config
from trolley.db import Database
from trolley.setup_mail import Prompt, host_for, run, write_config, write_env

from fake_imap import FakeIMAP, build_email, receipt_html

MILK = (2, "Tesco British Semi Skimmed Milk 2.272L", "2.50")
ROLL = (1, "Tesco Toilet Tissue 9 Roll", "4.00")

GMAIL_APP_PASSWORD = "abcdefghijklmnop"


def order_email() -> bytes:
    return build_email(
        "Your Tesco order confirmation",
        receipt_html("A1", date(2026, 9, 1), [MILK, ROLL]),
        date(2026, 9, 1),
    )


class Answers:
    """Scripted replies, so the whole conversation can be exercised."""

    def __init__(self, answers: list[str], secret: str, confirm: bool | list[bool] = True) -> None:
        self.answers = list(answers)
        self.secret_value = secret
        self.confirms = confirm if isinstance(confirm, list) else None
        self.confirm_value = confirm if isinstance(confirm, bool) else True
        self.said: list[str] = []
        self.questions: list[str] = []

    def prompt(self) -> Prompt:
        def ask(question: str, default: str = "") -> str:
            self.questions.append(question)
            return self.answers.pop(0) if self.answers else default

        def secret(_: str) -> str:
            return self.secret_value

        def confirm(question: str, default: bool = True) -> bool:
            self.questions.append(question)
            if self.confirms is not None:
                return self.confirms.pop(0) if self.confirms else default
            return self.confirm_value

        return Prompt(ask=ask, secret=secret, confirm=confirm, say=self.said.append)

    @property
    def transcript(self) -> str:
        return "\n".join(self.said)


@pytest.fixture
def gmail() -> FakeIMAP:
    return FakeIMAP(
        {1: order_email()},
        expect_password=GMAIL_APP_PASSWORD,
        folders=("INBOX", "Tesco", '"Shopping/Tesco"'),
    )


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    path = tmp_path / "config.toml"
    path.write_text('[server]\ndatabase = "trolley.db"\n', encoding="utf-8")
    return path


def drive(config, db, config_path, gmail, answers: Answers) -> int:
    return run(
        config,
        config_path,
        db,
        answers.prompt(),
        connect=lambda: gmail,
        defaults=MailboxConfig(),
    )


@pytest.mark.parametrize(
    "address, host",
    [
        ("columfoley@gmail.com", "imap.gmail.com"),
        ("someone@googlemail.com", "imap.gmail.com"),
        ("someone@outlook.com", "outlook.office365.com"),
        ("someone@icloud.com", "imap.mail.me.com"),
        ("someone@example.ie", "imap.example.ie"),
        ("", ""),
    ],
)
def test_the_host_is_guessed_from_the_address(address: str, host: str) -> None:
    assert host_for(address) == host


def test_a_working_gmail_setup_writes_the_config(db, config, config_path, gmail) -> None:
    answers = Answers(
        ["columfoley@gmail.com", "imap.gmail.com", "993", "INBOX", 'FROM "tesco"'],
        secret=GMAIL_APP_PASSWORD,
    )
    assert drive(config, db, config_path, gmail, answers) == 0

    saved = load_config(config_path)
    assert saved.mailbox.enabled
    assert saved.mailbox.host == "imap.gmail.com"
    assert saved.mailbox.username == "columfoley@gmail.com"
    assert saved.mailbox.search == 'FROM "tesco"'


def test_the_app_password_is_accepted_with_the_spaces_google_shows(
    db, config, config_path, gmail
) -> None:
    """Pasting it exactly as displayed is the obvious thing to do."""
    answers = Answers(
        ["columfoley@gmail.com", "imap.gmail.com", "993", "INBOX", 'FROM "tesco"'],
        secret="abcd efgh ijkl mnop",
    )
    assert drive(config, db, config_path, gmail, answers) == 0
    assert gmail.password_seen == GMAIL_APP_PASSWORD


def test_the_setup_shows_the_orders_it_found(db, config, config_path, gmail) -> None:
    answers = Answers(
        ["columfoley@gmail.com", "imap.gmail.com", "993", "INBOX", 'FROM "tesco"'],
        secret=GMAIL_APP_PASSWORD,
    )
    drive(config, db, config_path, gmail, answers)
    assert "Toilet roll" in answers.transcript
    assert "Milk" in answers.transcript


def test_nothing_is_written_while_testing(db, config, config_path, gmail) -> None:
    """The sample read is a dry run: setup must not half-import your history."""
    answers = Answers(
        ["columfoley@gmail.com", "imap.gmail.com", "993", "INBOX", 'FROM "tesco"'],
        secret=GMAIL_APP_PASSWORD,
    )
    drive(config, db, config_path, gmail, answers)
    assert db.items() == [] and db.purchases() == []


def test_a_gmail_label_with_a_space_is_quoted_for_the_server(db, config, config_path) -> None:
    server = FakeIMAP(
        {1: order_email()},
        expect_password=GMAIL_APP_PASSWORD,
        folders=('"Shopping/Tesco Orders"',),
    )
    answers = Answers(
        ["columfoley@gmail.com", "imap.gmail.com", "993", "Shopping/Tesco Orders", 'FROM "tesco"'],
        secret=GMAIL_APP_PASSWORD,
    )
    assert drive(config, db, config_path, server, answers) == 0
    assert server.selected == '"Shopping/Tesco Orders"'


def test_a_wrong_password_stops_before_anything_is_saved(db, config, config_path, gmail) -> None:
    answers = Answers(
        ["columfoley@gmail.com", "imap.gmail.com", "993", "INBOX", 'FROM "tesco"'],
        secret="my normal google password",
    )
    assert drive(config, db, config_path, gmail, answers) == 1
    assert "app password" in answers.transcript
    assert "[mailbox]" not in config_path.read_text()


def test_googles_browser_login_alert_is_explained(db, config, config_path) -> None:
    server = FakeIMAP({}, web_login_alert=True)
    answers = Answers(
        ["columfoley@gmail.com", "imap.gmail.com", "993", "INBOX", 'FROM "tesco"'],
        secret=GMAIL_APP_PASSWORD,
    )
    assert drive(config, db, config_path, server, answers) == 1
    assert "apppasswords" in answers.transcript


def test_a_wrong_label_says_what_a_gmail_folder_is(db, config, config_path) -> None:
    server = FakeIMAP({1: order_email()}, expect_password=GMAIL_APP_PASSWORD, folders=("INBOX",))
    answers = Answers(
        ["columfoley@gmail.com", "imap.gmail.com", "993", "Tesco Stuff", 'FROM "tesco"'],
        secret=GMAIL_APP_PASSWORD,
    )
    assert drive(config, db, config_path, server, answers) == 1
    assert "label" in answers.transcript


def test_finding_no_orders_is_called_out_rather_than_declared_a_success(
    db, config, config_path
) -> None:
    server = FakeIMAP(
        {1: build_email("Your Clubcard points", "<p>Nothing to see.</p>")},
        expect_password=GMAIL_APP_PASSWORD,
    )
    answers = Answers(
        ["columfoley@gmail.com", "imap.gmail.com", "993", "INBOX", 'FROM "tesco"'],
        secret=GMAIL_APP_PASSWORD,
        confirm=[False],
    )
    assert drive(config, db, config_path, server, answers) == 1
    assert "No order emails matched" in answers.transcript


def test_declining_to_save_changes_nothing(db, config, config_path, gmail) -> None:
    answers = Answers(
        ["columfoley@gmail.com", "imap.gmail.com", "993", "INBOX", 'FROM "tesco"'],
        secret=GMAIL_APP_PASSWORD,
        confirm=[False],
    )
    assert drive(config, db, config_path, gmail, answers) == 0
    assert "[mailbox]" not in config_path.read_text()


def test_the_password_goes_to_a_private_env_file_not_the_config(
    db, config, config_path, gmail
) -> None:
    answers = Answers(
        ["columfoley@gmail.com", "imap.gmail.com", "993", "INBOX", 'FROM "tesco"'],
        secret=GMAIL_APP_PASSWORD,
        confirm=[True, True],
    )
    drive(config, db, config_path, gmail, answers)

    env = config_path.parent / ".env"
    assert f"TROLLEY_IMAP_PASSWORD={GMAIL_APP_PASSWORD}" in env.read_text()
    assert env.stat().st_mode & 0o777 == 0o600
    assert GMAIL_APP_PASSWORD not in config_path.read_text()


def test_an_existing_mailbox_section_is_not_silently_overwritten(
    db, config, config_path, gmail
) -> None:
    config_path.write_text(
        '[server]\ndatabase = "trolley.db"\n\n[mailbox]\nenabled = false\nhost = "old.example"\n'
    )
    answers = Answers(
        ["columfoley@gmail.com", "imap.gmail.com", "993", "INBOX", 'FROM "tesco"'],
        secret=GMAIL_APP_PASSWORD,
    )
    drive(config, db, config_path, gmail, answers)
    assert "old.example" in config_path.read_text()
    assert "already has a [mailbox] section" in answers.transcript


def test_giving_no_address_stops_politely(db, config, config_path, gmail) -> None:
    answers = Answers([""], secret=GMAIL_APP_PASSWORD)
    assert drive(config, db, config_path, gmail, answers) == 1
    assert "nothing was changed" in answers.transcript.casefold()


def test_the_written_section_is_valid_toml(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    settings = MailboxConfig(
        enabled=True, host="imap.gmail.com", username="a@gmail.com",
        folder="Shopping/Tesco", search='FROM "tesco"',
    )
    write_config(path, settings)
    assert load_config(path).mailbox.folder == "Shopping/Tesco"


def test_an_env_file_keeps_its_other_settings(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("TROLLEY_NTFY_TOKEN=abc\nTROLLEY_IMAP_PASSWORD=old\n")
    write_env(env, "new-password")
    text = env.read_text()
    assert "TROLLEY_NTFY_TOKEN=abc" in text
    assert "TROLLEY_IMAP_PASSWORD=new-password" in text
    assert "old" not in text
