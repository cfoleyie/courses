"""Walking someone through connecting a mailbox, and proving it works.

Setting this up by hand means an IMAP host, a folder name that is really a
Gmail label, and an app password that is not the password you think it is.
Each one fails in its own confusing way, so this asks for them in order, tries
the connection before writing anything down, and shows what it found in the
mailbox so you can see it reading your actual orders.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from getpass import getpass
from pathlib import Path
from typing import Callable

from .config import Config, MailboxConfig, clean_password
from .db import Database
from .mailbox import Mailbox, MailboxError, collect

#: Hosts for the mail providers people actually use, so the host question can
#: usually be answered by recognising the address.
KNOWN_HOSTS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("gmail.com", "googlemail.com"), "imap.gmail.com"),
    (("outlook.com", "hotmail.com", "live.com", "msn.com"), "outlook.office365.com"),
    (("yahoo.com", "yahoo.co.uk", "ymail.com"), "imap.mail.yahoo.com"),
    (("icloud.com", "me.com", "mac.com"), "imap.mail.me.com"),
    (("proton.me", "protonmail.com"), "127.0.0.1"),  # Needs the Proton Bridge.
    (("fastmail.com", "fastmail.fm"), "imap.fastmail.com"),
)

APP_PASSWORD_HELP = {
    "imap.gmail.com": (
        "Gmail needs an app password, not your normal one:\n"
        "  1. Turn on 2-Step Verification for THIS account, at\n"
        "     myaccount.google.com/signinoptions/twosv. App passwords do not\n"
        "     exist until it is on, and the page just says the setting is not\n"
        "     available for your account.\n"
        "  2. If you are signed in to more than one Google account, check the\n"
        "     account switcher: it is easy to turn 2-Step Verification on for\n"
        "     the wrong one.\n"
        "  3. Go to myaccount.google.com/apppasswords and make one called Trolley.\n"
        "  4. Google shows it as four groups of four. Paste it however you like;\n"
        "     the spaces are ignored.\n"
        "Nothing needs enabling in Gmail itself: Google removed the IMAP toggle in\n"
        "January 2025 and IMAP is now always on."
    ),
    "outlook.office365.com": (
        "Outlook needs an app password from account.microsoft.com/security if you\n"
        "have two-step verification turned on."
    ),
    "imap.mail.me.com": (
        "iCloud needs an app-specific password from account.apple.com, under\n"
        "Sign-In and Security."
    ),
}


def host_for(address: str) -> str:
    """Guess the IMAP host from an email address."""
    domain = address.partition("@")[2].casefold().strip()
    for domains, host in KNOWN_HOSTS:
        if domain in domains:
            return host
    return f"imap.{domain}" if domain else ""


@dataclass
class Prompt:
    """Where the answers come from, so this can be driven by a test."""

    ask: Callable[[str, str], str]
    secret: Callable[[str], str]
    confirm: Callable[[str, bool], bool]
    say: Callable[[str], None]


def terminal_prompt() -> Prompt:
    def ask(question: str, default: str = "") -> str:
        shown = f"{question} [{default}]: " if default else f"{question}: "
        return input(shown).strip() or default

    def confirm(question: str, default: bool = True) -> bool:
        answer = input(f"{question} [{'Y/n' if default else 'y/N'}]: ").strip().casefold()
        return default if not answer else answer.startswith("y")

    return Prompt(ask=ask, secret=getpass, confirm=confirm, say=print)


def mailbox_block(settings: MailboxConfig) -> str:
    """The config file section for these settings."""
    return (
        "\n[mailbox]\n"
        "enabled = true\n"
        f'host = "{settings.host}"\n'
        f"port = {settings.port}\n"
        f'username = "{settings.username}"\n'
        + (f'security = "{settings.security}"\n' if settings.security != "ssl" else "")
        + f'folder = "{settings.folder}"\n'
        f"search = '{settings.search}'\n"
        f"backfill_days = {settings.backfill_days}\n"
        f"poll_seconds = {settings.poll_seconds}\n"
    )


def write_config(path: Path, settings: MailboxConfig) -> str:
    """Add the [mailbox] section, or say why it was left alone."""
    block = mailbox_block(settings)
    if not path.exists():
        path.write_text(block.lstrip("\n"), encoding="utf-8")
        return f"wrote {path}"
    existing = path.read_text(encoding="utf-8")
    if "[mailbox]" in existing:
        return (
            f"{path} already has a [mailbox] section, so it was left alone. "
            f"Replace it with:\n{block}"
        )
    path.write_text(existing.rstrip("\n") + "\n" + block, encoding="utf-8")
    return f"added [mailbox] to {path}"


def write_env(path: Path, password: str) -> str:
    """Keep the password out of the config file and off the command line."""
    line = f"TROLLEY_IMAP_PASSWORD={password}\n"
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    kept = [
        row
        for row in existing.splitlines()
        if row.strip() and not row.startswith("TROLLEY_IMAP_PASSWORD=")
    ]
    path.write_text("\n".join([*kept, line.rstrip("\n")]) + "\n", encoding="utf-8")
    path.chmod(0o600)
    return f"saved the password to {path} (readable only by you)"


def run(
    config: Config,
    config_path: Path,
    db: Database,
    prompt: Prompt | None = None,
    *,
    connect: Callable[[], object] | None = None,
    defaults: MailboxConfig | None = None,
    given: frozenset[str] = frozenset(),
) -> int:
    """Ask, test, show, then save. Returns a process exit code.

    `given` names the settings that came from the command line. Those are not
    asked about again: passing one is how you say you already know the answer.
    """
    prompt = prompt or terminal_prompt()
    say = prompt.say
    start = defaults or config.mailbox

    def settle(field: str, question: str, fallback: str) -> str:
        supplied = str(getattr(start, field) or "")
        if field in given and supplied:
            say(f"{question}: {supplied}")
            return supplied
        return prompt.ask(question, supplied or fallback)

    say("Connecting Trolley to the mailbox your order emails arrive in.\n")

    username = settle("username", "Your email address", "")
    if not username:
        say("No address given, so nothing was changed.")
        return 1
    host = settle("host", "IMAP host", host_for(username))
    port = int(settle("port", "IMAP port", "993") or 993)

    help_text = APP_PASSWORD_HELP.get(host)
    if help_text:
        say("\n" + help_text + "\n")
    password = clean_password(prompt.secret("App password (not shown as you type): "))
    if not password:
        say("No password given, so nothing was changed.")
        return 1

    say(
        "\nWhich folder holds the order emails? INBOX is everything. If you filter\n"
        "Tesco mail into a label, name that label instead and Trolley sees nothing else."
    )
    folder = settle("folder", "Folder", "INBOX")
    search = settle("search", "IMAP search for grocery mail", 'FROM "tesco"')

    settings = replace(
        start,
        enabled=True,
        host=host,
        port=port,
        username=username,
        folder=folder,
        search=search,
    )
    if settings.security != "ssl":
        say(f"(connecting with security = {settings.security!r})")
    # The mailbox reads the password from the environment, like the server will.
    os.environ["TROLLEY_IMAP_PASSWORD"] = password

    box = Mailbox(settings, connect=connect) if connect else Mailbox(settings)
    say("\nTrying it...")
    try:
        say("  " + box.check())
    except MailboxError as exc:
        say(f"\nThat did not work.\n  {exc}\n\nNothing was saved. Fix that and run this again.")
        return 1

    trial = replace(config, mailbox=settings)
    try:
        result = collect(db, trial, mailbox=box, dry_run=True, limit=20)
    except MailboxError as exc:
        say(f"\nConnected, but reading failed:\n  {exc}")
        return 1

    say(f"\nReading a sample: {result.summary()}")
    # The same products appear in order after order, so show each once: the
    # point is to prove the names are being read right, not to list every line.
    seen: set[str] = set()
    for match in result.ingest.matches:
        if match.raw_name in seen:
            continue
        seen.add(match.raw_name)
        say(f"    {match.raw_name[:52]:54} -> {match.item_name}")
        if len(seen) >= 15:
            say(f"    ... and {len(result.ingest.matches) - len(seen)} more lines")
            break
    if not result.receipts:
        say(
            "\nNo order emails matched. The connection is fine, so it is the search:\n"
            f"  {search!r} in folder {folder!r} found nothing readable.\n"
            "Try folder INBOX, or widen the search, then run this again."
        )
        if not prompt.confirm("Save these settings anyway?", False):
            return 1

    if not prompt.confirm("\nSave this to the config?", True):
        say("Nothing was saved.")
        return 0
    say("  " + write_config(config_path, settings))

    if prompt.confirm("Save the password to a .env file beside it?", True):
        say("  " + write_env(config_path.parent / ".env", password))
        say("  Load it with: set -a; source .env; set +a")
    else:
        say("  Put this in the environment before starting Trolley:")
        say("      export TROLLEY_IMAP_PASSWORD='<your app password>'")

    say(
        "\nDone. Next:\n"
        "  trolley mail --all     read the back catalogue (once)\n"
        "  trolley serve          from here it keeps itself up to date"
    )
    return 0
