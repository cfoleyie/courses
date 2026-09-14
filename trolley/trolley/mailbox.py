"""Reading order emails straight out of a mailbox, so nothing needs importing.

This is the part that makes the app worth having. Point it at the mailbox the
confirmations land in and the history keeps itself up to date: an order is
placed, the email arrives, the next poll picks it up, and the suggestions for
the following delivery already know about it.

Only IMAP is used, which means the connection is outbound only. Nothing has to
be exposed to the internet for this to work from a machine at home.

Progress is tracked by IMAP UID rather than by read/unread flags, so the app
never has to modify your inbox to keep its place, and reading mail on your
phone does not hide it from the importer.
"""

from __future__ import annotations

import imaplib
import logging
import re
import socket
import ssl
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Callable, Iterator, Protocol

from .config import Config, MailboxConfig
from .db import Database
from .importers.base import ImportError_
from .importers.email_import import message_to_text, parse_receipt_text
from .ingest import IngestResult, ingest
from .model import ParsedOrder

_LOG = logging.getLogger(__name__)

#: State keys. UIDs are only meaningful within one UIDVALIDITY, so both are
#: stored and the position is abandoned if the server renumbers the folder.
UID_KEY = "mailbox:last_uid"
VALIDITY_KEY = "mailbox:uidvalidity"

#: Read at most this many messages in one pass, so a first run over years of
#: mail makes steady progress instead of one enormous fetch.
BATCH = 200

IMAP_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

#: Folder names only need quoting when they are not a plain single word, which
#: a Gmail label very often is not ("Tesco Orders", "Shopping/Tesco").
_PLAIN_FOLDER = re.compile(r"^[A-Za-z0-9_./-]+$")


def quote_folder(name: str) -> str:
    """Quote a mailbox name for IMAP, because imaplib will not do it for you.

    Without this, a label with a space in it is sent as two arguments and the
    server rejects the whole command.
    """
    name = name or "INBOX"
    if _PLAIN_FOLDER.match(name):
        return name
    escaped = name.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"' 


class MailboxError(Exception):
    """The mailbox could not be read. The message says what to change."""


class ImapLike(Protocol):  # pragma: no cover - a structural type, not code
    def login(self, user: str, password: str): ...
    def select(self, mailbox: str, readonly: bool): ...
    def uid(self, command: str, *args): ...
    def status(self, mailbox: str, names: str): ...
    def logout(self): ...


@dataclass
class Message:
    uid: int
    raw: bytes


@dataclass
class CollectResult:
    """What one pass over the mailbox did."""

    examined: int = 0
    receipts: int = 0
    unreadable: int = 0
    ingest: IngestResult = field(default_factory=IngestResult)
    reset: bool = False

    def summary(self) -> str:
        if not self.examined:
            return "no new mail"
        parts = [f"{self.examined} message{'' if self.examined == 1 else 's'} checked"]
        if self.receipts:
            parts.append(self.ingest.summary())
        if self.unreadable:
            parts.append(f"{self.unreadable} not a receipt")
        return ", ".join(parts)


def imap_date(day: date) -> str:
    """A date in the form IMAP's SEARCH wants: 01-Jan-2026."""
    return f"{day.day:02d}-{IMAP_MONTHS[day.month - 1]}-{day.year}"


def _friendly(error: Exception, config: MailboxConfig) -> MailboxError:
    """Turn IMAP's terse failures into something that says what to do."""
    text = str(error)
    gmail = "gmail" in config.host.casefold() or "googlemail" in config.host.casefold()

    if "support.google.com/mail/accounts/answer/78754" in text or "log in via your web browser" in text:
        return MailboxError(
            "Google refused the sign-in. That message means the password was accepted as a "
            "shape but not as an app password: generate one at "
            "myaccount.google.com/apppasswords and use that as TROLLEY_IMAP_PASSWORD"
        )
    if "AUTHENTICATIONFAILED" in text or "Invalid credentials" in text or "LOGIN failed" in text:
        if gmail:
            hint = (
                "Google rejected the password. It must be a 16-character app password from "
                "myaccount.google.com/apppasswords, not your normal Google password. If that "
                "page says the setting is not available, 2-Step Verification is not on for "
                "this account yet: turn it on at myaccount.google.com/signinoptions/twosv and "
                "the app password option appears. Check the account switcher first if you are "
                "signed in to more than one Google account"
            )
        else:
            hint = f"the password for {config.username} was rejected"
        return MailboxError(f"{config.host}: {hint}")
    if isinstance(error, (socket.gaierror, socket.timeout, TimeoutError)):
        return MailboxError(f"could not reach {config.host}:{config.port} ({text})")
    if isinstance(error, ssl.SSLError):
        return MailboxError(f"TLS failed talking to {config.host}:{config.port} ({text})")
    if "NONEXISTENT" in text or "Unknown Mailbox" in text or "does not exist" in text.casefold():
        extra = (
            ' In Gmail a folder is a label: use the label exactly as it appears, nesting '
            'with a slash ("Shopping/Tesco"), or "INBOX" for the inbox itself.'
            if gmail
            else ""
        )
        return MailboxError(
            f"no folder called {config.folder!r} on {config.host}. "
            f"Folder names are case sensitive.{extra}"
        )
    return MailboxError(f"{config.host}: {text}")


class Mailbox:
    """A read-only view of one IMAP folder, narrowed to grocery mail."""

    def __init__(
        self,
        config: MailboxConfig,
        connect: Callable[[], ImapLike] | None = None,
    ) -> None:
        self.config = config
        self._connect_factory = connect or self._default_connect

    def _default_connect(self) -> ImapLike:
        """Open the connection the way this server expects to be talked to."""
        host, port = self.config.host, self.config.port
        if self.config.security == "none":
            return imaplib.IMAP4(host, port, timeout=30)
        if self.config.security == "starttls":
            conn = imaplib.IMAP4(host, port, timeout=30)
            conn.starttls(ssl.create_default_context())
            return conn
        return imaplib.IMAP4_SSL(host, port, timeout=30)

    @contextmanager
    def session(self, readonly: bool = True) -> Iterator[ImapLike]:
        config = self.config
        try:
            conn = self._connect_factory()
        except Exception as exc:
            raise _friendly(exc, config) from exc
        try:
            conn.login(config.username, config.password)
            status, detail = conn.select(quote_folder(config.folder), readonly)
            if status != "OK":
                # The server's own words usually name the problem ("NONEXISTENT"),
                # so they go through the same translation as a raised error.
                said = detail[0] if detail else b""
                raise _friendly(
                    Exception(said.decode(errors="replace") if isinstance(said, bytes) else str(said)),
                    config,
                )
            yield conn
        except MailboxError:
            raise
        except Exception as exc:
            raise _friendly(exc, config) from exc
        finally:
            try:
                conn.logout()
            except Exception:  # pragma: no cover - nothing useful to do
                pass

    def uid_validity(self, conn: ImapLike) -> str:
        status, data = conn.status(quote_folder(self.config.folder), "(UIDVALIDITY)")
        if status != "OK" or not data:
            return ""
        found = re.search(rb"UIDVALIDITY\s+(\d+)", data[0] or b"")
        return found.group(1).decode() if found else ""

    def search(self, conn: ImapLike, since_uid: int | None) -> list[int]:
        """UIDs of candidate messages, oldest first."""
        criteria = self.config.search.strip()
        if since_uid:
            # Everything newer than the last one imported. The server may
            # include `since_uid` itself, so it is filtered out below.
            window = f"UID {since_uid}:*"
        else:
            earliest = date.today() - timedelta(days=max(self.config.backfill_days, 1))
            window = f"SINCE {imap_date(earliest)}"
        query = f"({criteria}) {window}" if criteria else window

        status, data = conn.uid("SEARCH", None, query)
        if status != "OK":
            raise MailboxError(f"mailbox search failed: {query}")
        raw = (data[0] or b"").split()
        uids = sorted({int(value) for value in raw})
        return [uid for uid in uids if not since_uid or uid > since_uid]

    def fetch(self, conn: ImapLike, uids: list[int]) -> Iterator[Message]:
        for uid in uids:
            status, data = conn.uid("FETCH", str(uid), "(RFC822)")
            if status != "OK" or not data or not data[0]:
                _LOG.warning("could not fetch message %s", uid)
                continue
            payload = data[0][1] if isinstance(data[0], tuple) else data[0]
            if isinstance(payload, bytes):
                yield Message(uid=uid, raw=payload)

    def check(self) -> str:
        """Prove the settings work, without importing anything."""
        with self.session() as conn:
            validity = self.uid_validity(conn)
            uids = self.search(conn, None)
        return (
            f"connected to {self.config.host} as {self.config.username}; "
            f"folder {self.config.folder!r} has {len(uids)} message(s) matching "
            f"{self.config.search!r} in the last {self.config.backfill_days} days "
            f"(uidvalidity {validity or 'unknown'})"
        )


def read_order(raw: bytes) -> ParsedOrder | None:
    """Parse one message, or None if it is not a receipt at all."""
    try:
        text, sent = message_to_text(raw)
        return parse_receipt_text(text, sent)
    except ImportError_:
        return None
    except Exception as exc:  # A malformed message must not stop the poll.
        _LOG.debug("skipping unreadable message: %s", exc)
        return None


def collect(
    db: Database,
    config: Config,
    *,
    mailbox: Mailbox | None = None,
    dry_run: bool = False,
    limit: int = BATCH,
) -> CollectResult:
    """Read new order emails and fold them into the history.

    Safe to call repeatedly: the last UID read is remembered, so each message
    is only ever examined once, and order references stop a message that does
    arrive twice from being counted twice.
    """
    settings = config.mailbox
    box = mailbox or Mailbox(settings)
    result = CollectResult()

    with box.session() as conn:
        validity = box.uid_validity(conn)
        stored_validity = db.get_state(VALIDITY_KEY)
        stored_uid = db.get_state(UID_KEY)

        if validity and stored_validity and validity != stored_validity:
            # The server renumbered the folder, so old UIDs mean nothing now.
            _LOG.warning("mailbox was renumbered; re-reading from the start")
            stored_uid, result.reset = None, True

        since_uid = int(stored_uid) if stored_uid else None
        uids = box.search(conn, since_uid)[:limit]
        if not uids:
            return result

        orders: list[ParsedOrder] = []
        for message in box.fetch(conn, uids):
            result.examined += 1
            order = read_order(message.raw)
            if order is None:
                result.unreadable += 1
                continue
            result.receipts += 1
            orders.append(order)

        if orders:
            result.ingest = ingest(db, orders, config, dry_run=dry_run)

        if not dry_run:
            # Advance past everything examined, receipts and marketing alike,
            # or the same newsletters would be re-read on every poll.
            db.set_state(UID_KEY, str(max(uids)))
            if validity:
                db.set_state(VALIDITY_KEY, validity)

    # Outside the session: the read-only one above cannot set flags.
    if not dry_run and settings.mark_seen and uids:
        _mark_seen(box, uids)
    return result


def collect_all(
    db: Database,
    config: Config,
    *,
    mailbox: Mailbox | None = None,
    dry_run: bool = False,
    max_passes: int = 50,
) -> CollectResult:
    """Keep reading until the mailbox has nothing new, for a first backfill.

    A dry run cannot make progress, because progress is what it refuses to
    record, so it stops after one pass rather than looping for ever.
    """
    box = mailbox or Mailbox(config.mailbox)
    total = CollectResult()
    for _ in range(max_passes):
        pass_result = collect(db, config, mailbox=box, dry_run=dry_run)
        total.examined += pass_result.examined
        total.receipts += pass_result.receipts
        total.unreadable += pass_result.unreadable
        total.reset = total.reset or pass_result.reset
        total.ingest.orders += pass_result.ingest.orders
        total.ingest.lines += pass_result.ingest.lines
        total.ingest.added += pass_result.ingest.added
        total.ingest.duplicates += pass_result.ingest.duplicates
        total.ingest.skipped_orders += pass_result.ingest.skipped_orders
        total.ingest.replaced_orders += pass_result.ingest.replaced_orders
        total.ingest.new_items.extend(pass_result.ingest.new_items)
        total.ingest.matches.extend(pass_result.ingest.matches)
        if pass_result.examined < BATCH or dry_run:
            break
    total.ingest.dry_run = dry_run
    return total


def _mark_seen(box: Mailbox, uids: list[int]) -> None:
    """Flag imported mail as read, for people who want a tidy inbox."""
    try:
        with box.session(readonly=False) as conn:
            conn.uid("STORE", ",".join(str(uid) for uid in uids), "+FLAGS", "(\\Seen)")
    except MailboxError as exc:  # Not worth failing an import over.
        _LOG.warning("could not mark messages read: %s", exc)


def reset_position(db: Database) -> None:
    """Forget where we got to, so the next pass re-reads the whole search."""
    db.set_state(UID_KEY, "")
    db.set_state(VALIDITY_KEY, "")
